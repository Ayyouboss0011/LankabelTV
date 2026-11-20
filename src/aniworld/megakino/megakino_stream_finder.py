#!/usr/bin/env python3
"""
Bridge between MegaKino stream URLs and the existing AniWorld download engine.

MegaKino provides embed links (VOE / GXPlayer) instead of episode pages, so we
build lightweight ``Anime``/``Episode`` objects that already carry the embed
link and provider. The download engine then only has to run the matching
provider extractor before handing the direct link to yt-dlp.
"""

import logging
import re
from typing import Callable, Optional

from ..action.download import download
from ..models import Anime, Episode
from ..parser import arguments
from .megakino import provider_from_url

# Language codes used by the site (German only)
LANGUAGE_MAP = {
    "de": "German Dub",
    "de-dub": "German Dub",
    "german": "German Dub",
}


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]", "", (title or "movie").replace(" ", "-").lower())
    return slug or "movie"


def create_anime_object(
    stream_url: str,
    title: str,
    language: str,
    provider_name: str,
    season: int = 0,
    episode: int = 1,
    output_directory: Optional[str] = None,
) -> Anime:
    """Build an Anime/Episode pair that is ready for the download engine."""
    slug = _slugify(title)

    episode_obj = Episode(
        anime_title=title,
        title_german=title,
        title_english=title,
        season=season,
        episode=episode,
        slug=slug,
        link=None,
        embeded_link=stream_url,
        provider={provider_name: {1: stream_url}},
        provider_name=[provider_name],
        language=[1],
        language_name=[language],
        _selected_provider=provider_name,
        _selected_language=language,
    )
    episode_obj.direct_link = None

    return Anime(
        title=title,
        slug=slug,
        episode_list=[episode_obj],
        action="Download",
        provider=provider_name,
        language=language,
        output_directory=output_directory or "",
        skip_shared_data=True,
    )


def download_stream(
    stream_url: str,
    title: str,
    lang_code: str = "de",
    provider_name: Optional[str] = None,
    season: int = 0,
    episode: int = 1,
    web_progress_callback: Optional[Callable] = None,
    output_dir: Optional[str] = None,
) -> bool:
    """
    Download a single MegaKino stream via the existing download engine.

    Returns True when the download succeeded.
    """
    if not provider_name:
        provider_name = provider_from_url(stream_url) or "VOE"

    language = LANGUAGE_MAP.get((lang_code or "de").lower(), "German Dub")

    print(f"\nPreparing download: {title} ({language}) via {provider_name}")
    print(f"Embed URL: {stream_url}")
    if output_dir:
        print(f"Output directory: {output_dir}")

    try:
        anime = create_anime_object(
            stream_url,
            title,
            language,
            provider_name,
            season=season,
            episode=episode,
            output_directory=output_dir,
        )
        if output_dir:
            anime.output_directory = output_dir
            arguments.output_dir = output_dir

        print("-" * 60)
        success = download(anime, web_progress_callback=web_progress_callback)
        print("-" * 60)
        return success

    except Exception as err:  # noqa: BLE001 - surface any download failure
        logging.error("MegaKino download failed for '%s': %s", title, err)
        import traceback

        traceback.print_exc()
        return False
