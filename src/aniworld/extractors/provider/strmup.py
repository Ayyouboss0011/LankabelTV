import re
import logging
import requests
from urllib.parse import urlparse

from ...config import RANDOM_USER_AGENT, DEFAULT_REQUEST_TIMEOUT

# Constants
STRMUP_AJAX_URL = "https://strmup.to/ajax/stream"


def get_direct_link_from_strmup(embeded_strmup_link: str) -> str:
    """
    Extract direct download link from Strmup embed URL.

    Args:
        embeded_strmup_link: Strmup embed URL

    Returns:
        Direct download link (HLS/m3u8)

    Raises:
        ValueError: If required data cannot be extracted
        requests.RequestException: If HTTP requests fail
    """
    if not embeded_strmup_link:
        raise ValueError("Embed URL cannot be empty")

    logging.info(f"Extracting direct link from Strmup: {embeded_strmup_link}")

    try:
        # Extract filecode from URL
        # URL format: https://strmup.to/vw60nJubtF4SL?zUKfPG
        parsed = urlparse(embeded_strmup_link)
        path_parts = parsed.path.strip("/").split("/")
        filecode = path_parts[-1] if path_parts else None

        if not filecode:
             raise ValueError("Could not extract filecode from URL")

        # Request AJAX API
        params = {"filecode": filecode}
        headers = {
            "User-Agent": RANDOM_USER_AGENT,
            "Referer": embeded_strmup_link,
            "X-Requested-With": "XMLHttpRequest"
        }
        
        response = requests.get(
            STRMUP_AJAX_URL, 
            params=params, 
            headers=headers, 
            timeout=DEFAULT_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        data = response.json()
        streaming_url = data.get("streaming_url")
        
        if not streaming_url:
            raise ValueError("No streaming_url found in API response")
            
        # Ensure it's a valid URL
        if not streaming_url.startswith("http"):
             streaming_url = "https:" + streaming_url if streaming_url.startswith("//") else streaming_url

        logging.info("Successfully extracted Strmup direct link")
        return streaming_url

    except Exception as err:
        logging.error(f"Failed to extract direct link from Strmup: {err}")
        raise


def get_preview_image_link_from_strmup(embeded_strmup_link: str) -> str:
    """
    Extract preview image link from Strmup embed URL.
    """
    try:
        parsed = urlparse(embeded_strmup_link)
        path_parts = parsed.path.strip("/").split("/")
        filecode = path_parts[-1] if path_parts else None

        if not filecode:
             raise ValueError("Could not extract filecode from URL")

        params = {"filecode": filecode}
        headers = {
            "User-Agent": RANDOM_USER_AGENT,
            "Referer": embeded_strmup_link,
            "X-Requested-With": "XMLHttpRequest"
        }
        
        response = requests.get(
            STRMUP_AJAX_URL, 
            params=params, 
            headers=headers, 
            timeout=DEFAULT_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        data = response.json()
        thumbnail = data.get("thumbnail")
        
        if thumbnail:
             return thumbnail
        raise ValueError("No thumbnail found")

    except Exception as err:
        logging.error(f"Failed to extract preview image from Strmup: {err}")
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    try:
        url = input("Enter Strmup Link: ").strip()
        print(get_direct_link_from_strmup(url))
    except Exception as e:
        print(e)
