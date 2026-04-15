"""
LankabelTV main entry point.
"""

import sys
import logging
from typing import NoReturn

from .entry import lankabeltv
from .config import VERSION, IS_NEWEST_VERSION


def set_terminal_title() -> None:
    """Set the terminal window title with version and update status."""
    title = f"LankabelTV v.{VERSION}"
    if not IS_NEWEST_VERSION:
        title += " (Update Available)"

    # ANSI escape sequence to set terminal title
    print(f"\033]0;{title}\007", end="", flush=True)


def main() -> NoReturn:
    """
    Main entry point for the LankabelTV application.

    Sets up the terminal title and launches the main application.
    """
    set_terminal_title()
    lankabeltv()
    sys.exit(0)


if __name__ == "__main__":
    main()
