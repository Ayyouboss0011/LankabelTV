"""
Download Queue Manager for LankabelTV
Handles global download queue processing and status tracking
"""

import threading
import time
import logging
import re
from typing import Optional
from datetime import datetime
from .database import UserDatabase
from ..megakino.megakino import MegakinoClient, is_megakino_url
from ..megakino.megakino_stream_finder import download_stream

# Pause after a failed episode so rate-limited providers (VOE/DDoS-Guard)
# have time to recover instead of hammering them in a tight failure loop
FAILED_EPISODE_BACKOFF = 3.0


class DownloadQueueManager:
    """Manages the global download queue processing with in-memory storage"""

    def __init__(self, database: Optional[UserDatabase] = None):
        self.db = database  # Only used for user auth, not download storage
        self.is_processing = False
        self.current_download_id = None
        self.worker_thread = None
        self._stop_event = threading.Event()
        self._cancelled_jobs = set()

        # In-memory download queue storage
        self._next_id = 1
        # RLock: methods may re-enter lock-protected helpers (e.g. cancel from stop_episode)
        self._queue_lock = threading.RLock()
        self._active_downloads = {}  # id -> download_job dict
        self._cancelled_episodes = set() # set of (queue_id, ep_url)
        self._completed_downloads = []  # list of completed download jobs (keep last N)
        self._max_completed_history = 10
        self._skip_flags = set()
        self._tracker_scan_status = {} # tracker_id -> bool (is_scanning)
        self._tracker_debug_messages = {} # tracker_id -> list of strings

    def start_queue_processor(self):
        """Start the background queue processor"""
        if not self.is_processing:
            self.is_processing = True
            self._stop_event.clear()
            self.worker_thread = threading.Thread(
                target=self._process_queue, daemon=True
            )
            self.worker_thread.start()
            logging.info("Download queue processor started")

    def stop_queue_processor(self):
        """Stop the background queue processor"""
        if self.is_processing:
            self.is_processing = False
            self._stop_event.set()
            if self.worker_thread:
                self.worker_thread.join(timeout=5)
            logging.info("Download queue processor stopped")

    def start_tracker_processor(self):
        """Start the background tracker processor"""
        if not hasattr(self, "tracker_thread") or self.tracker_thread is None:
            self.tracker_thread = threading.Thread(
                target=self._process_trackers, daemon=True
            )
            self.tracker_thread.start()
            logging.info("Tracker processor started")

    def trigger_tracker_scan(self):
        """Manually trigger a tracker scan immediately"""
        logging.info("Manual tracker scan triggered")
        threading.Thread(target=self._run_single_scan, daemon=True).start()
        return True

    def _run_single_scan(self):
        """Run a single pass of checking all trackers"""
        try:
            if self.db:
                trackers = self.db.get_trackers()
                logging.info(f"Starting manual scan of {len(trackers)} trackers")
                for tracker in trackers:
                    self._tracker_scan_status[tracker["id"]] = True
                    try:
                        self._check_single_tracker(tracker)
                    finally:
                        self._tracker_scan_status[tracker["id"]] = False
                    time.sleep(0.5) # Fast scan
                logging.info("Manual tracker scan completed")
        except Exception as e:
            logging.error(f"Error in manual tracker scan: {e}")

    def _process_trackers(self):
        """Background worker that checks trackers for new episodes"""
        while True:
            try:
                if self.db:
                    trackers = self.db.get_trackers()
                    for tracker in trackers:
                        self._check_single_tracker(tracker)
                        time.sleep(5)  # Pause between trackers to be polite
            except Exception as e:
                logging.error(f"Error in tracker processor: {e}")

            # Wait for 1 hour before next check
            for _ in range(3600):
                if hasattr(self, "_stop_event") and self._stop_event.is_set():
                    return
                time.sleep(1)

    def _check_single_tracker(self, tracker):
        """Check a single tracker for new episodes"""
        tracker_id = tracker["id"]
        self._tracker_debug_messages[tracker_id] = []
        
        def debug(msg, is_error=False):
            prefix = "ERROR: " if is_error else ""
            full_msg = f"[{tracker['anime_title']}] {prefix}{msg}"
            self._tracker_debug_messages[tracker_id].append(full_msg)
            if is_error: logging.error(full_msg)
            else: logging.info(full_msg)

        try:
            from ..common import get_season_episodes_details
            from ..entry import _detect_site_from_url
            from .. import config

            debug(f"Starting scan. Current Stand: S{tracker['last_season']} E{tracker['last_episode']}")
            
            series_url = tracker["series_url"]
            last_season = tracker["last_season"]
            last_episode = tracker["last_episode"]
            target_language = tracker["language"]

            # MegaKino series tracking (one tracker per season page)
            if is_megakino_url(str(series_url)):
                self._check_megakino_tracker(tracker, debug)
                return

            lang_map = {
                "German Dub": 1, "German Sub": 3, "English Dub": 2, "English Sub": 2,
                "Language ID 1": 1, "Language ID 2": 2, "Language ID 3": 3,
            }
            target_lang_id = lang_map.get(target_language)

            if "/anime/stream/" in series_url:
                slug = series_url.split("/anime/stream/")[-1].rstrip("/")
                base_url = config.ANIWORLD_TO
                stream_path = "anime/stream"
            elif config.S_TO in series_url:
                # Clean up S.to URL to get a pure slug
                # e.g. https://s.to/serie/stream/serie/a-knight-of-the-seven-kingdoms -> a-knight-of-the-seven-kingdoms
                temp_slug = series_url.replace(config.S_TO, "").strip("/")
                # Split and filter out "serie" and "stream" keywords
                parts = [p for p in temp_slug.split("/") if p not in ["serie", "stream"]]
                if not parts: return
                slug = parts[0]
                base_url = config.S_TO
                stream_path = "serie/stream"
            else:
                return

            debug(f"Fetching series details for slug: {slug}")
            all_seasons_details = get_season_episodes_details(slug, base_url)
            if not all_seasons_details:
                debug("No seasons found or failed to fetch details", is_error=True)
                return

            debug(f"Found {len(all_seasons_details)} seasons")
            new_episodes = []
            updated_s, updated_e = tracker["last_season"], tracker["last_episode"]
            sorted_seasons = sorted(all_seasons_details.keys())

            for s_num in sorted_seasons:
                if s_num < tracker["last_season"]: continue
                episodes = all_seasons_details[s_num]
                debug(f"Checking Season {s_num} ({len(episodes)} episodes)")
                for ep_detail in episodes:
                    e_num = ep_detail["episode"]
                    if s_num == tracker["last_season"] and e_num <= tracker["last_episode"]: continue
                    available_langs = ep_detail.get("languages", [])
                    is_available = False
                    for l in available_langs:
                        if (isinstance(l, int) and l == target_lang_id) or \
                           (isinstance(l, str) and (l == target_language or "DE Dub" in l or "DE Sub" in l)):
                            is_available = True
                            break
                    if not is_available:
                        try:
                            from ..models import Episode
                            ep_url = f"{base_url}/{stream_path}/{slug}/staffel-{s_num}/episode-{e_num}"
                                
                            debug(f"Verifying S{s_num}E{e_num} via episode page...")
                            temp_ep = Episode(link=ep_url); temp_ep.auto_fill_details()
                            verified_langs = temp_ep.language_name
                            
                            debug(f"S{s_num}E{e_num}: Verified languages: {verified_langs}")
                            for l in verified_langs:
                                l_norm, t_norm = l.lower(), target_language.lower()
                                if l == target_language or l_norm == t_norm: is_available = True; break
                                if "german dub" in t_norm or "de dub" in t_norm or "deutsch" in t_norm:
                                    if "de dub" in l_norm or "german dub" in l_norm or "synchronisation" in l_norm or l_norm == "deutsch" or l_norm == "de": is_available = True; break
                                elif "german sub" in t_norm or "de sub" in t_norm:
                                    if "de sub" in l_norm or "german sub" in l_norm or "untertitel" in l_norm: is_available = True; break
                                elif "english sub" in t_norm or "en sub" in t_norm:
                                    if "en sub" in l_norm or "english sub" in l_norm or l_norm == "englisch" or l_norm == "en": is_available = True; break
                                elif "english dub" in t_norm or "en dub" in t_norm:
                                    if "en dub" in l_norm or "english dub" in l_norm or l_norm == "englisch" or l_norm == "en": is_available = True; break
                            
                            if is_available:
                                # Also verify provider availability
                                verified_providers = [p.lower() for p in temp_ep.provider_name]
                                debug(f"S{s_num}E{e_num}: Verified providers: {verified_providers}")
                                if tracker["provider"].lower() not in verified_providers and "auto" not in tracker["provider"].lower():
                                    debug(f"S{s_num}E{e_num}: Required provider {tracker['provider']} not found in {verified_providers}")
                                    is_available = False
                        except Exception as e:
                            debug(f"S{s_num}E{e_num}: Failed to verify: {e}", is_error=True)
                    if not is_available: continue
                    debug(f"FOUND NEW EPISODE: S{s_num} E{e_num}")
                    ep_url = f"{base_url}/{stream_path}/{slug}/staffel-{s_num}/episode-{e_num}"
                    new_episodes.append(ep_url)
                    if s_num > updated_s or (s_num == updated_s and e_num > updated_e):
                        updated_s, updated_e = s_num, e_num
            if new_episodes:
                self.add_download(anime_title=tracker["anime_title"], episode_urls=new_episodes, language=tracker["language"], provider=tracker["provider"], total_episodes=len(new_episodes), created_by=tracker["user_id"])
                self.db.update_tracker_last_episode(tracker["id"], updated_s, updated_e)
        except Exception as e:
            debug(f"Fatal error during scan: {str(e)}", is_error=True)

    def _check_megakino_tracker(self, tracker, debug):
        """Check a MegaKino series season page for new episodes."""
        try:
            from ..megakino.megakino import MegakinoClient

            page_url = str(tracker["series_url"])
            if page_url.startswith("megakino:"):
                page_url = page_url.split(":", 2)[2]
            page_url = page_url.split("::")[0]

            debug(f"Fetching MegaKino page: {page_url}")
            details = MegakinoClient().get_details(page_url)
            if not details or details.get("media_type") != "series":
                debug("No MegaKino series details found", is_error=True)
                return

            season = int(details.get("season") or 1)
            last_episode = int(tracker["last_episode"] or 0)
            resolved_url = details.get("url") or page_url
            new_episodes = []
            updated_e = last_episode

            for ep in details.get("episodes", []):
                ep_num = int(ep.get("episode") or 0)
                if ep_num <= last_episode or not ep.get("streams"):
                    continue
                debug(f"FOUND NEW EPISODE: S{season} E{ep_num}")
                new_episodes.append(f"megakino:series:{resolved_url}::ep{ep_num}")
                updated_e = max(updated_e, ep_num)

            if new_episodes:
                self.add_download(
                    anime_title=tracker["anime_title"],
                    episode_urls=new_episodes,
                    language=tracker["language"],
                    provider=tracker["provider"],
                    total_episodes=len(new_episodes),
                    created_by=tracker["user_id"],
                )
                self.db.update_tracker_last_episode(tracker["id"], season, updated_e)
        except Exception as e:
            debug(f"Fatal MegaKino tracker error: {str(e)}", is_error=True)

    def cancel_download(self, queue_id: int) -> bool:
        cancelled = False
        is_queued = False
        with self._queue_lock:
            if queue_id in self._active_downloads:
                job = self._active_downloads[queue_id]
                if job["status"] in ["queued", "downloading"]:
                    self._cancelled_jobs.add(queue_id)
                    cancelled = True
                    is_queued = job["status"] == "queued"

        # Update the status outside of the lock to avoid a self-deadlock
        if is_queued:
            self._update_download_status(queue_id, "failed", error_message="Cancelled by user")

        return cancelled

    def skip_current_candidate(self, queue_id: int) -> bool:
        with self._queue_lock:
            if queue_id in self._active_downloads and self._active_downloads[queue_id]["status"] == "downloading":
                self._skip_flags.add(queue_id); return True
            return False

    def delete_download(self, queue_id: int) -> bool:
        with self._queue_lock:
            for i, d in enumerate(self._completed_downloads):
                if d["id"] == queue_id: self._completed_downloads.pop(i); return True
            if queue_id in self._active_downloads and self._active_downloads[queue_id]["status"] != "downloading":
                del self._active_downloads[queue_id]; return True
            return False

    def retry_download(self, queue_id: int) -> Optional[int]:
        """Re-queue all failed episodes of a finished download job."""
        with self._queue_lock:
            job = next((d for d in self._completed_downloads if d["id"] == queue_id), None)
            if not job:
                return None

            failed_urls = [
                ep["url"] for ep in job.get("episodes", [])
                if ep.get("status") == "failed"
            ]
            if not failed_urls:
                return None

            anime_title = job.get("anime_title", "Unknown Anime")
            language = job.get("language", "German Dub")
            provider = job.get("provider", "VOE")
            episodes_config = job.get("episodes_config")
            created_by = job.get("created_by")

        logging.info(f"Retrying {len(failed_urls)} failed episode(s) of job {queue_id}")
        return self.add_download(
            anime_title=anime_title,
            episode_urls=failed_urls,
            language=language,
            provider=provider,
            total_episodes=len(failed_urls),
            created_by=created_by,
            episodes_config=episodes_config,
        )

    def add_download(self, anime_title: str, episode_urls: list, language: str, provider: str, total_episodes: int, created_by: int = None, episodes_config: dict = None) -> int:
        is_movie = any(
            str(url).startswith("megakino:movie:") or "/filme/" in str(url)
            for url in episode_urls
        )
        episodes = []
        for url in episode_urls:
            url_str = str(url)
            ep_name = url_str.split("/")[-1]
            if "staffel-" in url_str and "episode-" in url_str:
                try:
                    parts = url_str.split("/")
                    s_num = next(p.split("-")[1] for p in parts if "staffel-" in p)
                    e_num = next(p.split("-")[1] for p in parts if "episode-" in p)
                    ep_name = f"S{s_num} E{e_num}"
                except: pass
            elif url_str.startswith("megakino:"):
                if url_str.startswith("megakino:movie:"):
                    ep_name = "Movie"
                else:
                    ep_part = url_str.split("::ep")[-1] if "::ep" in url_str else ""
                    ep_name = f"Episode {ep_part}" if ep_part.isdigit() else "Episode"
            episodes.append({"url": url, "name": ep_name, "status": "queued", "progress": 0.0, "speed": "", "eta": ""})
        with self._queue_lock:
            queue_id = self._next_id; self._next_id += 1
            job = {"id": queue_id, "anime_title": anime_title, "episode_urls": list(episode_urls), "episodes": episodes, "language": language, "provider": provider, "is_movie": is_movie, "episodes_config": episodes_config, "total_episodes": total_episodes, "completed_episodes": 0, "status": "queued", "current_episode": "", "progress_percentage": 0.0, "current_episode_progress": 0.0, "error_message": "", "created_by": created_by, "created_at": datetime.now(), "started_at": None, "completed_at": None}
            self._active_downloads[queue_id] = job
        if not self.is_processing: self.start_queue_processor()
        return queue_id

    def get_queue_status(self):
        with self._queue_lock:
            active = []
            for d in self._active_downloads.values():
                if d["status"] in ["queued", "downloading"]:
                    active.append({"id": d["id"], "anime_title": d["anime_title"], "total_episodes": d["total_episodes"], "completed_episodes": d["completed_episodes"], "status": d["status"], "is_movie": d.get("is_movie", False), "current_episode": d["current_episode"], "progress_percentage": float(round(d["progress_percentage"], 2)), "current_episode_progress": float(round(d["current_episode_progress"], 2)), "error_message": d["error_message"], "created_at": d["created_at"].isoformat() if d["created_at"] else None})
            completed = []
            for d in sorted(self._completed_downloads, key=lambda x: x.get("completed_at", datetime.min), reverse=True)[:5]:
                completed.append({"id": d["id"], "anime_title": d["anime_title"], "total_episodes": d["total_episodes"], "completed_episodes": d["completed_episodes"], "status": d["status"], "is_movie": d.get("is_movie", False), "current_episode": d["current_episode"], "progress_percentage": d["progress_percentage"], "current_episode_progress": d.get("current_episode_progress", 100.0), "error_message": d["error_message"], "completed_at": d["completed_at"].isoformat() if d["completed_at"] else None})
            return {"active": active, "completed": completed}

    def _process_queue(self):
        while self.is_processing and not self._stop_event.is_set():
            try:
                job = self._get_next_queued_download()
                if job:
                    self.current_download_id = job["id"]
                    try: self._process_download_job(job)
                    except KeyboardInterrupt: self._update_download_status(job["id"], "failed", error_message="Interrupted")
                    self.current_download_id = None
                else: time.sleep(2)
            except Exception as e: logging.error(f"Queue error: {e}"); time.sleep(5)

    def _process_download_job(self, job):
        queue_id = job["id"]
        try:
            self._update_download_status(queue_id, "downloading", current_episode="Starting...")
            from ..entry import _group_episodes_by_series
            from ..models import Anime
            from pathlib import Path
            from ..action.common import sanitize_filename
            from .. import config
            import os

            megakino_urls = [
                url for url in job["episode_urls"]
                if str(url).startswith("megakino:")
            ]
            regular_urls = [
                url for url in job["episode_urls"]
                if not str(url).startswith("megakino:")
            ]

            anime_list = _group_episodes_by_series(regular_urls) if regular_urls else []
            if not anime_list and not megakino_urls:
                self._update_download_status(queue_id, "failed", error_message="URL processing failed")
                return
            
            for a in anime_list:
                a.language, a.provider, a.action = job["language"], job["provider"], "Download"
            
            actual_total = sum(len(a.episode_list) for a in anime_list) + len(megakino_urls)
            if actual_total != job["total_episodes"]: self._update_download_status(queue_id, "downloading", total_episodes=actual_total)

            successful_downloads, failed_downloads = 0, 0
            from ..parser import arguments
            
            # Base download directories
            series_download_dir = str(getattr(config, "DEFAULT_SERIES_PATH", os.path.expanduser("~/Downloads")))
            movie_download_dir = str(getattr(config, "DEFAULT_MOVIE_PATH", os.path.expanduser("~/Downloads")))

            if self.db:
                # Priority 1: Specific settings in DB
                custom_series_path = self.db.get_setting("series_download_path")
                custom_movie_path = self.db.get_setting("movie_download_path")
                
                # Priority 2: General settings in DB (fallback for migration)
                custom_general_path = self.db.get_setting("download_path")
                
                if custom_series_path: series_download_dir = custom_series_path
                elif custom_general_path: series_download_dir = custom_general_path
                
                if custom_movie_path: movie_download_dir = custom_movie_path
                elif custom_general_path: movie_download_dir = custom_general_path

            # Determine final download directory for this job
            download_dir = movie_download_dir if job.get("is_movie", False) else series_download_dir

            for anime in anime_list:
                for episode in anime.episode_list:
                    if self._stop_event.is_set() or queue_id in self._cancelled_jobs: break
                    original_link = episode.link

                    is_cancelled = False
                    with self._queue_lock:
                        if queue_id in self._active_downloads:
                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                if ep_item["url"] == original_link and ep_item["status"] == "cancelled": is_cancelled = True; break
                    if is_cancelled: continue

                    episode_info = f"{anime.title} - Episode {episode.episode} (Season {episode.season})"

                    # Per-episode configuration (language/provider chosen in the UI)
                    ep_config = (job.get("episodes_config") or {}).get(original_link) or {}
                    selected_language = ep_config.get("language") or job["language"]
                    selected_provider = ep_config.get("provider") or job["provider"]

                    # Provider fallback: selected provider first, then every other
                    # provider that offers this episode (VOE challenge etc.)
                    candidate_providers = [selected_provider]
                    try:
                        episode.auto_fill_details()
                        for provider_name in episode.provider.keys():
                            if provider_name and provider_name not in candidate_providers:
                                candidate_providers.append(provider_name)
                    except Exception as provider_err:
                        logging.debug(f"Could not determine providers for {episode_info}: {provider_err}")

                    episode_success = False
                    episode_cancelled = False

                    for cand_idx, provider_name in enumerate(candidate_providers):
                        if self._stop_event.is_set() or queue_id in self._cancelled_jobs: break
                        self._update_download_status(queue_id, "downloading", current_episode=f"Downloading {episode_info} via {provider_name}", current_episode_progress=0.0)

                        # Reset provider-specific link state for every attempt
                        episode.link = original_link
                        episode._selected_language = selected_language
                        episode._selected_provider = provider_name
                        episode.embeded_link = None
                        episode.redirect_link = None
                        episode.direct_link = None

                        with self._queue_lock:
                            if queue_id in self._active_downloads:
                                for ep_item in self._active_downloads[queue_id]["episodes"]:
                                    if ep_item["url"] == original_link: ep_item["status"] = "downloading"

                        try:
                            temp_anime = Anime(title=anime.title, slug=anime.slug, site=anime.site, language=selected_language, provider=provider_name, action=anime.action, episode_list=[episode])

                            def web_progress_callback(d, _provider=provider_name):
                                if self._stop_event.is_set() or queue_id in self._cancelled_jobs: raise KeyboardInterrupt("Stopped")
                                with self._queue_lock:
                                    if (queue_id, original_link) in self._cancelled_episodes: self._cancelled_episodes.discard((queue_id, original_link)); raise KeyboardInterrupt("EpCancelled")
                                    if queue_id in self._skip_flags: self._skip_flags.discard(queue_id); raise KeyboardInterrupt("Skip")

                                if d["status"] == "downloading":
                                    p = 0.0
                                    if d.get("_percent_str"):
                                        try: p = float(d["_percent_str"].replace("%", ""))
                                        except: pass
                                    if p == 0.0:
                                        db, tb = d.get("downloaded_bytes", 0), d.get("total_bytes") or d.get("total_bytes_estimate")
                                        if tb: p = (db / tb) * 100
                                    p = min(100.0, max(0.0, p))
                                    s, e = re.sub(r"\x1b\[[0-9;]*m", "", str(d.get("_speed_str", "N/A"))).strip(), re.sub(r"\x1b\[[0-9;]*m", "", str(d.get("_eta_str", "N/A"))).strip()
                                    msg = f"Downloading {episode_info} via {_provider} - {p:.1f}% | Speed: {s} | ETA: {e}"
                                    
                                    with self._queue_lock:
                                        if queue_id in self._active_downloads:
                                            self._active_downloads[queue_id]["current_episode"], self._active_downloads[queue_id]["current_episode_progress"] = msg, float(p)
                                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                                if ep_item["url"] == original_link:
                                                    ep_item["status"], ep_item["progress"], ep_item["speed"], ep_item["eta"] = "downloading", p, s if s != "N/A" else "", e if e != "N/A" else ""
                                    self.update_episode_progress(queue_id, p, msg)

                            # Use consistent output directory for yt-dlp
                            from ..parser import arguments
                            arguments.output_dir = download_dir

                            from ..action.download import download
                            success = download(temp_anime, web_progress_callback)

                            if success:
                                episode_success = True
                                successful_downloads += 1
                                with self._queue_lock:
                                    if queue_id in self._active_downloads:
                                        for ep_item in self._active_downloads[queue_id]["episodes"]:
                                            if ep_item["url"] == original_link: ep_item["status"], ep_item["progress"] = "completed", 100.0
                                self._update_download_status(queue_id, "downloading", completed_episodes=successful_downloads, current_episode=f"Completed {episode_info}", current_episode_progress=100.0)
                                break
                            else:
                                logging.warning(f"Provider '{provider_name}' failed for {episode_info}, trying next provider")
                        except KeyboardInterrupt as ki:
                            if str(ki) == "EpCancelled":
                                episode_cancelled = True
                                with self._queue_lock:
                                    if queue_id in self._active_downloads:
                                        for ep_item in self._active_downloads[queue_id]["episodes"]:
                                            if ep_item["url"] == original_link: ep_item["status"] = "cancelled"
                                break
                            elif str(ki) == "Skip":
                                logging.info(f"Skip requested, trying next provider for {episode_info}")
                                continue
                            else:
                                raise ki
                        except Exception as download_err:
                            logging.warning(f"Provider '{provider_name}' error for {episode_info}: {download_err}")

                    if episode_cancelled:
                        continue

                    if not episode_success and not (self._stop_event.is_set() or queue_id in self._cancelled_jobs):
                        failed_downloads += 1
                        with self._queue_lock:
                            if queue_id in self._active_downloads:
                                for ep_item in self._active_downloads[queue_id]["episodes"]:
                                    if ep_item["url"] == original_link and ep_item["status"] != "cancelled":
                                        ep_item["status"] = "failed"
                        # Give rate-limited providers (VOE/DDoS-Guard) time to recover
                        time.sleep(FAILED_EPISODE_BACKOFF)

            # MegaKino items (movies + series episodes) are resolved separately
            for mega_url in megakino_urls:
                if self._stop_event.is_set() or queue_id in self._cancelled_jobs:
                    break

                with self._queue_lock:
                    if queue_id in self._active_downloads:
                        job_ep = next(
                            (e for e in self._active_downloads[queue_id]["episodes"] if e["url"] == mega_url),
                            None,
                        )
                    else:
                        job_ep = None
                if job_ep is None:
                    continue

                try:
                    result = self._process_megakino_download(
                        queue_id, mega_url, job, series_download_dir, movie_download_dir
                    )
                    if result is None:
                        # Episode was cancelled by the user - not a failure
                        continue
                    if result:
                        successful_downloads += 1
                    else:
                        failed_downloads += 1
                        self._mark_megakino_failed(queue_id, mega_url)
                        time.sleep(FAILED_EPISODE_BACKOFF)
                except KeyboardInterrupt:
                    raise
                except Exception as mega_err:
                    logging.error(f"[MegaKino] critical error: {mega_err}")
                    failed_downloads += 1
                    self._mark_megakino_failed(queue_id, mega_url)

            if queue_id in self._cancelled_jobs:
                self._update_download_status(queue_id, "failed", error_message="Cancelled by user")
                with self._queue_lock: self._cancelled_jobs.discard(queue_id)
                return
            total_att = successful_downloads + failed_downloads
            if successful_downloads == 0 and failed_downloads > 0: status, msg = "failed", f"Failed: 0/{failed_downloads} done."
            elif failed_downloads > 0: status, msg = "completed", f"Partial: {successful_downloads}/{total_att} done."
            else: status, msg = "completed", f"Done: {successful_downloads} eps."
            self._update_download_status(queue_id, status, completed_episodes=successful_downloads, current_episode=msg, error_message=msg if status=="failed" else None)
        except Exception as e: self._update_download_status(queue_id, "failed", error_message=f"Error: {e}")

    def _get_next_queued_download(self):
        with self._queue_lock:
            for d in self._active_downloads.values():
                if d["status"] == "queued": return d
            return None

    def update_episode_progress(self, queue_id: int, episode_progress: float, current_episode_desc: str = None):
        with self._queue_lock:
            if queue_id not in self._active_downloads: return False
            d = self._active_downloads[queue_id]
            d["current_episode_progress"] = float(min(100.0, max(0.0, float(episode_progress))))
            if current_episode_desc: d["current_episode"] = current_episode_desc
            t, c = int(d.get("total_episodes", 1)), int(d.get("completed_episodes", 0))
            if t > 0: d["progress_percentage"] = float(min(100.0, max(0.0, ((c + (d["current_episode_progress"]/100.0))/t)*100.0)))
            return True

    def stop_episode(self, queue_id: int, ep_url: str) -> bool:
        cancel_job = False
        with self._queue_lock:
            if queue_id not in self._active_downloads: return False
            job = self._active_downloads[queue_id]
            ep = next((e for e in job["episodes"] if e["url"] == ep_url), None)
            if not ep: return False
            if ep["status"] == "downloading": ep["status"] = "cancelled"; self._cancelled_episodes.add((queue_id, ep_url)); return True
            if ep_url in job["episode_urls"]: job["episode_urls"].remove(ep_url)
            job["episodes"] = [e for e in job["episodes"] if e["url"] != ep_url]; job["total_episodes"] = len(job["episodes"])
            if not job["episodes"]: cancel_job = True

        # Cancel outside of the lock to avoid a self-deadlock
        if cancel_job:
            self.cancel_download(queue_id)
        return True

    def reorder_episodes(self, queue_id: int, new_order_urls: list) -> bool:
        with self._queue_lock:
            if queue_id not in self._active_downloads: return False
            job = self._active_downloads[queue_id]
            fixed = [e["url"] for e in job["episodes"] if e["status"] != "queued"]
            if new_order_urls[:len(fixed)] != fixed or set(job["episode_urls"]) != set(new_order_urls): return False
            job["episode_urls"] = new_order_urls
            u_to_e = {e["url"]: e for e in job["episodes"]}; job["episodes"] = [u_to_e[u] for u in new_order_urls]
            return True

    def get_job_episodes(self, queue_id: int):
        with self._queue_lock:
            if queue_id in self._active_downloads: return self._active_downloads[queue_id].get("episodes", [])
            for j in self._completed_downloads:
                if j["id"] == queue_id: return j.get("episodes", [])
            return None

    def _process_megakino_download(self, queue_id, original_link, job, series_download_dir, movie_download_dir):
        """Resolve a MegaKino item and download it via VOE/GXPlayer."""
        try:
            # Parse tokens: megakino:movie:<page url> | megakino:series:<page url>::ep<N>
            token = original_link.split(":", 2)[2]
            episode_num = None
            if "::ep" in token:
                page_url, ep_part = token.split("::ep", 1)
                try:
                    episode_num = int(ep_part)
                except ValueError:
                    episode_num = None
            else:
                page_url = token

            is_movie = original_link.startswith("megakino:movie:")
            download_dir = movie_download_dir if is_movie else series_download_dir

            self._update_download_status(
                queue_id, "downloading",
                current_episode="Resolving MegaKino...",
                current_episode_progress=0.0,
            )

            client = MegakinoClient()
            details = client.get_details(page_url)
            if not details:
                logging.error(f"[MegaKino] No details found for {page_url}")
                self._mark_megakino_failed(queue_id, original_link)
                return False

            title = details.get("title") or job["anime_title"]

            if is_movie:
                streams = details.get("streams", [])
                season = 0
                episode = 1
            else:
                season = int(details.get("season") or 1)
                episode = episode_num or 1
                streams = []
                for ep in details.get("episodes", []):
                    if episode_num is None or int(ep.get("episode", 0)) == episode_num:
                        streams = ep.get("streams", [])
                        break

            if not streams:
                logging.error(f"[MegaKino] No streams found for {original_link}")
                self._mark_megakino_failed(queue_id, original_link)
                return False

            # Order providers: explicit user selection first, then site priority
            ep_config = (job.get("episodes_config") or {}).get(original_link) or {}
            selected_provider = ep_config.get("provider") or job.get("provider")
            ordered_streams = self._order_streams(streams, selected_provider)
            item_label = (
                f"{title} (Movie)" if is_movie else f"{title} - S{season:02}E{episode:02}"
            )

            # Show the real title in the queue instead of the page URL
            with self._queue_lock:
                if queue_id in self._active_downloads:
                    for ep_item in self._active_downloads[queue_id]["episodes"]:
                        if ep_item["url"] == original_link:
                            ep_item["name"] = item_label

            for stream in ordered_streams:
                if self._stop_event.is_set() or queue_id in self._cancelled_jobs:
                    break

                provider = stream["provider"]
                stream_url = stream["url"]

                def web_progress_callback(d, _provider=provider, _label=item_label):
                    if self._stop_event.is_set() or queue_id in self._cancelled_jobs:
                        raise KeyboardInterrupt("Stopped")

                    with self._queue_lock:
                        if (queue_id, original_link) in self._cancelled_episodes:
                            self._cancelled_episodes.discard((queue_id, original_link))
                            raise KeyboardInterrupt("EpCancelled")
                        if queue_id in self._skip_flags:
                            self._skip_flags.discard(queue_id)
                            logging.info(f"[MegaKino] Skip requested for job {queue_id}")
                            raise KeyboardInterrupt("Skip")

                    if d["status"] == "downloading":
                        p = 0.0
                        if d.get("_percent_str"):
                            try: p = float(d["_percent_str"].replace("%", ""))
                            except: pass
                        p = min(100.0, max(0.0, p))
                        s_speed = re.sub(r"\x1b\[[0-9;]*m", "", str(d.get("_speed_str", "N/A"))).strip()
                        e_eta = re.sub(r"\x1b\[[0-9;]*m", "", str(d.get("_eta_str", "N/A"))).strip()
                        msg = f"Downloading {_label} via {_provider} - {p:.1f}% | Speed: {s_speed} | ETA: {e_eta}"

                        with self._queue_lock:
                            if queue_id in self._active_downloads:
                                self._active_downloads[queue_id]["current_episode"] = msg
                                self._active_downloads[queue_id]["current_episode_progress"] = float(p)
                                for ep_item in self._active_downloads[queue_id]["episodes"]:
                                    if ep_item["url"] == original_link:
                                        ep_item["status"], ep_item["progress"], ep_item["speed"], ep_item["eta"] = "downloading", p, s_speed if s_speed != "N/A" else "", e_eta if e_eta != "N/A" else ""
                        self.update_episode_progress(queue_id, p, msg)

                self._update_download_status(
                    queue_id, "downloading",
                    current_episode=f"Downloading {item_label} via {provider}",
                    current_episode_progress=0.0,
                )

                try:
                    success = download_stream(
                        stream_url,
                        title,
                        "de",
                        provider,
                        season=season,
                        episode=episode,
                        web_progress_callback=web_progress_callback,
                        output_dir=download_dir,
                    )
                except KeyboardInterrupt as ki:
                    if str(ki) == "Skip":
                        logging.info("[MegaKino] Skipping current stream as requested")
                        continue
                    if str(ki) == "EpCancelled":
                        with self._queue_lock:
                            if queue_id in self._active_downloads:
                                for ep_item in self._active_downloads[queue_id]["episodes"]:
                                    if ep_item["url"] == original_link:
                                        ep_item["status"] = "cancelled"
                        return None
                    raise ki

                if success:
                    completed = job.get("completed_episodes", 0) + 1
                    with self._queue_lock:
                        if queue_id in self._active_downloads:
                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                if ep_item["url"] == original_link:
                                    ep_item["status"], ep_item["progress"] = "completed", 100.0
                    self._update_download_status(
                        queue_id, "downloading",
                        completed_episodes=completed,
                        current_episode=f"Completed {item_label}",
                        current_episode_progress=100.0,
                    )
                    return True

            self._mark_megakino_failed(queue_id, original_link)
            return False

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logging.error(f"[MegaKino] processing error: {e}")
            return False

    @staticmethod
    def _order_streams(streams, selected_provider):
        """Put the explicitly selected provider first, keep site priority otherwise."""
        ordered = list(streams)
        if selected_provider:
            ordered.sort(
                key=lambda s: 0 if s.get("provider") == selected_provider else 1
            )
        return ordered

    def _mark_megakino_failed(self, queue_id, original_link):
        with self._queue_lock:
            if queue_id in self._active_downloads:
                for ep_item in self._active_downloads[queue_id]["episodes"]:
                    if ep_item["url"] == original_link and ep_item["status"] != "cancelled":
                        ep_item["status"] = "failed"

    def _update_download_status(self, queue_id: int, status: str, completed_episodes: int = None, current_episode: str = None, error_message: str = None, total_episodes: int = None, current_episode_progress: float = None):
        with self._queue_lock:
            if queue_id not in self._active_downloads: return False
            d = self._active_downloads[queue_id]; d["status"] = status
            if total_episodes is not None: d["total_episodes"] = total_episodes
            if completed_episodes is not None: d["completed_episodes"] = completed_episodes
            if current_episode_progress is not None: d["current_episode_progress"] = min(100.0, max(0.0, float(current_episode_progress)))
            t, c, cp = d["total_episodes"], d["completed_episodes"], d.get("current_episode_progress", 0.0)
            if t > 0: d["progress_percentage"] = float(min(100.0, ((int(c) + (float(cp)/100.0))/int(t))*100.0 if status == "downloading" else (int(c)/int(t))*100.0))
            if current_episode is not None: d["current_episode"] = current_episode
            if error_message is not None: d["error_message"] = error_message
            if status == "downloading" and d["started_at"] is None: d["started_at"] = datetime.now()
            elif status in ["completed", "failed"]:
                d["completed_at"] = datetime.now()
                if status == "completed": d["current_episode_progress"], d["progress_percentage"] = 100.0, 100.0
                self._completed_downloads.append(d.copy())
                if len(self._completed_downloads) > self._max_completed_history: self._completed_downloads = self._completed_downloads[-self._max_completed_history:]
                del self._active_downloads[queue_id]
            return True


_download_manager = None

def get_download_manager(database: Optional[UserDatabase] = None) -> DownloadQueueManager:
    global _download_manager
    if _download_manager is None: _download_manager = DownloadQueueManager(database)
    return _download_manager
