import re
import base64
import logging
import sys
from urllib.parse import urlparse

import requests

from ...config import DEFAULT_REQUEST_TIMEOUT, RANDOM_USER_AGENT

# Constants
SPEEDFILES_PATTERN = re.compile(r'var _0x5opu234 = "(?P<encoded_data>.*?)";')
SERVER_DOWN_INDICATOR = '<span class="inline-block">Web server is down</span>'

# Setup module logger
logger = logging.getLogger(__name__)


def _validate_speedfiles_url(url: str) -> str:
    """
    Validate and clean the SpeedFiles URL.

    Args:
        url: URL to validate

    Returns:
        Validated and cleaned URL

    Raises:
        ValueError: If URL is invalid
    """
    if not url or not url.strip():
        raise ValueError("SpeedFiles URL cannot be empty")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL format - must start with http:// or https://")

    try:
        parsed_url = urlparse(url)
        if not parsed_url.netloc:
            raise ValueError("Invalid URL format - missing domain")
    except Exception as err:
        raise ValueError(f"Invalid URL format: {err}") from err

    return url


def _make_request(url: str) -> requests.Response:
    """
    Make HTTP request with error handling.

    Args:
        url: URL to request

    Returns:
        HTTP response object

    Raises:
        ValueError: If request fails
    """
    try:
        logger.debug(f"Making request to: {url}")
        response = requests.get(
            url,
            timeout=DEFAULT_REQUEST_TIMEOUT,
            headers={"User-Agent": RANDOM_USER_AGENT},
        )
        response.raise_for_status()
        return response

    except requests.RequestException as err:
        logger.error(f"Request failed for {url}: {err}")
        raise ValueError(f"Failed to fetch URL: {err}") from err


def _check_server_status(response_text: str) -> None:
    """
    Check if SpeedFiles server is down.

    Args:
        response_text: HTML response text

    Raises:
        ValueError: If server is down
    """
    if SERVER_DOWN_INDICATOR in response_text:
        raise ValueError(
            "The SpeedFiles server is currently down.\n"
            "Please try again later or choose a different hoster."
        )


def _extract_encoded_data(response_text: str) -> str:
    """
    Extract encoded data from response text.

    Args:
        response_text: HTML response text

    Returns:
        Encoded data string

    Raises:
        ValueError: If encoded data cannot be found
    """
    try:
        match = SPEEDFILES_PATTERN.search(response_text)
        if not match:
            raise ValueError("Pattern not found in the response")

        encoded_data = match.group("encoded_data")
        if not encoded_data:
            raise ValueError("Empty encoded data found")

        logger.debug(f"Extracted encoded data: {encoded_data[:50]}...")
        return encoded_data

    except Exception as err:
        logger.error(f"Failed to extract encoded data: {err}")
        raise ValueError(f"Failed to extract encoded data: {err}") from err


def _decode_speedfiles_data(encoded_data: str) -> str:
    """
    Decode SpeedFiles encoded data using their specific algorithm.

    Args:
        encoded_data: Base64 encoded data from SpeedFiles

    Returns:
        Decoded video URL

    Raises:
        ValueError: If decoding fails
    """
    try:
        logger.debug("Starting SpeedFiles decoding process")

        # Step 1: Base64 decode
        decoded = base64.b64decode(encoded_data).decode()
        logger.debug("Step 1: Base64 decoded")

        # Step 2: Swap case and reverse
        decoded = decoded.swapcase()[::-1]
        logger.debug("Step 2: Swapped case and reversed")

        # Step 3: Base64 decode again and reverse
        decoded = base64.b64decode(decoded).decode()[::-1]
        logger.debug("Step 3: Base64 decoded again and reversed")

        # Step 4: Convert hex to characters
        if len(decoded) % 2 != 0:
            raise ValueError("Invalid hex string length")

        decoded_hex = "".join(
            chr(int(decoded[i : i + 2], 16)) for i in range(0, len(decoded), 2)
        )
        logger.debug("Step 4: Converted hex to characters")

        # Step 5: Shift characters by -3
        shifted = "".join(chr(ord(char) - 3) for char in decoded_hex)
        logger.debug("Step 5: Shifted characters by -3")

        # Step 6: Final base64 decode with swap case and reverse
        result = base64.b64decode(shifted.swapcase()[::-1]).decode()
        logger.debug("Step 6: Final decoding complete")

        if not result:
            raise ValueError("Decoding resulted in empty string")

        logger.info(f"Successfully decoded SpeedFiles URL: {result}")
        return result

    except (base64.binascii.Error, ValueError, UnicodeDecodeError) as err:
        logger.error(f"Decoding failed: {err}")
        raise ValueError(f"Failed to decode SpeedFiles data: {err}") from err
    except Exception as err:
        logger.error(f"Unexpected error during decoding: {err}")
        raise ValueError(f"Unexpected decoding error: {err}") from err


def get_direct_link_from_speedfiles(embeded_speedfiles_link: str) -> str:
    """
    Extract direct video link from SpeedFiles embedded URL.

    Args:
        embeded_speedfiles_link: SpeedFiles embedded URL

    Returns:
        Direct video URL

    Raises:
        ValueError: If extraction fails
    """
    try:
        # Validate input URL
        validated_url = _validate_speedfiles_url(embeded_speedfiles_link)
        logger.info(f"Extracting video from SpeedFiles URL: {validated_url}")

        # Make request to SpeedFiles
        response = _make_request(validated_url)

        # Check if server is down
        _check_server_status(response.text)

        # Extract encoded data
        encoded_data = _extract_encoded_data(response.text)

        # Decode the data
        video_url = _decode_speedfiles_data(encoded_data)

        logger.info(f"Successfully extracted video URL: {video_url}")
        return video_url

    except ValueError:
        raise
    except Exception as err:
        logger.error(f"Unexpected error extracting SpeedFiles video: {err}")
        raise ValueError(f"Failed to extract video from SpeedFiles: {err}") from err


def validate_video_url(url: str) -> bool:
    """
    Validate if a video URL is accessible.

    Args:
        url: Video URL to validate

    Returns:
        True if video is accessible, False otherwise
    """
    try:
        response = requests.head(url, timeout=DEFAULT_REQUEST_TIMEOUT)
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
            url = input("Enter SpeedFiles Link: ").strip()

        if not url:
            print("No URL provided.")
            sys.exit(1)

        # Extract video URL
        video_url = get_direct_link_from_speedfiles(url)
        print(f"Direct video URL: {video_url}")

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(0)
    except ValueError as err:
        print(f"Error: {err}")
        logger.error(f"SpeedFiles extraction error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Unexpected error: {err}")
        logger.error(f"Unexpected error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
