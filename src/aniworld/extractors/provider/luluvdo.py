import re
import logging
import sys
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import requests

from ... import config

# Setup module logger
logger = logging.getLogger(__name__)


def _validate_luluvdo_url(url: str) -> str:
    """
    Validate and clean the LuluVDO URL.

    Args:
        url: URL to validate

    Returns:
        Validated and cleaned URL

    Raises:
        ValueError: If URL is invalid
    """
    if not url or not url.strip():
        raise ValueError("LuluVDO URL cannot be empty")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL format - must start with http:// or https://")

    try:
        parsed_url = urlparse(url)
        if not parsed_url.netloc:
            raise ValueError("Invalid URL format - missing domain")

        # Basic domain validation for LuluVDO
        if "luluvdo.com" not in parsed_url.netloc.lower():
            raise ValueError("URL must be from luluvdo.com domain")

    except Exception as err:
        raise ValueError(f"Invalid URL format: {err}") from err

    return url


def _extract_luluvdo_id(url: str) -> str:
    """
    Extract LuluVDO ID from URL.

    Args:
        url: LuluVDO URL

    Returns:
        LuluVDO ID

    Raises:
        ValueError: If ID cannot be extracted
    """
    try:
        url_parts = url.split("/")
        if not url_parts:
            raise ValueError("Invalid URL structure")

        luluvdo_id = url_parts[-1]
        if not luluvdo_id:
            raise ValueError("No ID found in URL")

        # Remove query parameters if present
        if "?" in luluvdo_id:
            luluvdo_id = luluvdo_id.split("?")[0]

        if not luluvdo_id:
            raise ValueError("Empty ID after processing")

        return luluvdo_id

    except Exception as err:
        logger.error(f"Failed to extract LuluVDO ID from URL: {err}")
        raise ValueError(f"Failed to extract LuluVDO ID: {err}") from err


def _build_embed_url(luluvdo_id: str) -> str:
    """
    Build embed URL for LuluVDO.

    Args:
        luluvdo_id: LuluVDO ID

    Returns:
        Embed URL
    """
    return f"https://luluvdo.com/dl?op=embed&file_code={luluvdo_id}&embed=1&referer=luluvdo.com&adb=0"


def _build_headers(arguments: Optional[Any] = None) -> Dict[str, str]:
    """
    Build headers for LuluVDO request.

    Args:
        arguments: Optional arguments object

    Returns:
        Headers dictionary
    """
    headers = {
        "Origin": "https://luluvdo.com",
        "Referer": "https://luluvdo.com/",
        "User-Agent": config.LULUVDO_USER_AGENT,
    }

    # Add language header for downloads
    if arguments and hasattr(arguments, "action") and arguments.action == "Download":
        headers["Accept-Language"] = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"

    return headers


def _make_request(url: str, headers: Dict[str, str]) -> requests.Response:
    """
    Make HTTP request with error handling.

    Args:
        url: URL to request
        headers: Request headers

    Returns:
        HTTP response object

    Raises:
        ValueError: If request fails
    """
    try:
        logger.debug(f"Making request to: {url}")
        response = requests.get(
            url, headers=headers, timeout=config.DEFAULT_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response

    except requests.RequestException as err:
        logger.error(f"Request failed for {url}: {err}")
        raise ValueError(f"Failed to fetch URL: {err}") from err


def _extract_video_url(response_text: str) -> str:
    """
    Extract video URL from response text.

    Args:
        response_text: HTML response text

    Returns:
        Video URL

    Raises:
        ValueError: If video URL cannot be extracted
    """
    try:
        if not response_text:
            raise ValueError("Empty response received")

        pattern = r'file:\s*"([^"]+)"'
        matches = re.findall(pattern, response_text)

        if not matches:
            raise ValueError("No video URL found in response")

        video_url = matches[0].strip()
        if not video_url:
            raise ValueError("Empty video URL found")

        logger.debug(f"Extracted video URL: {video_url}")
        return video_url

    except Exception as err:
        logger.error(f"Failed to extract video URL: {err}")
        raise ValueError(f"Failed to extract video URL: {err}") from err


def get_direct_link_from_luluvdo(
    embeded_luluvdo_link: str, arguments: Optional[Any] = None
) -> str:
    """
    Extract direct video link from LuluVDO embedded URL.

    Args:
        embeded_luluvdo_link: LuluVDO embedded URL
        arguments: Optional arguments object for additional configuration

    Returns:
        Direct video URL

    Raises:
        ValueError: If extraction fails
    """
    try:
        # Validate input URL
        validated_url = _validate_luluvdo_url(embeded_luluvdo_link)
        logger.info(f"Extracting video from LuluVDO URL: {validated_url}")

        # Extract LuluVDO ID
        luluvdo_id = _extract_luluvdo_id(validated_url)
        logger.debug(f"Extracted LuluVDO ID: {luluvdo_id}")

        # Build embed URL
        embed_url = _build_embed_url(luluvdo_id)

        # Build headers
        headers = _build_headers(arguments)

        # Make request
        response = _make_request(embed_url, headers)

        # Check response status
        if response.status_code != 200:
            raise ValueError(f"Server returned status code: {response.status_code}")

        # Extract video URL
        video_url = _extract_video_url(response.text)

        logger.info(f"Successfully extracted video URL: {video_url}")
        return video_url

    except ValueError:
        raise
    except Exception as err:
        logger.error(f"Unexpected error extracting LuluVDO video: {err}")
        raise ValueError(f"Failed to extract video from LuluVDO: {err}") from err


def validate_video_url(url: str) -> bool:
    """
    Validate if a video URL is accessible.

    Args:
        url: Video URL to validate

    Returns:
        True if video is accessible, False otherwise
    """
    try:
        response = requests.head(url, timeout=config.DEFAULT_REQUEST_TIMEOUT)
        return response.status_code == 200
    except requests.RequestException:
        return False


def main() -> None:
    """
    Main function for standalone execution.

    Handles command-line execution with proper error handling and logging.
    """
    # Setup logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        # Get URL from command line arguments or user input
        if len(sys.argv) > 1:
            url = sys.argv[1]
        else:
            url = input("Enter LuluVDO Link: ").strip()

        if not url:
            print("No URL provided.")
            sys.exit(1)

        # Extract video URL
        video_url = get_direct_link_from_luluvdo(url)
        print(f"Direct video URL: {video_url}")

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)
    except ValueError as err:
        print(f"Error: {err}")
        logger.error(f"LuluVDO extraction error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        logger.error(f"Unexpected error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
