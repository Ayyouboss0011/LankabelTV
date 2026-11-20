import re
import logging
import tempfile
import json
from typing import Dict, Optional, List
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_REQUEST_TIMEOUT, MPV_SCRIPTS_DIRECTORY
from ..common import copy_file_if_different, setup_autostart, setup_autoexit

# Constants
CHAPTER_FORMAT = "\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={}\nEND={}\nTITLE={}\n"
OPTION_FORMAT = "skip-{}_start={},skip-{}_end={}"
MAL_ANIME_URL = "https://myanimelist.net/anime/{}"
MAL_SEARCH_URL = "https://myanimelist.net/search/prefix.json?type=anime&keyword={}"
ANISKIP_API_URL = "https://api.aniskip.com/v1/skip-times/{}/{}?types=op&types=ed"


def _float_to_milliseconds(value: float) -> str:
    """Convert float seconds to milliseconds string."""
    return str(int(value * 1000))


def _make_request(
    url: str, timeout: int = DEFAULT_REQUEST_TIMEOUT
) -> requests.Response:
    """Make HTTP request with error handling."""
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.RequestException as err:
        logging.error("Request failed for %s: %s", url, err)
        raise


def _extract_episode_count(soup: BeautifulSoup) -> Optional[int]:
    """Extract episode count from MAL page."""
    episodes_span = soup.find("span", class_="dark_text", string="Episodes:")

    if not episodes_span or not episodes_span.parent:
        return None

    try:
        episodes_text = episodes_span.parent.text.replace("Episodes:", "").strip()
        return int(episodes_text)
    except (ValueError, AttributeError):
        return None


def _clean_anime_title(title: str) -> str:
    """Clean anime title for search."""
    # Remove episode count info
    cleaned = re.sub(r" \(\d+ episodes\)", "", title)
    # Replace spaces with URL encoding
    return re.sub(r"\s+", "%20", cleaned)


def _find_best_match(search_results: List[Dict]) -> Optional[Dict]:
    """Find best match from search results, excluding OVAs."""
    results = [entry for entry in search_results if "OVA" not in entry.get("name", "")]

    return results[0] if results else None


def _extract_anime_id_from_url(url: str) -> Optional[str]:
    """Extract anime ID from MAL URL."""
    match = re.search(r"/anime/(\d+)", url)
    return match.group(1) if match else None


def _find_sequel_info(soup: BeautifulSoup) -> Optional[str]:
    """Find sequel anime URL from MAL page."""
    sequel_div = soup.find(
        "div", string=lambda text: text and "Sequel" in text and "(TV)" in text
    )

    if not sequel_div:
        return None

    title_div = sequel_div.find_next("div", class_="title")
    if not title_div:
        return None

    link_element = title_div.find("a")
    if not link_element:
        return None

    return link_element.get("href")


def _write_chapter(file_handle, start_time: float, end_time: float, title: str) -> None:
    """Write chapter information to file."""
    file_handle.write(
        CHAPTER_FORMAT.format(
            _float_to_milliseconds(start_time), _float_to_milliseconds(end_time), title
        )
    )


def _create_skip_option(skip_type: str, start_time: float, end_time: float) -> str:
    """Create skip option string for MPV."""
    return OPTION_FORMAT.format(skip_type, start_time, skip_type, end_time)


def check_episodes(anime_id: int) -> Optional[int]:
    """
    Check episode count for anime on MyAnimeList.

    Args:
        anime_id: MAL anime ID

    Returns:
        Episode count or None if not found
    """
    try:
        response = _make_request(MAL_ANIME_URL.format(anime_id))
        soup = BeautifulSoup(response.content, "html.parser")

        episode_count = _extract_episode_count(soup)
        if episode_count is None:
            logging.warning("Episode count not found for anime ID: %s", anime_id)

        return episode_count

    except Exception as err:
        logging.error("Failed to check episodes for anime ID %s: %s", anime_id, err)
        return None


def get_mal_id_from_title(title: str, season: int) -> Optional[int]:
    """
    Get MAL ID from anime title and season.

    Args:
        title: Anime title
        season: Season number

    Returns:
        MAL anime ID or None if not found
    """
    logging.debug("Fetching MAL ID for: %s (Season %d)", title, season)

    try:
        keyword = _clean_anime_title(title)
        response = _make_request(MAL_SEARCH_URL.format(keyword))

        logging.debug("MyAnimeList response status code: %d", response.status_code)

        mal_metadata = response.json()
        categories = mal_metadata.get("categories", [])

        if not categories or not categories[0].get("items"):
            logging.error("No search results found for: %s", title)
            return None

        best_match = _find_best_match(categories[0]["items"])
        if not best_match:
            logging.error("No suitable match found for: %s", title)
            return None

        anime_id = best_match["id"]
        logging.debug(
            "Found MAL ID: %s for %s", anime_id, json.dumps(best_match, indent=4)
        )

        # Navigate to correct season
        current_id = anime_id
        for _ in range(season - 1):
            current_id = get_sequel_anime_id(current_id)
            if current_id is None:
                logging.error("Could not find season %d for anime: %s", season, title)
                return None

        return current_id

    except Exception as err:
        logging.error("Failed to get MAL ID for %s: %s", title, err)
        return None


def get_sequel_anime_id(anime_id: int) -> Optional[int]:
    """
    Get sequel anime ID from MAL.

    Args:
        anime_id: Current anime ID

    Returns:
        Sequel anime ID or None if not found
    """
    try:
        response = _make_request(MAL_ANIME_URL.format(anime_id))
        soup = BeautifulSoup(response.text, "html.parser")

        sequel_url = _find_sequel_info(soup)
        if not sequel_url:
            logging.warning("Sequel not found for anime ID: %s", anime_id)
            return None

        sequel_id = _extract_anime_id_from_url(sequel_url)
        if not sequel_id:
            logging.error("Could not extract anime ID from sequel URL: %s", sequel_url)
            return None

        return int(sequel_id)

    except Exception as err:
        logging.error("Failed to get sequel for anime ID %s: %s", anime_id, err)
        return None


def build_options(metadata: Dict, chapters_file: str) -> str:
    """
    Build MPV options from aniskip metadata.

    Args:
        metadata: Aniskip API response data
        chapters_file: Path to chapters file

    Returns:
        MPV options string
    """
    op_end, ed_start = None, None
    options = []

    try:
        with open(chapters_file, "a", encoding="utf-8") as f:
            for skip in metadata.get("results", []):
                skip_type = skip.get("skip_type")
                interval = skip.get("interval", {})
                start_time = interval.get("start_time")
                end_time = interval.get("end_time")

                if None in (skip_type, start_time, end_time):
                    logging.warning("Invalid skip data: %s", skip)
                    continue

                # Determine chapter name
                chapter_name = {"op": "Opening", "ed": "Ending"}.get(
                    skip_type, skip_type.title()
                )

                # Track timings for episode chapter
                if skip_type == "op":
                    op_end = end_time
                elif skip_type == "ed":
                    ed_start = start_time

                # Write chapter info
                _write_chapter(f, start_time, end_time, chapter_name)

                # Add skip option
                options.append(_create_skip_option(skip_type, start_time, end_time))

            # Add episode chapter if we have opening end time
            if op_end is not None:
                episode_end = ed_start if ed_start is not None else op_end
                _write_chapter(f, op_end, episode_end, "Episode")

        return ",".join(options)

    except Exception as err:
        logging.error("Failed to build options: %s", err)
        return ""


def build_flags(anime_id: str, episode: int, chapters_file: str) -> str:
    """
    Build MPV flags for aniskip functionality.

    Args:
        anime_id: MAL anime ID
        episode: Episode number
        chapters_file: Path to chapters file

    Returns:
        MPV flags string
    """
    try:
        aniskip_url = ANISKIP_API_URL.format(anime_id, episode)
        response = requests.get(aniskip_url, timeout=DEFAULT_REQUEST_TIMEOUT)

        if response.status_code == 500:
            logging.info("Aniskip API is currently not working!")
            return ""

        if response.status_code != 200:
            logging.info(
                "Failed to fetch AniSkip data (Status: %d)", response.status_code
            )
            return ""

        metadata = response.json()

        if not metadata.get("found"):
            logging.warning(
                "No skip times found for anime %s episode %d", anime_id, episode
            )
            return ""

        # Initialize chapters file
        with open(chapters_file, "w", encoding="utf-8") as f:
            f.write(";FFMETADATA1")

        options = build_options(metadata, chapters_file)

        if options:
            return f"--chapters-file={chapters_file} --script-opts={options}"

        return ""

    except Exception as err:
        logging.error("Failed to build flags: %s", err)
        return ""


def setup_aniskip() -> bool:
    """
    Set up aniskip script in MPV scripts directory.

    Returns:
        True if setup was successful
    """
    try:
        script_directory = Path(__file__).parent.parent
        mpv_scripts_path = Path(MPV_SCRIPTS_DIRECTORY)

        # Ensure scripts directory exists
        mpv_scripts_path.mkdir(parents=True, exist_ok=True)

        # Copy aniskip script
        skip_source_path = script_directory / "aniskip" / "scripts" / "aniskip.lua"
        skip_destination_path = mpv_scripts_path / "aniskip.lua"

        copy_file_if_different(str(skip_source_path), str(skip_destination_path))

        logging.debug("Aniskip script setup completed")
        return True

    except Exception as err:
        logging.error("Failed to setup aniskip: %s", err)
        return False


def aniskip(title: str, episode: int, season: int, aniworld_episodes: int) -> str:
    """
    Main aniskip function to generate MPV skip flags.

    Args:
        title: Anime title
        episode: Episode number
        season: Season number
        aniworld_episodes: Total episodes in season

    Returns:
        MPV flags string for aniskip functionality
    """
    try:
        # Setup required components
        setup_autostart()
        setup_autoexit()
        setup_aniskip()

        # Get anime ID
        if title.isdigit():
            anime_id = int(title)
        else:
            anime_id = get_mal_id_from_title(title, season)

        if not anime_id:
            logging.warning("No MAL ID found for: %s", title)
            return ""

        # Validate episode count
        mal_episodes = check_episodes(anime_id)
        if mal_episodes != aniworld_episodes:
            logging.warning(
                "Episode count mismatch: MAL=%s, AniWorld=%s",
                mal_episodes,
                aniworld_episodes,
            )
            return ""

        # Create temporary chapters file and build flags
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as chapters_file:
            return build_flags(str(anime_id), episode, chapters_file.name)

    except Exception as err:
        logging.error("Aniskip failed for %s: %s", title, err)
        return ""


if __name__ == "__main__":
    # Test functionality
    print(get_mal_id_from_title("Kaguya-sama: Love is War", season=1))
