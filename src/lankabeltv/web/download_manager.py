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


class DownloadQueueManager:
    """Manages the global download queue processing with in-memory storage"""

    def __init__(self, database: Optional[UserDatabase] = None):
        self.db = database  # Only used for user auth, not download storage
        self.is_processing = False
        self.max_concurrent_series = 1
        self.max_concurrent_episodes = 1
        if self.db:
            try:
                max_s = self.db.get_setting("max_concurrent_series")
                if max_s:
                    self.max_concurrent_series = max(1, int(max_s))
                else:
                    # Migration: use old setting if exists
                    old_max = self.db.get_setting("max_concurrent_downloads")
                    if old_max:
                        self.max_concurrent_series = max(1, int(old_max))
                
                max_e = self.db.get_setting("max_concurrent_episodes")
                if max_e:
                    self.max_concurrent_episodes = max(1, int(max_e))
            except:
                pass
        
        self.active_worker_threads = []
        self._worker_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._cancelled_jobs = set()
        # Condition variable used by episode workers to wake up the
        # job scheduler as soon as a slot frees up, instead of relying
        # on time-based polling.
        self._job_scheduler_cv = threading.Condition(threading.Lock())
        # Dedicated event for cross-thread wakeups. Unlike a Condition
        # variable, threading.Event.set() can be called from any thread
        # WITHOUT acquiring a lock first, so notifying the scheduler
        # from the Flask request thread (in add_download) can never
        # block waiting for the scheduler to release its cv.wait lock.
        # The scheduler does an Event.wait() once at the top of each
        # loop iteration; if it was set, we just clear it and continue.
        self._scheduler_wakeup = threading.Event()

        # In-memory download queue storage
        self._next_id = 1
        self._queue_lock = threading.Lock()
        self._active_downloads = {}  # id -> download_job dict
        self._cancelled_episodes = set() # set of (queue_id, ep_url)
        self._completed_downloads = []  # list of completed download jobs (keep last N)
        self._max_completed_history = 10
        self._skip_flags = set()
        self._tracker_scan_status = {} # tracker_id -> bool (is_scanning)
        self._tracker_debug_messages = {} # tracker_id -> list of strings

    def set_download_limits(self, series_count: int, episode_count: int):
        """Update the maximum number of concurrent series and episodes"""
        with self._worker_lock:
            self.max_concurrent_series = max(1, int(series_count))
            self.max_concurrent_episodes = max(1, int(episode_count))
            if self.db:
                self.db.set_setting("max_concurrent_series", str(self.max_concurrent_series))
                self.db.set_setting("max_concurrent_episodes", str(self.max_concurrent_episodes))
            logging.info(f"Limits set: max_concurrent_series={self.max_concurrent_series}, max_concurrent_episodes={self.max_concurrent_episodes}")

    def start_queue_processor(self):
        """Start the background queue processor"""
        if not self.is_processing:
            self.is_processing = True
            self._stop_event.clear()
            # Start the main scheduler thread
            self.scheduler_thread = threading.Thread(
                target=self._queue_scheduler, daemon=True
            )
            self.scheduler_thread.start()
            logging.info("Download queue processor started")

    def stop_queue_processor(self):
        """Stop the background queue processor"""
        if self.is_processing:
            self.is_processing = False
            self._stop_event.set()
            if hasattr(self, "scheduler_thread"):
                self.scheduler_thread.join(timeout=5)
            
            # Wait for all workers to finish
            with self._worker_lock:
                for thread in self.active_worker_threads:
                    thread.join(timeout=2)
                self.active_worker_threads = []
                
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

    def cancel_download(self, queue_id: int) -> bool:
        with self._queue_lock:
            if queue_id in self._active_downloads:
                job = self._active_downloads[queue_id]
                logging.info(
                    "[DEBUG] cancel_download called for job %s (current status: %s)",
                    queue_id, job["status"],
                )
                if job["status"] in ["queued", "downloading"]:
                    self._cancelled_jobs.add(queue_id)
                    # CRITICAL: also update job status immediately so the
                    # frontend stops showing "Starting..." and the scheduler
                    # sees a coherent state. The job worker thread will
                    # perform the final cleanup (move to _completed_downloads)
                    # when it next wakes up and notices _cancelled_jobs.
                    if job["status"] == "queued":
                        self._update_download_status(
                            queue_id, "failed", error_message="Cancelled by user"
                        )
                    else:
                        # status == "downloading" - flip the visible state but
                        # do NOT delete the job from _active_downloads yet, so
                        # the worker thread can finalize the episode statuses.
                        job["status"] = "cancelled"
                        job["current_episode"] = "Cancelled by user"
                        job["error_message"] = "Cancelled by user"
                    # Wake up both the top-level scheduler and any worker
                    # currently blocked in cv.wait() so cancellation
                    # propagates immediately instead of after the 2s timeout.
                    # Use a dedicated Event to avoid blocking on the
                    # Condition's internal lock.
                    try:
                        self._scheduler_wakeup.set()
                    except Exception:
                        pass
                    logging.info(
                        "[DEBUG] Job %s marked as cancelled, scheduler notified",
                        queue_id,
                    )
                    return True
            logging.warning(
                "[DEBUG] cancel_download: job %s not found or not cancellable",
                queue_id,
            )
            return False

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

    def add_download(self, anime_title: str, episode_urls: list, language: str, provider: str, total_episodes: int = 0, created_by: int = None, episodes_config: dict = None) -> int:
        """Register a new download job and return its queue_id.

        This is intentionally lightweight: the heavy lifting (resolving the
        episode URLs into Anime/Episode objects via HTTP requests) is deferred
        to the worker thread via ``_resolve_job_anime_objects()``. The Flask
        request thread therefore returns within milliseconds instead of
        blocking for 5-30s on HTTP requests to aniworld.to / s.to.
        """
        is_movie = any("/filme/" in url for url in episode_urls)
        episodes = []
        for url in episode_urls:
            ep_name = url.split("/")[-1]
            if "staffel-" in url and "episode-" in url:
                try:
                    parts = url.split("/")
                    s_num = next(p.split("-")[1] for p in parts if "staffel-" in p)
                    e_num = next(p.split("-")[1] for p in parts if "episode-" in p)
                    ep_name = f"S{s_num} E{e_num}"
                except Exception:
                    pass
            episodes.append({"url": url, "name": ep_name, "status": "queued", "progress": 0.0, "speed": "", "eta": ""})

        with self._queue_lock:
            queue_id = self._next_id
            self._next_id += 1
            # If total_episodes wasn't provided (or is 0), use the number of
            # episode URLs as a fallback so the frontend has something to show.
            if not total_episodes:
                total_episodes = len(episode_urls)
            job = {
                "id": queue_id,
                "anime_title": anime_title,
                "episode_urls": episode_urls,
                "episodes": episodes,
                "language": language,
                "provider": provider,
                "is_movie": is_movie,
                "episodes_config": episodes_config,
                "total_episodes": total_episodes,
                "completed_episodes": 0,
                "status": "queued",
                "current_episode": "",
                "progress_percentage": 0.0,
                "current_episode_progress": 0.0,
                "error_message": "",
                "created_by": created_by,
                "created_at": datetime.now(),
                "started_at": None,
                "completed_at": None,
                "_ep_heartbeats": {},
                "_last_activity": time.time(),
                # Flag set by the worker once the anime/episode objects have
                # been resolved. Until then, _process_download_job will call
                # _resolve_job_anime_objects() to do the heavy work.
                "_anime_objects": None,
                "_needs_resolution": True,
            }
            self._active_downloads[queue_id] = job
            logging.info(
                "[DEBUG] add_download: queued job %s (anime=%s, eps=%d, lang=%s, prov=%s)",
                queue_id, anime_title, total_episodes, language, provider,
            )

        # Fix 3: Auto-restart scheduler if its thread died for any reason.
        if hasattr(self, "scheduler_thread") and self.scheduler_thread is not None:
            if not self.scheduler_thread.is_alive():
                logging.warning(
                    "[DEBUG] add_download: scheduler thread is dead, restarting it "
                    "(was is_processing=%s)", self.is_processing,
                )
                self.is_processing = False

        if not self.is_processing:
            self.start_queue_processor()
        # Wake up the scheduler so it picks up the new job immediately.
        # Use a dedicated Event so we never block on the Condition lock.
        try:
            self._scheduler_wakeup.set()
        except Exception:
            pass
        return queue_id

    def _resolve_job_anime_objects(self, queue_id):
        """Resolve episode URLs into Anime/Episode objects.

        Runs in the job worker thread (not the Flask request thread) so that
        the HTTP requests it makes do not block the web UI. Returns a list of
        ``Anime`` objects (possibly empty on failure) and updates the job's
        ``_anime_objects`` field for later reuse.
        """
        logging.info("[DEBUG] _resolve_job_anime_objects[%s]: starting", queue_id)
        try:
            from ..entry import _group_episodes_by_series

            with self._queue_lock:
                job = self._active_downloads.get(queue_id)
                if not job:
                    logging.warning(
                        "[DEBUG] _resolve_job_anime_objects[%s]: job no longer in "
                        "active downloads, aborting", queue_id,
                    )
                    return []
                episode_urls = job.get("episode_urls", [])

            anime_list = _group_episodes_by_series(episode_urls)
            logging.info(
                "[DEBUG] _resolve_job_anime_objects[%s]: resolved %d URL(s) -> %d anime object(s)",
                queue_id, len(episode_urls), len(anime_list) if anime_list else 0,
            )

            with self._queue_lock:
                job = self._active_downloads.get(queue_id)
                if job is not None:
                    job["_anime_objects"] = anime_list
                    if anime_list:
                        # Update total_episodes to the actual count
                        actual_total = sum(len(a.episode_list) for a in anime_list)
                        if actual_total != job.get("total_episodes", 0):
                            logging.info(
                                "[DEBUG] _resolve_job_anime_objects[%s]: total_episodes "
                                "%s -> %s", queue_id, job.get("total_episodes"), actual_total,
                            )
                            job["total_episodes"] = actual_total
                    job["_needs_resolution"] = False
                    job["_last_activity"] = time.time()

            return anime_list
        except Exception as e:
            logging.error(
                "[DEBUG] _resolve_job_anime_objects[%s]: failed: %s",
                queue_id, e, exc_info=True,
            )
            with self._queue_lock:
                job = self._active_downloads.get(queue_id)
                if job is not None:
                    job["_needs_resolution"] = False
                    job["_last_activity"] = time.time()
            return []

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

    def _queue_scheduler(self):
        """Main scheduler that manages worker threads.

        Uses a condition variable so it can wake up immediately when a new
        download is queued or when a worker slot frees up, instead of relying
        on fixed-interval polling.
        """
        # The Condition variable is no longer used here; we use the
        # _scheduler_wakeup Event for inter-thread wakeups. The Condition
        # is still kept as a backwards-compat attribute.
        _ = self._job_scheduler_cv
        # Fix F: Stale-job detection. If a job has been in "downloading" state
        # without any activity for this many seconds, force it to "failed" so
        # the user is not stuck on a non-responsive queue entry.
        stale_job_threshold_seconds = 1800  # 30 minutes with no heartbeat
        while self.is_processing and not self._stop_event.is_set():
            try:
                # Clean up finished threads
                with self._worker_lock:
                    self.active_worker_threads = [t for t in self.active_worker_threads if t.is_alive()]
                    active_count = len(self.active_worker_threads)

                # Stale-job scan (Fix F): detect jobs that have been "downloading"
                # for too long without a heartbeat update, and force them to
                # "failed" so the scheduler can pick up the next job.
                stale_jobs = []
                with self._queue_lock:
                    now = time.time()
                    for qid, d in list(self._active_downloads.items()):
                        if d["status"] != "downloading":
                            continue
                        last = d.get("_last_activity")
                        if last is None:
                            # No heartbeat ever recorded - use started_at as fallback
                            last_ts = d.get("started_at").timestamp() if d.get("started_at") else now
                        else:
                            last_ts = last
                        if (now - last_ts) > stale_job_threshold_seconds:
                            stale_jobs.append(qid)
                for qid in stale_jobs:
                    logging.error(
                        "[DEBUG] Stale-job detector: job %s has been downloading "
                        "for >%ds without activity - force-failing",
                        qid, stale_job_threshold_seconds,
                    )
                    self._update_download_status(
                        qid, "failed",
                        error_message="Stale job - no activity for too long",
                    )

                if active_count < self.max_concurrent_series:
                    job = self._get_next_queued_download()
                    if job:
                        # Mark job as starting so it's not picked up again immediately
                        # We use 'downloading' but with a special message
                        self._update_download_status(job["id"], "downloading", current_episode="Initializing...")

                        worker = threading.Thread(
                            target=self._worker_wrapper, args=(job,), daemon=True
                        )
                        with self._worker_lock:
                            self.active_worker_threads.append(worker)
                        worker.start()
                        logging.info(f"Started worker for job {job['id']}. Active workers: {len(self.active_worker_threads)}")
                        # Loop immediately to pick up more jobs if capacity allows
                        continue
                    else:
                        # No queued jobs: wait for someone to enqueue one.
                        # We use the dedicated _scheduler_wakeup Event so
                        # this wait can never block add_download() callers
                        # that try to wake us up.
                        self._scheduler_wakeup.wait(timeout=2.0)
                else:
                    # All slots busy: wait for a worker to free up
                    self._scheduler_wakeup.wait(timeout=2.0)
                # Clear the event so the next wait() actually sleeps
                self._scheduler_wakeup.clear()
            except Exception as e:
                logging.error(f"Scheduler error: {e}")
                time.sleep(5)

    def _worker_wrapper(self, job):
        """Wrapper for the download job processing"""
        queue_id = job["id"]
        logging.info("[DEBUG] _worker_wrapper: starting job %s (anime=%s, eps=%d)",
                     queue_id, job.get("anime_title"), job.get("total_episodes"))
        try:
            self._process_download_job(job)
            logging.info("[DEBUG] _worker_wrapper: job %s finished normally", queue_id)
        except KeyboardInterrupt:
            logging.warning("[DEBUG] _worker_wrapper: job %s interrupted by KeyboardInterrupt", queue_id)
            self._update_download_status(queue_id, "failed", error_message="Interrupted")
        except Exception as e:
            logging.error(f"Worker error for job {queue_id}: {e}", exc_info=True)
            self._update_download_status(queue_id, "failed", error_message=f"Worker Error: {e}")

    def _touch_job_heartbeat(self, queue_id):
        """Update the job-level heartbeat. Called from episode workers and
        from the main loop. Used by the stale-job detector (Fix F).

        Note: We previously held ``self._queue_lock`` here, but that
        caused deadlocks when this method was called from the yt-dlp
        progress hook (which can run at very high frequency while the
        GIL is contended by a long-running socket read). Since the
        heartbeat is just a timestamp, the worst case if we lose the
        race is a slightly stale ``_last_activity`` value, which is
        acceptable.
        """
        if queue_id in self._active_downloads:
            try:
                self._active_downloads[queue_id]["_last_activity"] = time.time()
            except RuntimeError:
                # dict changed during iteration - just skip this update
                pass

    def _process_download_job(self, job):
        queue_id = job["id"]
        try:
            logging.info(
                "[DEBUG] _process_download_job[%s]: enter, urls=%d, lang=%s, prov=%s",
                queue_id, len(job.get("episode_urls", [])),
                job.get("language"), job.get("provider"),
            )
            self._update_download_status(queue_id, "downloading", current_episode="Starting...")
            self._touch_job_heartbeat(queue_id)
            from ..models import Anime
            from pathlib import Path
            from ..action.common import sanitize_filename
            from .. import config
            import os

            # Fix 2: Resolve Anime/Episode objects in the WORKER thread,
            # not the Flask request thread. _resolve_job_anime_objects
            # makes HTTP requests that can take 5-30s, which would
            # otherwise block the entire web UI.
            if job.get("_needs_resolution") or job.get("_anime_objects") is None:
                self._update_download_status(
                    queue_id, "downloading", current_episode="Resolving episodes...",
                )
                logging.info(
                    "[DEBUG] _process_download_job[%s]: resolving anime objects from URLs",
                    queue_id,
                )
                anime_list = self._resolve_job_anime_objects(queue_id)
            else:
                anime_list = job.get("_anime_objects") or []
                logging.info(
                    "[DEBUG] _process_download_job[%s]: reusing %d cached anime object(s)",
                    queue_id, len(anime_list),
                )

            if not anime_list:
                logging.error("[DEBUG] _process_download_job[%s]: URL processing returned no anime", queue_id)
                self._update_download_status(queue_id, "failed", error_message="URL processing failed")
                return

            for a in anime_list:
                a.language, a.provider, a.action = job["language"], job["provider"], "Download"

            actual_total = sum(len(a.episode_list) for a in anime_list)
            if actual_total != job.get("total_episodes", actual_total):
                logging.warning(
                    "[DEBUG] _process_download_job[%s]: episode count mismatch (job=%d, actual=%d) - correcting",
                    queue_id, job.get("total_episodes"), actual_total,
                )
                self._update_download_status(queue_id, "downloading", total_episodes=actual_total)

            # Base download directories
            series_download_dir = str(getattr(config, "DEFAULT_SERIES_PATH", os.path.expanduser("~/Downloads")))
            movie_download_dir = str(getattr(config, "DEFAULT_MOVIE_PATH", os.path.expanduser("~/Downloads")))

            if self.db:
                custom_series_path = self.db.get_setting("series_download_path")
                custom_movie_path = self.db.get_setting("movie_download_path")
                custom_general_path = self.db.get_setting("download_path")

                if custom_series_path: series_download_dir = custom_series_path
                elif custom_general_path: series_download_dir = custom_general_path
                if custom_movie_path: movie_download_dir = custom_movie_path
                elif custom_general_path: movie_download_dir = custom_general_path

            download_dir = movie_download_dir if job.get("is_movie", False) else series_download_dir
            logging.info(
                "[DEBUG] _process_download_job[%s]: download_dir=%s, max_concurrent_episodes=%d",
                queue_id, download_dir, self.max_concurrent_episodes,
            )

            # Episode processing with internal parallelism
            active_ep_threads = []
            ep_lock = threading.Lock()
            completed_episodes_count = 0
            failed_episodes_count = 0

            all_episodes_to_download = []
            for anime in anime_list:
                for episode in anime.episode_list:
                    all_episodes_to_download.append((anime, episode))

            ep_iterator = iter(all_episodes_to_download)
            stop_job = False
            # _scheduler_wakeup is the cross-thread wakeup signal that
            # the episode loop and the top-level scheduler both check.

            # Pre-cancel all not-yet-started episodes if the job is already cancelled
            if queue_id in self._cancelled_jobs:
                logging.info("[DEBUG] _process_download_job[%s]: job was already cancelled, "
                             "marking all %d episodes as cancelled",
                             queue_id, len(all_episodes_to_download))
                for anime, episode in all_episodes_to_download:
                    with self._queue_lock:
                        if queue_id in self._active_downloads:
                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                if ep_item["url"] == episode.link and ep_item["status"] == "queued":
                                    ep_item["status"] = "cancelled"
                return

            while not stop_job:
                # Clean up finished threads
                active_ep_threads = [t for t in active_ep_threads if t.is_alive()]

                # Zombie detection: if any thread is alive but its heartbeat
                # is older than the threshold, mark its episode as failed and
                # treat it as completed. This prevents the scheduler from
                # waiting forever on a stuck yt-dlp call.
                if active_ep_threads:
                    zombies = []
                    # Snapshot data without holding the lock - we just want a
                    # best-effort view, so a stale snapshot is fine. This
                    # avoids blocking the queue lock for long.
                    try:
                        for t in active_ep_threads:
                            if not t.is_alive():
                                continue
                            with self._queue_lock:
                                if queue_id not in self._active_downloads:
                                    continue
                                heartbeats = self._active_downloads[queue_id].get("_ep_heartbeats", {})
                                for ep_url, hb in list(heartbeats.items()):
                                    if hb is None:
                                        continue
                                    age = time.time() - hb[0]
                                    if age > 900:  # 15 minutes without progress
                                        zombies.append(ep_url)
                    except RuntimeError:
                        # dict changed during iteration - just retry next loop
                        continue
                    for ep_url in zombies:
                        logging.error(
                            "Job %s: Episode %s is unresponsive (no heartbeat for 15min) - marking as failed",
                            queue_id, ep_url,
                        )
                        with self._queue_lock:
                            if queue_id in self._active_downloads:
                                for ep_item in self._active_downloads[queue_id]["episodes"]:
                                    if ep_item["url"] == ep_url and ep_item["status"] == "downloading":
                                        ep_item["status"] = "failed"
                                        heartbeats = self._active_downloads[queue_id].setdefault("_ep_heartbeats", {})
                                        heartbeats.pop(ep_url, None)
                        self._cancelled_episodes.add((queue_id, ep_url))

                # Re-prune dead threads after zombie handling
                active_ep_threads = [t for t in active_ep_threads if t.is_alive()]

                # Cancellation check (Fix B): also re-check inside the
                # polling loop so we don't wait 2s on cv.wait() when the user
                # has just cancelled the job.
                if self._stop_event.is_set() or queue_id in self._cancelled_jobs:
                    logging.info(
                        "[DEBUG] _process_download_job[%s]: cancellation detected, "
                        "marking %d not-yet-started episodes as cancelled",
                        queue_id, len(active_ep_threads),
                    )
                    # Mark any still-queued episodes as cancelled
                    with self._queue_lock:
                        if queue_id in self._active_downloads:
                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                if ep_item["status"] == "queued":
                                    ep_item["status"] = "cancelled"
                    # Add cancellation flag for any currently downloading episodes
                    with self._queue_lock:
                        if queue_id in self._active_downloads:
                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                if ep_item["status"] == "downloading":
                                    self._cancelled_episodes.add((queue_id, ep_item["url"]))
                    stop_job = True
                    break

                if len(active_ep_threads) < self.max_concurrent_episodes:
                    try:
                        anime, episode = next(ep_iterator)

                        # Re-check cancellation right before starting a new episode
                        if self._stop_event.is_set() or queue_id in self._cancelled_jobs:
                            stop_job = True
                            break

                        original_link = episode.link
                        norm_link = original_link.rstrip("/")

                        is_cancelled = False
                        with self._queue_lock:
                            if queue_id in self._active_downloads:
                                for ep_item in self._active_downloads[queue_id]["episodes"]:
                                    if ep_item["url"].rstrip("/") == norm_link and ep_item["status"] == "cancelled":
                                        is_cancelled = True
                                        logging.info(f"[DEBUG] Job {queue_id}: Skipping cancelled episode {ep_item['name']}")
                                        break
                        if is_cancelled:
                            continue

                        # Start episode download thread
                        t = threading.Thread(
                            target=self._download_single_episode,
                            args=(queue_id, anime, episode, job, download_dir, ep_lock),
                            daemon=True,
                        )
                        active_ep_threads.append(t)
                        t.start()

                        # Yield briefly so we don't spin if episode creation is slow
                        time.sleep(0.05)

                    except StopIteration:
                        if not active_ep_threads:
                            break
                        # No more episodes to start, wait for workers to finish
                        time.sleep(0.5)
                else:
                    # All slots are busy - wait for a worker to signal completion
                    time.sleep(2.0)

            # Wait for remaining episode threads (with timeout to avoid hangs)
            join_deadline = time.time() + 30
            for t in active_ep_threads:
                remaining = max(0.1, join_deadline - time.time())
                t.join(timeout=remaining)
                if t.is_alive():
                    logging.error(
                        "Job %s: Episode thread did not finish in time, leaving it as daemon",
                        queue_id,
                    )

            if queue_id in self._cancelled_jobs:
                logging.info(
                    "[DEBUG] _process_download_job[%s]: finalized cancellation, "
                    "moving to completed history as 'failed'",
                    queue_id,
                )
                self._update_download_status(queue_id, "failed", error_message="Cancelled by user")
                with self._queue_lock: self._cancelled_jobs.discard(queue_id)
                return

            # Final job status update
            with self._queue_lock:
                if queue_id in self._active_downloads:
                    job_data = self._active_downloads[queue_id]
                    successful = sum(1 for e in job_data["episodes"] if e["status"] == "completed")
                    total_att = sum(1 for e in job_data["episodes"] if e["status"] in ["completed", "failed"])

                    if successful == 0 and total_att > 0: status, msg = "failed", f"Failed: 0/{total_att} done."
                    elif total_att < len(job_data["episodes"]): status, msg = "completed", f"Partial: {successful}/{len(job_data['episodes'])} done." # Should not happen if iterator finished
                    else: status, msg = "completed", f"Done: {successful} eps."

                    logging.info(
                        "[DEBUG] _process_download_job[%s]: finalizing -> status=%s, msg=%s",
                        queue_id, status, msg,
                    )
                    self._update_download_status(queue_id, status, completed_episodes=successful, current_episode=msg, error_message=msg if status=="failed" else None)
        except Exception as e:
            logging.error(f"Error in _process_download_job[{queue_id}]: {e}", exc_info=True)
            self._update_download_status(queue_id, "failed", error_message=f"Error: {e}")

    def _download_single_episode(self, queue_id, anime, episode, job, download_dir, ep_lock):
        """Worker function for a single episode download within a job.

        Always reports completion (success/failure/cancel) via the ``finally``
        block, so that the parent job scheduler never gets stuck waiting on a
        dead/zombie thread. Also signals a condition variable so the scheduler
        can wake up immediately instead of polling.
        """
        original_link = episode.link
        episode_info = f"{anime.title} - Episode {episode.episode} (Season {episode.season})"

        # Determine language and provider
        ep_config = (job.get("episodes_config") or {}).get(original_link) or {}
        lang = ep_config.get("language") or job["language"]
        prov = ep_config.get("provider") or job["provider"]

        logging.info(
            "[DEBUG] _download_single_episode[%s/%s]: start lang=%s prov=%s",
            queue_id, original_link, lang, prov,
        )

        # Heartbeat: tracks last time the worker made progress. The job scheduler
        # uses this to detect zombie threads that are alive but not actually
        # doing anything (e.g. yt-dlp stuck on a network call).
        last_heartbeat = [time.time()]
        final_status = {"value": "failed"}

        def touch_heartbeat():
            last_heartbeat[0] = time.time()
            # Also update the job-level heartbeat (Fix F)
            self._touch_job_heartbeat(queue_id)

        with self._queue_lock:
            if queue_id in self._active_downloads:
                for ep_item in self._active_downloads[queue_id]["episodes"]:
                    if ep_item["url"] == original_link:
                        ep_item["status"] = "downloading"
                        ep_item.setdefault("last_heartbeat", time.time())

        # Store the heartbeat reference for the job-level monitor
        with self._queue_lock:
            if queue_id in self._active_downloads:
                self._active_downloads[queue_id].setdefault(
                    "_ep_heartbeats", {}
                )[original_link] = last_heartbeat
                self._touch_job_heartbeat(queue_id)

        try:
            from ..models import Anime as AnimeModel
            # Use local copies for thread safety if needed
            temp_episode = episode  # In models.py Episode objects are mostly data containers
            temp_episode._selected_language = lang
            temp_episode._selected_provider = prov

            temp_anime = AnimeModel(
                title=anime.title,
                slug=anime.slug,
                site=anime.site,
                language=lang,
                provider=prov,
                action=anime.action,
                episode_list=[temp_episode],
            )

            def web_progress_callback(d):
                touch_heartbeat()
                if self._stop_event.is_set() or queue_id in self._cancelled_jobs:
                    raise KeyboardInterrupt("Stopped")
                with self._queue_lock:
                    if (queue_id, original_link) in self._cancelled_episodes:
                        self._cancelled_episodes.discard((queue_id, original_link))
                        raise KeyboardInterrupt("EpCancelled")
                    if queue_id in self._skip_flags:
                        self._skip_flags.discard(queue_id)
                        raise KeyboardInterrupt("Skip")

                if d["status"] == "downloading":
                    p = 0.0
                    if d.get("_percent_str"):
                        try:
                            p = float(d["_percent_str"].replace("%", ""))
                        except Exception:
                            pass
                    if p == 0.0:
                        db, tb = d.get("downloaded_bytes", 0), d.get("total_bytes") or d.get("total_bytes_estimate")
                        if tb:
                            p = (db / tb) * 100
                    p = min(100.0, max(0.0, p))
                    s, e = re.sub(r"\x1b\[[0-9;]*m", "", str(d.get("_speed_str", "N/A"))).strip(), re.sub(r"\x1b\[[0-9;]*m", "", str(d.get("_eta_str", "N/A"))).strip()

                    with self._queue_lock:
                        if queue_id in self._active_downloads:
                            msg = f"Downloading {episode_info} - {p:.1f}%"
                            self._active_downloads[queue_id]["current_episode"] = msg

                            for ep_item in self._active_downloads[queue_id]["episodes"]:
                                if ep_item["url"] == original_link:
                                    ep_item["status"], ep_item["progress"], ep_item["speed"], ep_item["eta"] = (
                                        "downloading",
                                        p,
                                        s if s != "N/A" else "",
                                        e if e != "N/A" else "",
                                    )
                                    ep_item["last_heartbeat"] = time.time()

                    self.update_episode_progress(queue_id, p)

            from ..action.download import download
            from ..action.common import sanitize_filename as _sanitize
            from ..action.download import _get_output_filename
            # Touch the heartbeat right before invoking yt-dlp so the scheduler
            # can distinguish "still working" from "stuck before download".
            touch_heartbeat()
            logging.info(
                "[DEBUG] _download_single_episode[%s/%s]: calling download()",
                queue_id, original_link,
            )
            success = download(temp_anime, web_progress_callback, output_dir=download_dir)
            logging.info(
                "[DEBUG] _download_single_episode[%s/%s]: download() returned %s",
                queue_id, original_link, success,
            )

            # Fix 4: Sanity-check that the output file actually exists.
            # yt-dlp can sometimes report failure (e.g. post-processing
            # issues) even when the .mp4 is on disk. In that case we should
            # not mark the episode as failed - the file is what the user
            # actually wants.
            if not success:
                try:
                    sanitized_title = _sanitize(anime.title)
                    expected_filename = _get_output_filename(
                        anime, episode, sanitized_title,
                    )
                    expected_path = (
                        Path(download_dir) / sanitized_title / expected_filename
                    )
                    if expected_path.exists() and expected_path.stat().st_size > 0:
                        logging.warning(
                            "[DEBUG] _download_single_episode[%s/%s]: download() returned False "
                            "but file exists at %s (%d bytes) - treating as success",
                            queue_id, original_link, expected_path,
                            expected_path.stat().st_size,
                        )
                        success = True
                except Exception as e:
                    logging.debug(
                        "[DEBUG] _download_single_episode[%s/%s]: post-download existence "
                        "check failed: %s", queue_id, original_link, e,
                    )

            with self._queue_lock:
                if queue_id in self._active_downloads:
                    for ep_item in self._active_downloads[queue_id]["episodes"]:
                        if ep_item["url"] == original_link:
                            if success:
                                ep_item["status"], ep_item["progress"] = "completed", 100.0
                            else:
                                ep_item["status"] = "failed"

            if success:
                with self._queue_lock:
                    if queue_id in self._active_downloads:
                        self._active_downloads[queue_id]["completed_episodes"] += 1
                final_status["value"] = "completed"
            else:
                final_status["value"] = "failed"

        except KeyboardInterrupt:
            with self._queue_lock:
                if queue_id in self._active_downloads:
                    for ep_item in self._active_downloads[queue_id]["episodes"]:
                        if ep_item["url"] == original_link:
                            ep_item["status"] = "cancelled"
            final_status["value"] = "cancelled"
        except Exception as e:
            logging.error(f"Error downloading episode {episode_info}: {e}", exc_info=True)
            with self._queue_lock:
                if queue_id in self._active_downloads:
                    for ep_item in self._active_downloads[queue_id]["episodes"]:
                        if ep_item["url"] == original_link:
                            ep_item["status"] = "failed"
            final_status["value"] = "failed"
        finally:
            logging.info(
                "[DEBUG] _download_single_episode[%s/%s]: finally cleanup, final_status=%s",
                queue_id, original_link, final_status["value"],
            )
            # ALWAYS clean up heartbeat reference and notify the scheduler,
            # even on uncaught exceptions. This is the guarantee that the
            # parent loop will not get stuck on a zombie thread.
            with self._queue_lock:
                if queue_id in self._active_downloads:
                    heartbeats = self._active_downloads[queue_id].get("_ep_heartbeats")
                    if isinstance(heartbeats, dict):
                        heartbeats.pop(original_link, None)
                    # Touch job heartbeat to mark worker exit
                    self._active_downloads[queue_id]["_last_activity"] = time.time()

            # Notify the job-level scheduler that one slot is free
            try:
                self._scheduler_wakeup.set()
            except Exception:
                pass

    def _is_worker_alive_and_responsive(self, queue_id, original_link, max_age_seconds=600):
        """Check whether an episode worker is making progress (heartbeat).

        Returns ``False`` if no heartbeat has been recorded for
        ``max_age_seconds`` so the scheduler can mark the job as failed
        instead of waiting forever on a zombie thread.
        """
        with self._queue_lock:
            if queue_id not in self._active_downloads:
                return False
            heartbeats = self._active_downloads[queue_id].get("_ep_heartbeats")
            if not isinstance(heartbeats, dict):
                return True
            hb = heartbeats.get(original_link)
            if hb is None:
                return True
            return (time.time() - hb[0]) <= max_age_seconds

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
        logging.info(f"[DEBUG] stop_episode called for job {queue_id}, ep: {ep_url}")
        result = False
        with self._queue_lock:
            if queue_id in self._active_downloads:
                job = self._active_downloads[queue_id]
                # Try to find episode, be flexible with URL matching (trailing slashes)
                norm_ep_url = ep_url.rstrip("/")
                ep = next((e for e in job["episodes"] if e["url"].rstrip("/") == norm_ep_url), None)

                if not ep:
                    logging.warning(f"[DEBUG] Episode {ep_url} not found in job {queue_id}. Available: {[e['url'] for e in job['episodes']]}")
                    return False

                logging.info(f"[DEBUG] Found episode {ep['name']} with status {ep['status']}")

                if ep["status"] == "downloading":
                    ep["status"] = "cancelled"
                    # Add BOTH versions of URL to be safe
                    self._cancelled_episodes.add((queue_id, ep_url))
                    self._cancelled_episodes.add((queue_id, ep_url.rstrip("/")))
                    self._cancelled_episodes.add((queue_id, ep_url + "/"))
                    logging.info(f"[DEBUG] Episode {ep_url} marked as cancelled in job {queue_id}")
                    result = True

                elif ep["status"] == "queued":
                    ep["status"] = "cancelled"
                    logging.info(f"[DEBUG] Queued episode {ep_url} marked as cancelled in job {queue_id}")

                    # Also remove from URLs list to be doubly sure, but the iterator check is key
                    if ep["url"] in job["episode_urls"]:
                        job["episode_urls"].remove(ep["url"])
                    elif norm_ep_url in [u.rstrip("/") for u in job["episode_urls"]]:
                        # Handle normalized match
                        job["episode_urls"] = [u for u in job["episode_urls"] if u.rstrip("/") != norm_ep_url]

                    # We don't remove it from job["episodes"] yet so the UI still sees it as cancelled
                    # but we update the count
                    job["total_episodes"] = sum(1 for e in job["episodes"] if e["status"] != "cancelled")
                    result = True

                # Check if the job is now fully cancelled (all episodes cancelled).
                # In that case, mark the job as cancelled/failed so the worker
                # thread can exit cleanly and the frontend stops showing
                # "Starting..." (Fix C).
                remaining = sum(1 for e in job["episodes"] if e["status"] not in ("cancelled",))
                if remaining == 0 and job["status"] not in ("completed", "failed"):
                    logging.info(
                        "[DEBUG] All %d episodes of job %s are now cancelled - "
                        "marking job as cancelled",
                        len(job["episodes"]), queue_id,
                    )
                    self._cancelled_jobs.add(queue_id)
                    job["status"] = "cancelled"
                    job["current_episode"] = "Cancelled by user"
                    job["error_message"] = "All episodes cancelled"
                    # Wake up the worker thread
                    try:
                        self._scheduler_wakeup.set()
                    except Exception:
                        pass

        return result

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

    def _update_download_status(self, queue_id: int, status: str, completed_episodes: int = None, current_episode: str = None, error_message: str = None, total_episodes: int = None, current_episode_progress: float = None):
        notify_scheduler = False
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
            d["_last_activity"] = time.time()
            if status == "downloading" and d["started_at"] is None: d["started_at"] = datetime.now()
            elif status in ["completed", "failed"]:
                d["completed_at"] = datetime.now()
                if status == "completed": d["current_episode_progress"], d["progress_percentage"] = 100.0, 100.0
                self._completed_downloads.append(d.copy())
                if len(self._completed_downloads) > self._max_completed_history: self._completed_downloads = self._completed_downloads[-self._max_completed_history:]
                del self._active_downloads[queue_id]
                # A job slot is now free, wake the top-level scheduler
                notify_scheduler = True
        # Wake the scheduler outside the lock (Fix D)
        if notify_scheduler:
            try:
                self._scheduler_wakeup.set()
            except Exception:
                pass
        return True


_download_manager = None

def get_download_manager(database: Optional[UserDatabase] = None) -> DownloadQueueManager:
    global _download_manager
    if _download_manager is None: _download_manager = DownloadQueueManager(database)
    return _download_manager
