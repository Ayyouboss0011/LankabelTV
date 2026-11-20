import json
import re
from typing import List
from urllib.parse import urljoin, urlparse

import requests

from ... import config

# Matches the inline video configuration object on the watch page
VIDEO_OBJECT_PATTERN = re.compile(r"var\s+video\s*=\s*(\{.*?\});", re.DOTALL)

# Matches `#EXT-X-STREAM-INF:...` followed by the variant URL
STREAM_INF_PATTERN = re.compile(
    r"#EXT-X-STREAM-INF:[^\n]*BANDWIDTH=(\d+)[^\n]*\n(?P<url>[^\n#]+)",
    re.IGNORECASE,
)


def _get_headers(embed_link: str) -> dict:
    parsed = urlparse(embed_link)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": config.RANDOM_USER_AGENT,
        "Referer": f"{origin}/",
        "Accept": "*/*",
    }


def _parse_master_playlist(playlist: str, master_url: str) -> List[dict]:
    """Parse an HLS master playlist and return variants sorted by bandwidth."""
    variants = []
    for match in STREAM_INF_PATTERN.finditer(playlist):
        variants.append(
            {
                "bandwidth": int(match.group(1)),
                "url": urljoin(master_url, match.group("url").strip()),
            }
        )
    return sorted(variants, key=lambda variant: variant["bandwidth"], reverse=True)


def get_direct_link_from_gxplayer(embeded_gxplayer_link: str) -> str:
    """
    Extract a playable HLS link from a gxplayer.xyz embed URL.

    The player page contains a ``var video = {...}`` JSON object with the
    uid/md5/id/status values that are required to build the playlist URL:
    ``/m3u8/{uid}/{md5}/master.txt?s=1&id={id}&cache={status}``.

    Args:
        embeded_gxplayer_link: URL of the GXPlayer embed page

    Returns:
        Direct HLS URL (highest bandwidth variant when available)

    Raises:
        ValueError: If the video configuration or playlist cannot be parsed
        requests.RequestException: If a request fails
    """
    try:
        headers = _get_headers(embeded_gxplayer_link)

        response = requests.get(
            embeded_gxplayer_link,
            headers=headers,
            timeout=config.DEFAULT_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        match = VIDEO_OBJECT_PATTERN.search(response.text)
        if not match:
            raise ValueError("No video configuration found in GXPlayer response.")

        try:
            video = json.loads(match.group(1))
        except json.JSONDecodeError as err:
            raise ValueError(f"Failed to parse GXPlayer video configuration: {err}") from err

        uid = video.get("uid")
        md5 = video.get("md5")
        video_id = video.get("id")
        status = video.get("status", "1")

        if not uid or not md5:
            raise ValueError("GXPlayer video configuration is missing uid/md5.")

        parsed = urlparse(embeded_gxplayer_link)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        master_url = f"{origin}/m3u8/{uid}/{md5}/master.txt?s=1&id={video_id}&cache={status}"

        playlist_response = requests.get(
            master_url,
            headers=headers,
            timeout=config.DEFAULT_REQUEST_TIMEOUT,
        )
        playlist_response.raise_for_status()
        playlist = playlist_response.text

        if not playlist.lstrip().startswith("#EXTM3U"):
            raise ValueError("GXPlayer did not return a valid HLS playlist.")

        variants = _parse_master_playlist(playlist, master_url)
        if variants:
            return variants[0]["url"]

        return master_url

    except requests.RequestException as err:
        raise ValueError(f"Failed to fetch GXPlayer page: {err}") from err


if __name__ == "__main__":
    link = input("Enter GXPlayer link: ").strip()
    print(get_direct_link_from_gxplayer(link))
