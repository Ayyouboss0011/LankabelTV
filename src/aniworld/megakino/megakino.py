#!/usr/bin/env python3
"""
MegaKino API module for searching movies/series and retrieving their
VOE / GXPlayer stream links.

The site is a DataLife Engine (DLE) installation with a light JavaScript
challenge: the first request has to hit ``/index.php?yg=token`` which sets a
``yg_token`` cookie. Afterwards all pages can be scraped with a normal
``requests.Session``.

The domain rotates regularly (e.g. megakino23.com -> megakino24.com). The
client therefore never trusts a static base URL: on the first request (and
again after connection failures) it probes candidate domains, follows the
redirects and adopts the final live domain for all subsequent requests.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from ..config import (
        DEFAULT_REQUEST_TIMEOUT,
        MEGAKINO_BASE_URL,
        MEGAKINO_FALLBACK_DOMAINS,
        RANDOM_USER_AGENT,
    )
except ImportError:  # pragma: no cover - allows running the file directly
    import os
    import sys

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from aniworld.config import (  # type: ignore
        DEFAULT_REQUEST_TIMEOUT,
        MEGAKINO_BASE_URL,
        MEGAKINO_FALLBACK_DOMAINS,
        RANDOM_USER_AGENT,
    )

MEGAKINO_TOKEN_PATH = "/index.php?yg=token"
MEGAKINO_SEARCH_PATH = "/index.php?do=search"
MEGAKINO_PAGE_SIZE = 20
MEGAKINO_MIN_SEARCH_LENGTH = 4

# Minimum page size (bytes) below which a response is treated as the JS challenge
MEGAKINO_CHALLENGE_MAX_SIZE = 2000

# Timeout (seconds) for probing a single candidate domain
MEGAKINO_DOMAIN_PROBE_TIMEOUT = 10

# Number of future numbered domains (megakinoN+1.com, ...) probed when the
# configured domain is completely dead (no redirect at all)
MEGAKINO_DOMAIN_GUESS_RANGE = 10

MEGAKINO_DOMAIN_RE = re.compile(r"(\d+)")

MEGAKINO_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "user-agent": RANDOM_USER_AGENT,
}

# Mapping of embed hosts to our internal provider names
PROVIDER_HOST_MAP = {
    "voe.sx": "VOE",
    "gxplayer.xyz": "GXPlayer",
}

# Preferred order for download fallbacks
PROVIDER_PRIORITY = ("VOE", "GXPlayer")


def provider_from_url(url: str) -> Optional[str]:
    """Resolve an embed URL to a supported provider name."""
    host = (urlparse(url).netloc or "").lower()
    for key, name in PROVIDER_HOST_MAP.items():
        if key in host:
            return name
    return None


def is_megakino_url(url: str) -> bool:
    """Return True for URLs pointing to MegaKino content.

    The MegaKino domain rotates regularly, so detection does not rely on a
    single static base URL: it matches the ``megakino:`` URL prefix used
    internally, any numbered ``megakinoN.com`` host, and the stable DLE
    content paths (``/films/<slug>.html`` / ``/serials/<slug>.html``) that
    survive domain changes.
    """
    url = str(url or "")
    if url.startswith("megakino:"):
        return True
    host = (urlparse(url).netloc or "").lower()
    if host.startswith("megakino") and host.endswith(".com"):
        return True
    return bool(re.search(r"/(?:films|serials)/[^/]+\.html", url))


class MegakinoClient:
    """Small client around the (rotating) MegaKino domain.

    ``base_url`` is only the starting point for domain resolution: the
    client probes candidate domains (configured base, explicit fallbacks,
    numbered-domain guesses), follows redirects and adopts the live domain
    for all requests.
    """

    def __init__(
        self,
        base_url: str = MEGAKINO_BASE_URL,
        headers: Optional[Dict[str, str]] = None,
        fallback_domains: Optional[List[str]] = None,
    ) -> None:
        self._configured_base = (base_url or MEGAKINO_BASE_URL).rstrip("/")
        self.base_url = self._configured_base
        if fallback_domains is None:
            fallback_domains = MEGAKINO_FALLBACK_DOMAINS
        self._fallback_domains = [
            d.strip() if d.strip().startswith("http") else f"https://{d.strip()}"
            for d in fallback_domains
            if d.strip()
        ]
        self._base_resolved = False
        self.session = requests.Session()
        self.session.headers.update(MEGAKINO_HEADERS)
        if headers:
            self.session.headers.update(headers)
        self._token_ready = False

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _absolute(self, url: str) -> str:
        if url.startswith("http"):
            return url
        return urljoin(self.base_url + "/", url)

    def _on_current_base(self, url: str) -> str:
        """Rewrite an absolute URL so it points at the current base_url."""
        parsed = urlparse(url)
        current_host = urlparse(self.base_url).netloc
        if parsed.netloc and parsed.netloc != current_host:
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            return self.base_url + path
        return url

    @staticmethod
    def _is_challenge(response: requests.Response) -> bool:
        """Detect the tiny JS-challenge page."""
        try:
            text = response.text
        except Exception:
            return False
        return len(text) < MEGAKINO_CHALLENGE_MAX_SIZE and "yg=token" in text

    def _ensure_token(self, force: bool = False) -> None:
        """Fetch the yg_token cookie if we don't have it yet."""
        if self._token_ready and not force:
            return
        try:
            self.session.get(
                self.base_url + MEGAKINO_TOKEN_PATH,
                timeout=DEFAULT_REQUEST_TIMEOUT,
                allow_redirects=False,
            )
            self._token_ready = True
        except requests.RequestException as err:
            logging.warning("MegaKino: failed to fetch yg_token: %s", err)

    # ------------------------------------------------------------------
    # Dynamic domain resolution (MegaKino rotates its domain)
    # ------------------------------------------------------------------
    def _candidate_bases(self) -> List[str]:
        """Ordered candidate base URLs: configured base, explicit fallback
        domains and numbered-domain guesses (megakinoN+1.com, ...)."""
        candidates: List[str] = [self._configured_base]
        candidates.extend(self._fallback_domains)

        match = MEGAKINO_DOMAIN_RE.search(urlparse(self._configured_base).netloc)
        if match:
            current = int(match.group(1))
            for number in range(current + 1, current + 1 + MEGAKINO_DOMAIN_GUESS_RANGE):
                candidates.append(f"https://megakino{number}.com")

        seen = set()
        unique: List[str] = []
        for candidate in candidates:
            candidate = candidate.rstrip("/")
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

    def _probe_base(self, candidate: str) -> Optional[str]:
        """Probe one candidate domain; return the final live base URL it
        leads to (following redirects), or None when it is dead."""
        try:
            response = self.session.get(
                candidate,
                timeout=MEGAKINO_DOMAIN_PROBE_TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException as err:
            logging.debug("MegaKino: probe of %s failed: %s", candidate, err)
            return None
        if response.status_code >= 400:
            return None
        parsed = urlparse(response.url)
        if not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}"

    def resolve_base_url(self, force: bool = False) -> str:
        """Resolve the live MegaKino domain and adopt it as base URL.

        Probes the candidate domains in order and uses the final URL of the
        first one that responds. Falls back to the configured base URL when
        nothing responds (preserves the previous behaviour).
        """
        if self._base_resolved and not force:
            return self.base_url
        for candidate in self._candidate_bases():
            base = self._probe_base(candidate)
            if base:
                if base != self.base_url:
                    logging.info(
                        "MegaKino: domain rotated, using %s (was %s)",
                        base,
                        self.base_url,
                    )
                self.base_url = base
                self._base_resolved = True
                self._token_ready = False
                return base
        logging.warning(
            "MegaKino: no candidate domain responded, keeping %s", self.base_url
        )
        return self.base_url

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Perform a request, transparently handling the token challenge and
        domain rotations (the MegaKino domain changes over time)."""
        self.resolve_base_url()
        self._ensure_token()
        target = self._on_current_base(self._absolute(url))
        try:
            response = self.session.request(
                method, target, timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs
            )
        except requests.RequestException as err:
            # The domain may have rotated since the last successful request:
            # re-resolve, refresh the token and retry once.
            previous_base = self.base_url
            self.resolve_base_url(force=True)
            if self.base_url == previous_base:
                raise
            self._ensure_token()
            target = self._on_current_base(self._absolute(url))
            response = self.session.request(
                method, target, timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs
            )

        # A request can land on a new domain via 301/302 (for POSTs this is
        # fatal: requests drops the request body). Adopt the new domain and
        # replay the request on it.
        final_host = urlparse(response.url).netloc
        current_host = urlparse(self.base_url).netloc
        if final_host and final_host != current_host:
            self.base_url = f"{urlparse(response.url).scheme}://{final_host}"
            self._base_resolved = True
            self._token_ready = False
            logging.info(
                "MegaKino: request redirected to %s, switching base URL",
                self.base_url,
            )
            self._ensure_token()
            target = self._on_current_base(self._absolute(url))
            response = self.session.request(
                method, target, timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs
            )

        if self._is_challenge(response):
            self._ensure_token(force=True)
            target = self._on_current_base(self._absolute(url))
            response = self.session.request(
                method, target, timeout=DEFAULT_REQUEST_TIMEOUT, **kwargs
            )
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        """
        Search MegaKino for movies and series.

        Args:
            query: Search term (minimum 4 characters, enforced by the site)
            page: 1-based page number (20 results per page)

        Returns:
            List of result dicts with name/year/url/cover/description/media_type
        """
        query = (query or "").strip()
        if len(query) < MEGAKINO_MIN_SEARCH_LENGTH:
            logging.info(
                "MegaKino: query '%s' is shorter than %d characters, skipping",
                query,
                MEGAKINO_MIN_SEARCH_LENGTH,
            )
            return []

        page = max(1, int(page))
        data = {
            "do": "search",
            "subaction": "search",
            "search_start": str(page - 1),
            "full_search": "0",
            "result_from": str((page - 1) * MEGAKINO_PAGE_SIZE + 1),
            "story": query,
        }
        response = self._request("POST", MEGAKINO_SEARCH_PATH, data=data)
        return self._parse_search_results(response.text)

    def _parse_search_results(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []

        for card in soup.select("a.poster.grid-item"):
            href = (card.get("href") or "").strip()
            if not href:
                continue
            url = self._absolute(href)

            title_tag = card.select_one(".poster__title")
            name = title_tag.get_text(strip=True) if title_tag else ""
            if not name:
                img = card.select_one("img")
                name = (img.get("alt") or "").strip() if img else ""
            if not name:
                continue

            sub_items = [
                li.get_text(strip=True) for li in card.select(".poster__subtitle li")
            ]
            year = ""
            genres: List[str] = []
            if sub_items:
                year_match = re.search(r"(?:19|20)\d{2}", sub_items[0])
                if year_match:
                    year = year_match.group(0)
                genre_source = sub_items[1] if len(sub_items) > 1 else sub_items[0]
                genres = [g.strip() for g in genre_source.split("/") if g.strip()]

            media_type = (
                "series"
                if any(g.lower().startswith("serie") for g in genres)
                else "movie"
            )

            cover = ""
            img_tag = card.select_one("img")
            if img_tag:
                cover = (img_tag.get("data-src") or img_tag.get("src") or "").strip()
                if cover and not cover.startswith("http"):
                    cover = self._absolute(cover)

            desc_tag = card.select_one(".poster__text")
            description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            results.append(
                {
                    "name": name,
                    "year": year,
                    "url": url,
                    "cover": cover,
                    "description": description,
                    "media_type": media_type,
                    "genres": genres,
                }
            )

        return results

    # ------------------------------------------------------------------
    # Details
    # ------------------------------------------------------------------
    def get_details(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a MegaKino content page and return metadata + streams.

        Returns a dict with ``media_type`` set to ``movie`` or ``series``.
        Movies expose ``streams``; series expose ``season`` and ``episodes``
        (each episode has its own ``streams``).
        """
        if not url:
            return None

        response = self._request("GET", self._absolute(url))
        soup = BeautifulSoup(response.text, "html.parser")

        details = self._parse_metadata(soup)
        details["url"] = response.url

        is_series = bool(soup.select_one("select.mr-select") or soup.select_one("select.se-select"))
        if is_series:
            details["media_type"] = "series"
            details["season"] = self._parse_season_number(details.get("title", ""), response.url)
            details["episodes"] = self._parse_series_episodes(soup)
            details["streams"] = []
        else:
            details["media_type"] = "movie"
            details["season"] = 0
            details["streams"] = self._extract_movie_streams(soup)
            details["episodes"] = []

        return details

    def get_movie(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch movie details (returns None when the page is a series)."""
        details = self.get_details(url)
        if not details or details.get("media_type") != "movie":
            return None
        return details

    def get_series_season(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch a series season page (returns None when the page is a movie)."""
        details = self.get_details(url)
        if not details or details.get("media_type") != "series":
            return None
        return details

    def get_streams(
        self, url: str, episode: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        Return the stream candidates for a movie or a single episode.

        Args:
            url: MegaKino movie/series page URL
            episode: Episode number (only for series pages)

        Returns:
            List of ``{"provider": ..., "url": ...}`` ordered by provider priority
        """
        details = self.get_details(url)
        if not details:
            return []

        if details.get("media_type") == "movie":
            streams = details.get("streams", [])
        else:
            streams = []
            for ep in details.get("episodes", []):
                if episode is None or int(ep.get("episode", 0)) == int(episode):
                    streams = ep.get("streams", [])
                    break

        return self._sort_streams(streams)

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    def _parse_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        title_tag = soup.select_one("h1[itemprop='name']") or soup.select_one("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        year = ""
        year_tag = soup.select_one(".pmovie__year")
        if year_tag:
            year_match = re.search(r"(?:19|20)\d{2}", year_tag.get_text(" ", strip=True))
            if year_match:
                year = year_match.group(0)

        genres: List[str] = []
        genres_tag = soup.select_one(".pmovie__genres")
        if genres_tag:
            genres = [
                g.strip()
                for g in genres_tag.get_text(" ", strip=True).split("/")
                if g.strip()
            ]

        rating = None
        rating_tag = soup.select_one(".pmovie__subrating--kp")
        if rating_tag:
            rating_match = re.search(r"\d+(?:[.,]\d+)?", rating_tag.get_text(" ", strip=True))
            if rating_match:
                rating = rating_match.group(0).replace(",", ".")

        poster = ""
        img_tag = soup.select_one("img[itemprop='image']") or soup.select_one(
            ".pmovie__poster img"
        )
        if img_tag:
            poster = (img_tag.get("data-src") or img_tag.get("src") or "").strip()
            if poster and not poster.startswith("http"):
                poster = self._absolute(poster)

        description = ""
        desc_tag = soup.select_one("div[itemprop='description']")
        if desc_tag:
            description = desc_tag.get_text(" ", strip=True)
        if not description:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                description = (meta_desc.get("content") or "").strip()

        return {
            "title": title,
            "year": year,
            "genres": genres,
            "rating": rating,
            "poster": poster,
            "description": description,
        }

    @staticmethod
    def _parse_season_number(title: str, url: str = "") -> int:
        for source in (title or "", url or ""):
            match = re.search(
                r"(\d+)\s*(?:staffel|stafffel|season)", source, re.IGNORECASE
            )
            if match:
                return int(match.group(1))
        return 1

    def _extract_movie_streams(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        streams: List[Dict[str, str]] = []
        seen = set()

        iframes = soup.select(".pmovie__player .tabs-block__content iframe")
        if not iframes:
            iframes = soup.select("iframe[id='film_main'], iframe[data-src]")

        for iframe in iframes:
            embed = (iframe.get("data-src") or iframe.get("src") or "").strip()
            if not embed or embed.startswith("//"):
                if embed.startswith("//"):
                    embed = "https:" + embed
                else:
                    continue
            provider = provider_from_url(embed)
            if not provider or embed in seen:
                continue
            seen.add(embed)
            streams.append({"provider": provider, "url": embed})

        # Some movies also provide streams via per-episode selects
        if not streams:
            streams = self._extract_select_streams(soup)

        return self._sort_streams(streams)

    def _extract_select_streams(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        streams: List[Dict[str, str]] = []
        seen = set()
        for select in soup.select("select.mr-select"):
            for option in select.find_all("option"):
                embed = (option.get("value") or "").strip()
                if not embed.startswith("http"):
                    continue
                provider = provider_from_url(embed)
                if not provider or embed in seen:
                    continue
                seen.add(embed)
                streams.append({"provider": provider, "url": embed})
        return streams

    def _parse_series_episodes(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        episode_titles: Dict[int, str] = {}
        main_select = soup.select_one("select.se-select")
        if main_select:
            for option in main_select.find_all("option"):
                value = (option.get("value") or "").strip()
                match = re.search(r"(\d+)", value)
                if match:
                    episode_titles[int(match.group(1))] = option.get_text(strip=True)

        episodes: List[Dict[str, Any]] = []
        for select in soup.select("select.mr-select"):
            select_id = select.get("id") or ""
            match = re.search(r"(\d+)", select_id)
            if not match:
                continue
            episode_num = int(match.group(1))

            streams: List[Dict[str, str]] = []
            seen = set()
            for option in select.find_all("option"):
                embed = (option.get("value") or "").strip()
                if not embed.startswith("http"):
                    continue
                provider = provider_from_url(embed)
                if not provider or embed in seen:
                    continue
                seen.add(embed)
                streams.append({"provider": provider, "url": embed})

            if streams:
                episodes.append(
                    {
                        "episode": episode_num,
                        "title": episode_titles.get(episode_num, f"Episode {episode_num}"),
                        "streams": self._sort_streams(streams),
                    }
                )

        # Fallback when only the main select exists
        if not episodes and episode_titles:
            for episode_num, title in sorted(episode_titles.items()):
                episodes.append({"episode": episode_num, "title": title, "streams": []})

        episodes.sort(key=lambda ep: ep["episode"])
        return episodes

    @staticmethod
    def _sort_streams(streams: List[Dict[str, str]]) -> List[Dict[str, str]]:
        def key(stream: Dict[str, str]) -> int:
            provider = stream.get("provider", "")
            try:
                return PROVIDER_PRIORITY.index(provider)
            except ValueError:
                return len(PROVIDER_PRIORITY)

        return sorted(streams, key=key)


def search_megakino(query: str, page: int = 1) -> List[Dict[str, Any]]:
    """Convenience wrapper around :meth:`MegakinoClient.search`."""
    return MegakinoClient().search(query, page=page)


def get_megakino_details(url: str) -> Optional[Dict[str, Any]]:
    """Convenience wrapper around :meth:`MegakinoClient.get_details`."""
    return MegakinoClient().get_details(url)


def _main() -> None:
    client = MegakinoClient()
    query = input("Search MegaKino: ").strip()
    results = client.search(query)
    print(f"\nFound {len(results)} results:")
    for idx, result in enumerate(results, start=1):
        print(
            f"{idx}. [{result['media_type']}] {result['name']} ({result['year']}) -> {result['url']}"
        )

    if not results:
        return
    choice = input("\nSelect a result for details (number, empty to quit): ").strip()
    if not choice.isdigit():
        return
    details = client.get_details(results[int(choice) - 1]["url"])
    if not details:
        print("No details found.")
        return
    print(f"\n{details['title']} ({details['year']}) [{details['media_type']}]")
    print(f"Rating: {details.get('rating')} | Genres: {', '.join(details.get('genres', []))}")
    print(f"Description: {details.get('description', '')[:200]}...")
    if details["media_type"] == "movie":
        for stream in details["streams"]:
            print(f"  {stream['provider']}: {stream['url']}")
    else:
        print(f"Season {details['season']} - {len(details['episodes'])} episodes")
        for episode in details["episodes"]:
            providers = ", ".join(s["provider"] for s in episode["streams"])
            print(f"  {episode['title']}: {providers}")


if __name__ == "__main__":
    _main()
