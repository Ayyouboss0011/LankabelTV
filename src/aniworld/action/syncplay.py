import getpass
import logging
import hashlib
from typing import Optional, List

from ..models import Anime
from ..config import (
    MPV_PATH,
    PROVIDER_HEADERS_W,
    SYNCPLAY_PATH,
)
from ..common import (
    download_mpv,
    download_syncplay,
    setup_autostart,
    setup_autoexit,
)
from ..parser import arguments
from .common import (
    get_direct_link,
    get_media_title,
    sanitize_filename,
    execute_command,
    get_aniskip_data,
)


def _get_syncplay_username() -> str:
    """Get syncplay username from arguments or system user."""
    return arguments.username or getpass.getuser()


def _get_syncplay_hostname() -> str:
    """Get syncplay hostname from arguments or default."""
    return arguments.hostname or "syncplay.pl:8997"


def _get_syncplay_room(title: str) -> str:
    """Generate syncplay room name with optional password hashing."""
    if arguments.room:
        return arguments.room

    room = title
    if arguments.password:
        room += f":{arguments.password}"

    room_hash = hashlib.sha256(room.encode("utf-8")).hexdigest()
    return f"AniWorld_Downloader.{room_hash}"


def _append_password_to_command(command: List[str], title: str) -> List[str]:
    """Add password to syncplay command if provided."""
    if not arguments.password:
        return command

    password = f"{arguments.password}:{title}"
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()

    # Insert password at position 9 (after --name argument)
    command.insert(9, "--password")
    command.insert(10, password_hash)
    return command


def _format_episode_title(anime: Anime, episode) -> str:
    """Format episode title for logging."""
    return f"{anime.title} - S{episode.season}E{episode.episode} - ({anime.language}):"


def _build_syncplay_command(
    source: str,
    title: Optional[str] = None,
    headers: Optional[List[str]] = None,
    aniskip_data: Optional[str] = None,
    anime: Optional[Anime] = None,
    media_title: Optional[str] = None,
) -> List[str]:
    """Build syncplay command with all necessary parameters."""
    command = [
        SYNCPLAY_PATH,
        "--no-gui",
        "--no-store",
        "--host",
        _get_syncplay_hostname(),
        "--room",
        _get_syncplay_room(title=title or "default"),
        "--name",
        _get_syncplay_username(),
        "--player-path",
        MPV_PATH,
        source,
        "--",
        "--fs",
    ]

    if media_title:
        command.append(f'--force-media-title="{media_title}"')

    if title:
        command = _append_password_to_command(command, title)

    # Add provider-specific configurations
    if anime and anime.provider == "LoadX":
        command.extend(["--demuxer=lavf", "--demuxer-lavf-format=hls"])

    # Add headers
    if headers:
        for header in headers:
            command.append(f"--http-header-fields={header}")

    # Add aniskip data
    if aniskip_data:
        command.extend(aniskip_data.split()[:2])

    return command


def _process_anime_episodes(anime: Anime) -> None:
    """Process and play all episodes of an anime through syncplay."""
    sanitized_anime_title = sanitize_filename(anime.title)

    for episode in anime:
        # Print internal stats for debugging as requested by user
        requested_lang = anime.language
        requested_provider = anime.provider
        actual_lang = getattr(episode, "_selected_language", requested_lang)
        actual_provider = getattr(episode, "_selected_provider", requested_provider)
        
        print(f"\n[DEBUG] Syncplay Stats:")
        print(f"  Series: {anime.title}")
        print(f"  Episode: S{episode.season:02}E{episode.episode:03}" if episode.season != 0 else f"  Movie: {episode.episode:03}")
        print(f"  UI/Requested: Language='{requested_lang}', Provider='{requested_provider}'")
        print(f"  Internal/Actual: Language='{actual_lang}', Provider='{actual_provider}'")
        print(f"  Site: {episode.site}")

        episode_title = _format_episode_title(anime, episode)

        # Get direct link
        direct_link = get_direct_link(episode, episode_title)
        if not direct_link:
            logging.warning(
                'Something went wrong with "%s".\nNo direct link found.', episode_title
            )
            continue

        # Handle direct link only mode
        if arguments.only_direct_link:
            print(episode_title)
            print(f"{direct_link}\n")
            continue

        # Generate media title
        media_title = get_media_title(anime, episode, sanitized_anime_title)

        # Get aniskip data
        aniskip_data = get_aniskip_data(anime, episode)

        # Build and execute command
        command = _build_syncplay_command(
            source=direct_link,
            title=episode.title_german,
            headers=PROVIDER_HEADERS_W.get(anime.provider),
            aniskip_data=aniskip_data,
            anime=anime,
            media_title=media_title,
        )

        execute_command(command)


def _process_local_files() -> None:
    """Process local files through syncplay."""
    for file in arguments.local_episodes:
        command = _build_syncplay_command(source=file)
        execute_command(command)


def syncplay(anime: Optional[Anime] = None) -> None:
    """Main syncplay function to setup and play anime or local files."""
    try:
        # Download and setup required components
        download_mpv()
        download_syncplay()
        setup_autostart()
        setup_autoexit()

        # Process files
        if anime is None:
            _process_local_files()
        else:
            _process_anime_episodes(anime)

    except KeyboardInterrupt:
        logging.info("Syncplay session interrupted by user")
    except Exception as err:
        logging.error("Error in syncplay session: %s", err)
        raise


if __name__ == "__main__":
    download_syncplay()
