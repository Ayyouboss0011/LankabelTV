import re
import json
import sys
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

import requests

from ...config import DEFAULT_REQUEST_TIMEOUT

# Constants
VIDEO_MANIFEST_PATTERN = r"^.*videos_manifest.*$"
SUPPORTED_DOMAINS = ["hanime.tv"]
MAX_RETRY_ATTEMPTS = 3

# Setup module logger
logger = logging.getLogger(__name__)


def _make_request(url: str, retry_count: int = 0) -> requests.Response:
    """
    Make HTTP request with error handling and retry logic.

    Args:
        url: URL to request
        retry_count: Current retry attempt

    Returns:
        HTTP response object

    Raises:
        ValueError: If request fails after retries
    """
    try:
        logger.debug(f"Making request to: {url} (attempt {retry_count + 1})")
        response = requests.get(
            url,
            timeout=DEFAULT_REQUEST_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        response.raise_for_status()
        return response

    except requests.RequestException as err:
        logger.error(f"Request failed for {url} (attempt {retry_count + 1}): {err}")

        if retry_count < MAX_RETRY_ATTEMPTS - 1:
            logger.info(f"Retrying request to {url}")
            return _make_request(url, retry_count + 1)

        raise ValueError(
            f"Failed to fetch URL after {MAX_RETRY_ATTEMPTS} attempts: {err}"
        ) from err


def _extract_json_from_line(line: str) -> Dict[str, Any]:
    """
    Extract JSON data from a line containing video manifest.

    Args:
        line: Text line containing JSON data

    Returns:
        Parsed JSON data as dictionary

    Raises:
        ValueError: If JSON cannot be extracted or parsed
    """
    try:
        start_index = line.find("{")
        end_index = line.rfind("}") + 1

        if start_index == -1 or end_index == 0:
            raise ValueError("No JSON data found in the line")

        json_str = line[start_index:end_index]
        if not json_str.strip():
            raise ValueError("Empty JSON string")

        return json.loads(json_str)

    except (ValueError, json.JSONDecodeError) as err:
        logger.error(f"Failed to parse JSON from line: {err}")
        raise ValueError(f"Invalid JSON data in video manifest: {err}") from err


def _parse_video_info(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse video information from extracted data.

    Args:
        data: Raw video data dictionary

    Returns:
        Dictionary containing video name and streams

    Raises:
        ValueError: If video data structure is invalid
    """
    try:
        video_info = data["state"]["data"]["video"]
        name = video_info["hentai_video"]["name"]
        streams = video_info["videos_manifest"]["servers"][0]["streams"]

        if not isinstance(streams, list):
            raise ValueError("Streams data is not a list")

        if not streams:
            raise ValueError("No streams found")

        return {"name": name, "streams": streams}

    except (KeyError, IndexError, TypeError) as err:
        logger.error(f"Failed to parse video info: {err}")
        raise ValueError(f"Invalid video data structure: {err}") from err


def _validate_url(url: str) -> str:
    """
    Validate and clean the URL.

    Args:
        url: URL to validate

    Returns:
        Validated and cleaned URL

    Raises:
        ValueError: If URL is invalid
    """
    if not url:
        raise ValueError("URL cannot be empty")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL format - must start with http:// or https://")

    # Parse URL to validate domain
    try:
        parsed_url = urlparse(url)
        if not parsed_url.netloc:
            raise ValueError("Invalid URL format - missing domain")

        # Check if domain is supported
        domain = parsed_url.netloc.lower()
        if not any(
            supported_domain in domain for supported_domain in SUPPORTED_DOMAINS
        ):
            raise ValueError(f"Unsupported domain: {domain}")

    except Exception as err:
        raise ValueError(f"Invalid URL format: {err}") from err

    return url


def _get_url_from_input() -> str:
    """
    Get URL from command line arguments or user input.

    Returns:
        URL string

    Raises:
        ValueError: If no URL provided
    """
    if len(sys.argv) > 1:
        return sys.argv[1]

    try:
        url = input("Please enter the hanime.tv video URL: ").strip()
        if not url:
            raise ValueError("No URL provided")
        return url
    except (EOFError, KeyboardInterrupt) as err:
        raise ValueError("No URL provided") from err


def _display_stream_info(stream: Dict[str, Any], index: int) -> None:
    """
    Display information for a single stream.

    Args:
        stream: Stream information dictionary
        index: Stream index for display
    """
    premium_tag = "(Premium)" if not stream.get("is_guest_allowed", True) else ""
    width = stream.get("width", "Unknown")
    height = stream.get("height", "Unknown")
    filesize = stream.get("filesize_mbs", "Unknown")

    print(f"{index}. {width}x{height}\t({filesize}MB) {premium_tag}")


def _get_stream_selection(streams: List[Dict[str, Any]]) -> int:
    """
    Get user's stream selection with validation.

    Args:
        streams: List of available streams

    Returns:
        Selected stream index

    Raises:
        KeyboardInterrupt: If user cancels selection
        ValueError: If invalid selection
    """
    while True:
        try:
            selection = input("Select a stream: ").strip()
            if not selection:
                print("Please enter a selection.")
                continue

            selected_index = int(selection) - 1

            if 0 <= selected_index < len(streams):
                return selected_index
            else:
                print(f"Invalid selection. Please choose between 1 and {len(streams)}.")

        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            logger.info("User cancelled selection")
            raise


def fetch_page_content(url: str) -> str:
    """
    Fetch page content from URL.

    Args:
        url: URL to fetch content from

    Returns:
        Page content as string

    Raises:
        ValueError: If request fails
    """
    logger.debug(f"Fetching page content from: {url}")
    response = _make_request(url)

    if not response.text:
        raise ValueError("Empty response received")

    return response.text


def extract_video_data(page_content: str) -> Dict[str, Any]:
    """
    Extract video data from page content.

    Args:
        page_content: HTML content of the page

    Returns:
        Dictionary containing video data

    Raises:
        ValueError: If video manifest cannot be extracted
    """
    logger.debug("Extracting video data from page content")

    if not page_content:
        raise ValueError("Empty page content")

    match = re.search(VIDEO_MANIFEST_PATTERN, page_content, re.MULTILINE)
    if not match:
        raise ValueError("Failed to extract video manifest from the response")

    return _extract_json_from_line(match.group(0))


def get_streams(url: str) -> Dict[str, Any]:
    """
    Get available streams for a video URL.

    Args:
        url: Video URL

    Returns:
        Dictionary containing video name and available streams

    Raises:
        ValueError: If URL is invalid
        ValueError: If request fails
        ValueError: If video data cannot be extracted
    """
    validated_url = _validate_url(url)
    logger.info(f"Getting streams for: {validated_url}")

    try:
        page_content = fetch_page_content(validated_url)
        data = extract_video_data(page_content)
        video_info = _parse_video_info(data)

        logger.info(
            f"Found {len(video_info['streams'])} streams for video: {video_info['name']}"
        )
        return video_info

    except (ValueError,):
        raise
    except Exception as err:
        logger.error(f"Unexpected error getting streams: {err}")
        raise ValueError(f"Failed to get streams: {err}") from err


def display_streams(streams: List[Dict[str, Any]]) -> None:
    """
    Display available streams in a formatted way.

    Args:
        streams: List of stream dictionaries
    """
    if not streams:
        print("No streams available.")
        return

    print("Available qualities:")
    for i, stream in enumerate(streams, 1):
        _display_stream_info(stream, i)


def get_user_selection(streams: List[Dict[str, Any]]) -> Optional[int]:
    """
    Get user's stream selection (legacy function for compatibility).

    Args:
        streams: List of available streams

    Returns:
        Selected stream index or None if invalid
    """
    try:
        return _get_stream_selection(streams)
    except KeyboardInterrupt:
        return None


def get_direct_link_from_hanime(url: Optional[str] = None) -> Optional[str]:
    """
    Get direct link from hanime.tv URL with interactive selection.

    Args:
        url: Optional hanime.tv URL. If None, will prompt for input.

    Returns:
        Selected stream URL or None if cancelled

    Raises:
        ValueError: For various extraction errors
    """
    try:
        # Get URL from parameter, command line, or user input
        if url is None:
            url = _get_url_from_input()

        if not url:
            logger.warning("No URL provided")
            return None

        # Get video data and streams
        video_data = get_streams(url)

        # Display video information
        print(f"Video: {video_data['name']}")
        print("*" * 40)
        display_streams(video_data["streams"])

        # Get user selection
        try:
            selected_index = _get_stream_selection(video_data["streams"])
            selected_stream = video_data["streams"][selected_index]

            if "url" not in selected_stream:
                raise ValueError("Selected stream has no URL")

            stream_url = selected_stream["url"]

            if not stream_url:
                raise ValueError("Selected stream URL is empty")

            print(f"M3U8 URL: {stream_url}")
            logger.info(f"Successfully extracted stream URL: {stream_url}")
            return stream_url

        except KeyboardInterrupt:
            print("\nSelection cancelled.")
            logger.info("User cancelled stream selection")
            return None

    except ValueError as err:
        print(f"Error: {err}")
        logger.error(f"Hanime extraction error: {err}")
        return None
    except Exception as err:
        print(f"Unexpected error: {err}")
        logger.error(f"Unexpected error in get_direct_link_from_hanime: {err}")
        return None


def validate_stream_url(url: str) -> bool:
    """
    Validate if a stream URL is accessible.

    Args:
        url: Stream URL to validate

    Returns:
        True if stream is accessible, False otherwise
    """
    try:
        response = requests.head(url, timeout=DEFAULT_REQUEST_TIMEOUT)
        return response.status_code == 200
    except requests.RequestException:
        return False


def get_stream_info(url: str) -> Dict[str, Any]:
    """
    Get comprehensive stream information without user interaction.

    Args:
        url: Video URL

    Returns:
        Dictionary containing video name, streams, and metadata

    Raises:
        ValueError: For various extraction errors
    """
    try:
        video_data = get_streams(url)

        # Add additional metadata
        video_data["total_streams"] = len(video_data["streams"])
        video_data["has_premium_streams"] = any(
            not stream.get("is_guest_allowed", True) for stream in video_data["streams"]
        )

        return video_data

    except Exception as err:
        logger.error(f"Failed to get stream info: {err}")
        raise ValueError(f"Failed to get stream info: {err}") from err


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
        result = get_direct_link_from_hanime()
        if result:
            print(f"Final URL: {result}")
        else:
            print("No URL obtained.")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)
    except ValueError as err:
        print(f"Hanime error: {err}")
        logger.error(f"Hanime error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        logger.error(f"Unexpected error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
