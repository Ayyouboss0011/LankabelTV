import os
import platform
import random
import re
from functools import lru_cache
from typing import Dict, List


@lru_cache(maxsize=1)
def _load_ascii_content() -> str:
    """Load ASCII content from file with caching."""
    try:
        ascii_file = os.path.join(os.path.dirname(__file__), "ASCII.txt")
    except ImportError:
        # TODO: untested should happen on nuitka build
        ascii_file = os.path.join(os.path.dirname(__file__), "ASCII.txt")
    with open(ascii_file, encoding="utf-8") as f:
        return f.read()


@lru_cache(maxsize=1)
def _parse_ascii_blocks() -> Dict[str, List[str]]:
    """Parse ASCII content into categorized blocks with caching."""
    content = _load_ascii_content()

    # Find all blocks with their types and names
    pattern = r"=== (banner|art|traceback): (\w+) ===\s*\n([\s\S]*?)(?=^=== (?:banner|art|traceback): |\Z)"
    matches = re.findall(pattern, content, flags=re.MULTILINE)

    blocks = {"banner": [], "art": [], "traceback": [], "all": []}

    for block_type, name, block in matches:
        cleaned_block = block.strip("\n")
        if cleaned_block:
            blocks[block_type].append(cleaned_block)
            blocks["all"].append(cleaned_block)

    return blocks


def is_windows_legacy() -> bool:
    """
    Check if Windows version is legacy (anything before Windows 11).
    Returns False for non-Windows systems.
    """
    if platform.system() != "Windows":
        return False

    try:
        return platform.release() != "11"
    except Exception:
        # If we can't determine the version, assume it's legacy to be safe
        return True


def display_ascii_art() -> str:
    """
    Displays a randomly selected ASCII art from available options.

    On Windows 10 or older, returns the banner (legacy compatibility).
    Otherwise, selects and returns one ASCII art string at random from art blocks.

    Returns:
        str: The selected ASCII art as a string.
    """
    blocks = _parse_ascii_blocks()

    # For legacy Windows, use banner blocks (fallback to first available)
    if platform.system() == "Windows" and is_windows_legacy():
        banner_blocks = blocks["banner"]
        if banner_blocks:
            return random.choice(banner_blocks)
        # Fallback to first available block if no banner
        if blocks["all"]:
            return blocks["all"][0]
        return ""

    # For modern systems, use art blocks
    art_blocks = blocks["art"]
    if art_blocks:
        return random.choice(art_blocks)

    # Fallback to any available block
    if blocks["all"]:
        return random.choice(blocks["all"])

    return ""


def display_banner_art() -> str:
    """
    Returns a randomly selected banner ASCII art.

    Returns:
        str: A randomly selected banner ASCII art string.
    """
    blocks = _parse_ascii_blocks()
    banner_blocks = blocks["banner"]

    if banner_blocks:
        return random.choice(banner_blocks)

    return ""


def display_traceback_art() -> str:
    """
    Returns a randomly selected ASCII art representation of a traceback.

    Returns:
        str: A randomly selected traceback ASCII art string.
    """
    blocks = _parse_ascii_blocks()
    traceback_blocks = blocks["traceback"]

    if traceback_blocks:
        return random.choice(traceback_blocks)

    return ""


if __name__ == "__main__":
    print(display_ascii_art())
