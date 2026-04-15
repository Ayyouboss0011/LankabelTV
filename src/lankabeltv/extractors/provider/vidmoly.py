import re

import requests
from bs4 import BeautifulSoup

from ...config import DEFAULT_REQUEST_TIMEOUT, RANDOM_USER_AGENT


# Compile regex pattern once for better performance
FILE_LINK_PATTERN = re.compile(r'file:\s*"(https?://[^"]+)"')


def get_direct_link_from_vidmoly(embeded_vidmoly_link: str) -> str:
    """
    Extract direct video link from Vidmoly embed page.

    Args:
        embeded_vidmoly_link: URL of the Vidmoly embed page

    Returns:
        Direct video URL

    Raises:
        ValueError: If no direct link is found
        requests.RequestException: If the request fails
    """
    try:
        response = requests.get(
            embeded_vidmoly_link,
            headers={"User-Agent": RANDOM_USER_AGENT},
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )
        response.raise_for_status()  # Raise an exception for bad status codes

        # Use compiled regex to search directly in the HTML content
        match = FILE_LINK_PATTERN.search(response.text)
        if match:
            return match.group(1)

        # Fallback to BeautifulSoup parsing if direct search fails
        soup = BeautifulSoup(response.text, "html.parser")
        scripts = soup.find_all("script", string=True)

        for script in scripts:
            match = FILE_LINK_PATTERN.search(script.string)
            if match:
                return match.group(1)

    except requests.RequestException as err:
        raise ValueError(f"Failed to fetch Vidmoly page: {err}") from err
    except Exception as err:
        raise ValueError(f"Error parsing Vidmoly page: {err}") from err

    raise ValueError("No direct link found in Vidmoly page.")


def get_preview_image_link_from_vidmoly(embeded_vidmoly_link: str) -> str:
    """
    Extract preview image URL from Vidmoly embed page.

    Args:
        embeded_vidmoly_link: URL of the Vidmoly embed page

    Returns:
        Preview image URL

    Raises:
        ValueError: If no preview image is found
        requests.RequestException: If the request fails
    """
    try:
        # Perform initial request to fetch HTML content
        response = requests.get(
            embeded_vidmoly_link,
            headers={"User-Agent": RANDOM_USER_AGENT},
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        html = response.text

        # Search for image URL using regular expression
        match = re.search(r'image\s*:\s*"([^"]+\.jpg)"', html)
        if match:
            return match.group(1)

        # Raise if no match is found
        raise ValueError("No preview image found in Vidmoly page.")

    except requests.RequestException as err:
        raise ValueError(f"Failed to fetch Vidmoly page: {err}") from err
    except Exception as err:
        raise ValueError(f"Error parsing Vidmoly page: {err}") from err


if __name__ == "__main__":
    link = input("Enter Vidmoly Link: ")
    print('Note: --referer "https://vidmoly.to"')
    print(get_direct_link_from_vidmoly(embeded_vidmoly_link=link))
    print(get_preview_image_link_from_vidmoly(embeded_vidmoly_link=link))
