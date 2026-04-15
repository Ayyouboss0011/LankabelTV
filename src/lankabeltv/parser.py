import argparse
import logging
import os
import sys
from typing import List, Optional, Callable

from . import config


def _add_general_arguments(parser: argparse.ArgumentParser) -> None:
    """Add general command-line arguments to the parser."""
    general_opts = parser.add_argument_group("General Options")
    general_opts.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode for detailed logs.",
    )
    general_opts.add_argument(
        "-v", "--version", action="store_true", help="Display version information."
    )


def _add_web_ui_arguments(parser: argparse.ArgumentParser) -> None:
    """Add Web UI related command-line arguments to the parser."""
    web_opts = parser.add_argument_group("Web UI Options")
    web_opts.add_argument(
        "-p",
        "--port",
        type=int,
        default=5001,
        help="Specify the port for the web interface (default: 5001).",
    )
    web_opts.add_argument(
        "-a",
        "--auth",
        action="store_true",
        help="Enable authentication for web interface with user management.",
    )
    web_opts.add_argument(
        "-nb",
        "--no-browser",
        action="store_true",
        help="Disable automatic browser opening.",
    )
    web_opts.add_argument(
        "-e",
        "--expose",
        action="store_true",
        help="Bind web interface to 0.0.0.0 for external access.",
    )


def _handle_version() -> None:
    """Handle version information display."""
    from .ascii_art import display_banner_art, display_ascii_art

    banner = display_banner_art()
    art = display_ascii_art()

    if art == banner:
        art = ""

    version_info = f"LankabelTV v.{config.VERSION}"
    if not config.IS_NEWEST_VERSION:
        version_info += (
            f"\nYour version is outdated.\n"
            f"Please update to the latest version (v.{config.LATEST_VERSION})."
        )
    else:
        version_info += "\nYou are on the latest version."

    if banner:
        print(banner)
    if art:
        print(art)
    print(f"\n{version_info}")
    sys.exit(0)


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments for LankabelTV.

    Returns:
        Parsed command-line arguments
    """
    parser = argparse.ArgumentParser(
        description="LankabelTV Web Interface"
    )

    _add_general_arguments(parser)
    _add_web_ui_arguments(parser)

    args = parser.parse_args()

    if args.version:
        _handle_version()

    # Map new arguments to internal expected names for backward compatibility with app.py
    args.web_ui = True
    args.web_port = args.port
    args.enable_web_auth = args.auth
    # web_expose is now True by default in app.py logic, but we keep the mapping
    args.web_expose = True
    
    # Set these to None/False as they are no longer supported via CLI but might be referenced
    args.slug = None
    args.episode = None
    args.episode_file = None
    args.local_episodes = None
    args.provider_link = None
    args.action = config.DEFAULT_ACTION
    args.language = config.DEFAULT_LANGUAGE
    args.provider = None
    args.keep_watching = False
    args.only_direct_link = False
    args.only_command = False

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    return args


arguments = parse_arguments()


if __name__ == "__main__":
    pass
