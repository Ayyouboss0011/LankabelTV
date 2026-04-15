import re
import base64
import binascii
import json
from typing import Optional, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import requests
from bs4 import BeautifulSoup

from ... import config


# Compile regex patterns once for better performance
REDIRECT_PATTERN = re.compile(r"https?://[^'\"<>]+")
B64_PATTERN = re.compile(r"var a168c='([^']+)'")
HLS_PATTERN = re.compile(r"'hls': '(?P<hls>[^']+)'")

# Pre-compiled junk parts for replacement
JUNK_PARTS = ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]


def shift_letters(input_str: str) -> str:
    """Apply ROT13 cipher to alphabetic characters."""
    result = []
    for c in input_str:
        code = ord(c)
        if 65 <= code <= 90:  # Uppercase A-Z
            code = (code - 65 + 13) % 26 + 65
        elif 97 <= code <= 122:  # Lowercase a-z
            code = (code - 97 + 13) % 26 + 97
        result.append(chr(code))
    return "".join(result)


def replace_junk(input_str: str) -> str:
    """Replace junk patterns with underscores."""
    for part in JUNK_PARTS:
        input_str = input_str.replace(part, "_")
    return input_str


def shift_back(s: str, n: int) -> str:
    """Shift characters back by n positions."""
    return "".join(chr(ord(c) - n) for c in s)


def decode_voe_string(encoded: str) -> Dict[str, Any]:
    """
    Decode VOE encoded string through multiple transformation steps.

    Args:
        encoded: The encoded string to decode

    Returns:
        Decoded JSON object as dictionary

    Raises:
        ValueError: If decoding fails at any step
    """
    try:
        step1 = shift_letters(encoded)
        step2 = replace_junk(step1).replace("_", "")
        step3 = base64.b64decode(step2).decode()
        step4 = shift_back(step3, 3)
        step5 = base64.b64decode(step4[::-1]).decode()
        return json.loads(step5)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as err:
        raise ValueError(f"Failed to decode VOE string: {err}") from err


def extract_voe_from_script(html: str) -> Optional[str]:
    """
    Extract VOE source from script tag in HTML.

    Args:
        html: HTML content to parse

    Returns:
        Video source URL or None if not found
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", type="application/json")
        if script and script.text:
            decoded = decode_voe_string(script.text[2:-2])
            return decoded.get("source")
    except (ValueError, KeyError, AttributeError):
        pass
    return None


def get_direct_link_from_voe(embeded_voe_link: str) -> str:
    """
    Extract direct video link from VOE embed page.

    Args:
        embeded_voe_link: URL of the VOE embed page

    Returns:
        Direct video URL

    Raises:
        ValueError: If no direct link is found or processing fails
        requests.RequestException: If the request fails
    """
    try:
        # Initial request to get redirect URL
        response = requests.get(
            embeded_voe_link,
            headers={"User-Agent": config.RANDOM_USER_AGENT},
            timeout=config.DEFAULT_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        # Find redirect URL using compiled regex
        redirect_match = REDIRECT_PATTERN.search(response.text)
        if not redirect_match:
            raise ValueError("No redirect URL found in VOE response.")

        redirect_url = redirect_match.group(0)

        # Update provider headers with referer
        parts = redirect_url.strip().split("/")
        if len(parts) >= 3:
            referer = f'Referer: "{parts[0]}//{parts[2]}/"'
            config.PROVIDER_HEADERS_D["VOE"].append(referer)
            config.PROVIDER_HEADERS_W["VOE"].append(referer)

        # Follow redirect and get final HTML
        try:
            with urlopen(
                Request(redirect_url, headers={"User-Agent": config.RANDOM_USER_AGENT}),
                timeout=config.DEFAULT_REQUEST_TIMEOUT,
            ) as resp:
                html = resp.read().decode()
        except (HTTPError, URLError, TimeoutError) as err:
            raise ValueError(f"Failed to follow redirect: {err}") from err

        # Try multiple extraction methods

        # Method 1: Extract from script tag
        extracted = extract_voe_from_script(html)
        if extracted:
            return extracted

        # Method 2: Extract from base64 encoded variable
        b64_match = B64_PATTERN.search(html)
        if b64_match:
            try:
                decoded = base64.b64decode(b64_match.group(1)).decode()[::-1]
                source = json.loads(decoded).get("source")
                if source:
                    return source
            except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
                pass  # Continue to next method

        # Method 3: Extract HLS source
        hls_match = HLS_PATTERN.search(html)
        if hls_match:
            try:
                return base64.b64decode(hls_match.group("hls")).decode()
            except (binascii.Error, UnicodeDecodeError):
                pass  # Continue to final error

        raise ValueError("No video source found using any extraction method.")

    except requests.RequestException as err:
        raise ValueError(f"Failed to fetch VOE page: {err}") from err
    except Exception as err:
        raise ValueError(
            f"Unable to process this VOE link: {err}\n\n"
            "Try using a different provider for now.\n"
            "If this issue persists and hasn't been reported yet, please consider creating a new issue."
        ) from err


def get_preview_image_link_from_voe(embeded_voe_link: str) -> str:
    """
    Try to extract the preview image from a VOE embed page.

    Args:
        embeded_voe_link: URL of the VOE embed page

    Returns:
        Direct image URL of the preview frame

    Raises:
        ValueError: If no redirect or image URL is found
        requests.RequestException: If any request fails
    """
    try:
        # Initial request to get redirect URL
        response = requests.get(
            embeded_voe_link,
            headers={"User-Agent": config.RANDOM_USER_AGENT},
            timeout=config.DEFAULT_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        # Find redirect URL using compiled regex
        redirect_match = REDIRECT_PATTERN.search(response.text)
        if not redirect_match:
            raise ValueError("No redirect URL found in VOE response.")

        redirect_url = redirect_match.group(0)
        image_url = f"{redirect_url.replace('/e/', '/cache/')}_storyboard_L2.jpg"

        # Check if the preview image is actually reachable
        try:
            head_response = requests.head(
                image_url,
                headers={"User-Agent": config.RANDOM_USER_AGENT},
                timeout=config.DEFAULT_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            head_response.raise_for_status()
            if "image" in head_response.headers.get("Content-Type", ""):
                return image_url
        except requests.RequestException as err:
            raise ValueError(f"Preview image not available or invalid: {err}") from err

        raise ValueError("Preview image not found or not reachable.")

    except requests.RequestException as err:
        raise ValueError(f"Failed to fetch VOE page: {err}") from err
    except Exception as err:
        raise ValueError(
            f"Unable to process this VOE link: {err}\n\n"
            "Try using a different provider for now.\n"
            "If this issue persists and hasn't been reported yet, please consider creating a new issue."
        ) from err


if __name__ == "__main__":
    link = input("Enter VOE Link: ")
    print(get_direct_link_from_voe(link))
    print(get_preview_image_link_from_voe(link))
