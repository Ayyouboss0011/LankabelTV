import re
import base64
import binascii
import json
import time
from typing import Optional, Dict, Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ... import config


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# The embed page performs a JavaScript redirect. Match the assignment directly
# instead of blindly taking the first URL in the document.
REDIRECT_ASSIGN_PATTERNS = (
    re.compile(r"window\.location\.href\s*=\s*['\"](?P<url>[^'\"]+)['\"]"),
    re.compile(r"(?:window\.)?location\.replace\(\s*['\"](?P<url>[^'\"]+)['\"]\s*\)"),
    re.compile(r"(?:window\.)?location\.assign\(\s*['\"](?P<url>[^'\"]+)['\"]\s*\)"),
    re.compile(r"location\.href\s*=\s*['\"](?P<url>[^'\"]+)['\"]"),
)
GENERIC_URL_PATTERN = re.compile(r"https?://[^'\"<>\\\s]+")
B64_PATTERN = re.compile(r"var a168c='([^']+)'")
HLS_PATTERN = re.compile(r"'hls': '(?P<hls>[^']+)'")

# Pre-compiled junk parts for replacement
JUNK_PARTS = ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]

# Hosts that show up in player pages but are never the redirect target
IGNORED_URL_HOSTS = (
    "fonts.gstatic.com",
    "fonts.googleapis.com",
    "googletagmanager.com",
    "google-analytics.com",
    "gstatic.com",
    "cloudflare.com",
    "jquery",
)

# Retry delays (seconds) for transient DDoS-Guard challenges
RETRY_DELAYS = (0, 2, 5)

# Persistent session so DDoS-Guard cookies survive between requests
VOE_SESSION = requests.Session()
VOE_SESSION.headers.update(
    {
        "User-Agent": config.RANDOM_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
)


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Redirect handling
# ---------------------------------------------------------------------------


def normalize_redirect_url(raw_url: str, base_url: str) -> Optional[str]:
    """Normalize a redirect target (escaped slashes, relative URLs, ...)."""
    if not raw_url:
        return None

    url = raw_url.strip()
    url = url.replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")

    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(base_url, url)
    if url.startswith("http"):
        return url
    return None


def extract_redirect_url(html: str, base_url: str) -> Optional[str]:
    """
    Extract the redirect target from a VOE embed page.

    Handles JS redirects (``window.location.href``, ``location.replace``), escaped
    slashes (``https:\\/\\/...``) and relative URLs. Falls back to the first
    absolute URL that is not a known static asset host.
    """
    for pattern in REDIRECT_ASSIGN_PATTERNS:
        match = pattern.search(html)
        if match:
            url = normalize_redirect_url(match.group("url"), base_url)
            if url:
                return url

    # Fallback: first absolute URL that is not a known static asset host.
    # Unescape backslashes first so JSON-escaped URLs are found as well.
    unescaped = html.replace("\\/", "/")
    for match in GENERIC_URL_PATTERN.finditer(unescaped):
        url = match.group(0)
        if any(host in url for host in IGNORED_URL_HOSTS):
            continue
        return url

    return None


def _update_voe_referer(redirect_url: str) -> None:
    """Add the mirror host as referer for the downloader (deduplicated)."""
    parts = redirect_url.strip().split("/")
    if len(parts) < 3:
        return

    referer = f'Referer: "{parts[0]}//{parts[2]}/"'
    for headers in (
        config.PROVIDER_HEADERS_D.setdefault("VOE", []),
        config.PROVIDER_HEADERS_W.setdefault("VOE", []),
    ):
        if referer not in headers:
            headers.append(referer)


def _is_voe_host(url: str) -> bool:
    return "voe.sx" in (urlparse(url).netloc or "").lower()


def _fetch_redirect_page(embeded_voe_link: str) -> tuple:
    """
    Fetch the VOE embed page.

    Returns a tuple ``(redirect_url, html_or_none)``. ``html_or_none`` is set
    when the request already landed on the mirror/player page.
    """
    last_error: Optional[Exception] = None

    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            response = VOE_SESSION.get(
                embeded_voe_link,
                timeout=config.DEFAULT_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()

            # Already redirected to the mirror/player page via HTTP
            if response.url and not _is_voe_host(response.url):
                return response.url, response.text

            redirect_url = extract_redirect_url(response.text, response.url)
            if redirect_url:
                return redirect_url, None

            last_error = ValueError("No redirect URL found in VOE response.")
        except requests.RequestException as err:
            last_error = err

    raise last_error or ValueError("No redirect URL found in VOE response.")


def _fetch_mirror_html(redirect_url: str) -> str:
    """Fetch the mirror/player page with retries."""
    last_error: Optional[Exception] = None

    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            response = VOE_SESSION.get(
                redirect_url,
                timeout=config.DEFAULT_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as err:
            last_error = err

    raise last_error or ValueError("Failed to follow redirect.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
        redirect_url, html = _fetch_redirect_page(embeded_voe_link)
        _update_voe_referer(redirect_url)

        if html is None:
            html = _fetch_mirror_html(redirect_url)

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
        redirect_url, _ = _fetch_redirect_page(embeded_voe_link)
        image_url = f"{redirect_url.replace('/e/', '/cache/')}_storyboard_L2.jpg"

        # Check if the preview image is actually reachable
        try:
            head_response = VOE_SESSION.head(
                image_url,
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
