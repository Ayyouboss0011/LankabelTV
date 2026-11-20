import curses
import logging
import os
import sys
import struct

if sys.platform == "win32":
    import winfcntl as fcntl

    # termios existiert nicht unter Windows, definiere TIOCGWINSZ als None
    class MockTermios:
        TIOCGWINSZ = None

    termios = MockTermios()
else:
    import fcntl
    import termios
from typing import Dict, List, Optional, Tuple, Any

import urllib3

# Fix for Python 3.14+ buffer overflow in npyscreen
# The issue is that struct.unpack('hh', ...) expects exactly 4 bytes
# but TIOCGWINSZ returns 8 bytes on newer Python versions
# This must be applied BEFORE npyscreen is imported
if sys.version_info >= (3, 14):
    # Monkey-patch before import
    import npyscreen.proto_fm_screen_area as _npyscreen_area

    def _patched_max_physical(self):
        """Patched version of _max_physical to handle Python 3.14+ terminal size"""
        try:
            # Try to get terminal size using ioctl
            # Use 8 bytes buffer to accommodate both old and new behavior
            result = fcntl.ioctl(sys.stderr.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
            # Unpack only the first 4 bytes (2 shorts for rows and columns)
            mxy, mxx = struct.unpack("hh", result[:4])
            return mxy - 1, mxx - 1
        except (OSError, ValueError, AttributeError):
            # Fallback to curses method
            try:
                mxy, mxx = curses.LINES, curses.COLS
                return mxy - 1, mxx - 1
            except AttributeError:
                # Last resort fallback
                return 24, 80

    # Apply the patch
    _npyscreen_area.ScreenArea._max_physical = _patched_max_physical

import npyscreen

from .models import Anime, Episode
from .config import (
    VERSION,
    SUPPORTED_PROVIDERS,
    DEFAULT_PROVIDER_DOWNLOAD,
    DEFAULT_PROVIDER_WATCH,
    USES_DEFAULT_PROVIDER,
    IS_NEWEST_VERSION,
    ANIWORLD_TO,
)
from . import parser


class CustomTheme(npyscreen.ThemeManager):
    """Custom theme for the npyscreen interface with improved color scheme."""

    default_colors = {
        "DEFAULT": "WHITE_BLACK",
        "FORMDEFAULT": "MAGENTA_BLACK",
        "NO_EDIT": "BLUE_BLACK",
        "STANDOUT": "CYAN_BLACK",
        "CURSOR": "WHITE_BLACK",
        "CURSOR_INVERSE": "BLACK_WHITE",
        "LABEL": "CYAN_BLACK",
        "LABELBOLD": "CYAN_BLACK",
        "CONTROL": "GREEN_BLACK",
        "IMPORTANT": "GREEN_BLACK",
        "SAFE": "GREEN_BLACK",
        "WARNING": "YELLOW_BLACK",
        "DANGER": "RED_BLACK",
        "CRITICAL": "BLACK_RED",
        "GOOD": "GREEN_BLACK",
        "GOODHL": "GREEN_BLACK",
        "VERYGOOD": "BLACK_GREEN",
        "CAUTION": "YELLOW_BLACK",
        "CAUTIONHL": "BLACK_YELLOW",
    }


class SelectionMenu(npyscreen.NPSApp):
    """
    Interactive menu application for anime episode selection and configuration.

    This class provides a comprehensive terminal-based interface for users to
    select anime episodes, configure playback/download options, and manage
    provider and language settings.
    """

    def __init__(self, arguments: Any, slug: str) -> None:
        """
        Initialize the selection menu.

        Args:
            arguments: Parsed command-line arguments
            slug: Anime slug identifier
        """
        super().__init__()
        self.arguments = arguments
        self.slug = slug

        # Initialize anime data
        try:
            self.anime = Anime(
                slug=slug, episode_list=[Episode(slug=slug, season=1, episode=1)]
            )
        except Exception as err:
            logging.error(
                "Failed to initialize anime data for slug '%s': %s", slug, err
            )
            raise

        # UI state
        self.selected_episodes: List[str] = []
        self.episode_dict: Dict[str, str] = {}
        self.form: Optional[npyscreen.Form] = None

        # Widget references
        self.action_selection: Optional[npyscreen.TitleSelectOne] = None
        self.aniskip_selection: Optional[npyscreen.TitleMultiSelect] = None
        self.folder_selection: Optional[npyscreen.TitleFilenameCombo] = None
        self.language_selection: Optional[npyscreen.TitleSelectOne] = None
        self.provider_selection: Optional[npyscreen.TitleSelectOne] = None
        self.episode_selection: Optional[npyscreen.TitleMultiSelect] = None
        self.select_all_button: Optional[npyscreen.ButtonPress] = None

        # Cache for UI calculations
        self._ui_cache: Dict[str, Any] = {}

    def _get_anime_data(self) -> Tuple[List[str], Dict[int, int], int, List[str]]:
        """
        Extract anime data for UI population.

        Returns:
            Tuple of (available_languages, season_episode_count,
            movie_episode_count, available_providers)
        """
        try:
            anime_data = self.anime[0]

            # ensure episode details are filled
            anime_data.auto_fill_details()

            available_languages = anime_data.language_name
            season_episode_count = anime_data.season_episode_count
            movie_episode_count = anime_data.movie_episode_count
            available_providers = anime_data.provider_name

            return (
                available_languages,
                season_episode_count,
                movie_episode_count,
                available_providers,
            )
        except (IndexError, AttributeError) as err:
            logging.error("Failed to extract anime data: %s", err)
            raise ValueError("Invalid anime data structure") from err

    def _filter_supported_providers(self, available_providers: List[str]) -> List[str]:
        """
        Filter available providers to only include supported ones.

        Args:
            available_providers: List of all available providers

        Returns:
            List of supported providers
        """
        supported_providers = [
            provider
            for provider in available_providers
            if provider in SUPPORTED_PROVIDERS
        ]

        if not supported_providers:
            logging.warning(
                "No supported providers found for anime: %s", self.anime.title
            )
            # Fallback to first supported provider
            supported_providers = list(SUPPORTED_PROVIDERS)[:1]

        return supported_providers

    def _build_episode_dict(
        self, season_episode_count: Dict[int, int], movie_episode_count: int
    ) -> Dict[str, str]:
        """
        Build episode dictionary mapping URLs to formatted names.

        Args:
            season_episode_count: Dictionary of season -> episode count
            movie_episode_count: Number of movies available

        Returns:
            Dictionary mapping episode URLs to formatted names
        """
        episode_dict = {}

        # Add season episodes
        for season, episodes in season_episode_count.items():
            for episode in range(1, episodes + 1):
                link_formatted = (
                    f"{self.anime.title} - Season {season} - Episode {episode}"
                )
                link = (
                    f"{ANIWORLD_TO}/anime/stream/{self.anime.slug}/"
                    f"staffel-{season}/episode-{episode}"
                )
                episode_dict[link] = link_formatted

        # Add movie episodes
        for episode in range(1, movie_episode_count + 1):
            movie_link_formatted = f"{self.anime.title} - Movie {episode}"
            movie_link = (
                f"{ANIWORLD_TO}/anime/stream/{self.anime.slug}/filme/film-{episode}"
            )
            episode_dict[movie_link] = movie_link_formatted

        return episode_dict

    def _calculate_layout(
        self, available_languages: List[str], supported_providers: List[str]
    ) -> Tuple[int, int]:
        """
        Calculate optimal layout dimensions for the UI.

        Args:
            available_languages: List of available languages
            supported_providers: List of supported providers

        Returns:
            Tuple of (max_episode_height, terminal_height)
        """
        try:
            terminal_height = os.get_terminal_size().lines
        except OSError:
            terminal_height = 24  # Fallback for environments without proper terminal

        # Calculate reserved height for all widgets
        total_reserved_height = (
            3
            + 2
            + 2
            + 2
            + max(2, len(available_languages))
            + max(2, len(supported_providers))
            + 5
        )

        max_episode_height = max(3, terminal_height - total_reserved_height)

        return max_episode_height, terminal_height

    def _create_form(self) -> npyscreen.Form:
        """
        Create and configure the main form.

        Returns:
            Configured npyscreen Form
        """
        npyscreen.setTheme(CustomTheme)
        form_title = (
            f"Welcome to LankabelTV v.{VERSION}"
            f"{' (Update Available)' if not IS_NEWEST_VERSION else ''}"
        )

        return npyscreen.Form(name=form_title)

    def _create_action_widget(self, form: npyscreen.Form) -> npyscreen.TitleSelectOne:
        """Create the action selection widget."""
        actions = ["Watch", "Download", "Syncplay"]
        default_index = 0

        try:
            default_index = actions.index(self.arguments.action)
        except (ValueError, AttributeError):
            logging.debug("Using default action index")

        return form.add(
            npyscreen.TitleSelectOne,
            max_height=3,
            value=[default_index],
            name="Action",
            values=actions,
            scroll_exit=True,
        )

    def _create_aniskip_widget(
        self, form: npyscreen.Form, rely: int
    ) -> npyscreen.TitleMultiSelect:
        """Create the aniskip selection widget."""
        return form.add(
            npyscreen.TitleMultiSelect,
            max_height=2,
            name="Aniskip",
            values=["Enabled"],
            scroll_exit=True,
            rely=rely,
        )

    def _create_folder_widget(
        self, form: npyscreen.Form, rely: int
    ) -> npyscreen.TitleFilenameCombo:
        """Create the folder selection widget."""
        default_path = getattr(self.arguments, "output_dir", "")

        return form.add(
            npyscreen.TitleFilenameCombo,
            max_height=2,
            name="Save Location",
            rely=rely,
            value=default_path,
        )

    def _create_language_widget(
        self, form: npyscreen.Form, available_languages: List[str], rely: int
    ) -> npyscreen.TitleSelectOne:
        """Create the language selection widget."""
        default_index = 0

        try:
            if self.arguments.language in available_languages:
                default_index = available_languages.index(self.arguments.language)
        except (AttributeError, ValueError):
            logging.debug("Using default language index")

        return form.add(
            npyscreen.TitleSelectOne,
            max_height=max(2, len(available_languages)),
            value=[default_index],
            name="Language",
            values=available_languages,
            scroll_exit=True,
            rely=rely,
        )

    def _create_provider_widget(
        self, form: npyscreen.Form, supported_providers: List[str], rely: int
    ) -> npyscreen.TitleSelectOne:
        """Create the provider selection widget."""
        default_index = 0

        try:
            if self.arguments.provider in supported_providers:
                default_index = supported_providers.index(self.arguments.provider)
        except (AttributeError, ValueError):
            logging.debug("Using default provider index")

        return form.add(
            npyscreen.TitleSelectOne,
            max_height=max(2, len(supported_providers)),
            value=[default_index],
            name="Provider",
            values=supported_providers,
            scroll_exit=True,
            rely=rely,
        )

    def _create_episode_widget(
        self,
        form: npyscreen.Form,
        available_episodes: List[str],
        max_episode_height: int,
        rely: int,
    ) -> npyscreen.TitleMultiSelect:
        """Create the episode selection widget."""
        return form.add(
            npyscreen.TitleMultiSelect,
            max_height=max_episode_height,
            name="Episode",
            values=available_episodes,
            scroll_exit=True,
            rely=rely,
        )

    def _create_select_all_button(
        self, form: npyscreen.Form, rely: int
    ) -> npyscreen.ButtonPress:
        """Create the select all button."""
        return form.add(npyscreen.ButtonPress, name="Select All", rely=rely)

    def _create_toggle_select_all_handler(
        self, available_episodes: List[str], form: npyscreen.Form
    ) -> callable:
        """Create the toggle select all handler function."""

        def toggle_select_all():
            try:
                if len(self.episode_selection.value) == len(available_episodes):
                    self.episode_selection.value = []
                    self.selected_episodes = []
                    self.select_all_button.name = "Select All"
                else:
                    self.episode_selection.value = list(range(len(available_episodes)))
                    self.selected_episodes = list(self.episode_dict.keys())
                    self.select_all_button.name = "Deselect All"
                form.display()
            except Exception as err:
                logging.error("Error in toggle_select_all: %s", err)

        return toggle_select_all

    def _create_update_visibility_handler(
        self, supported_providers: List[str], form: npyscreen.Form
    ) -> callable:
        """Create the update visibility handler function."""

        def update_visibility():
            try:
                selected_objects = self.action_selection.get_selected_objects()
                if not selected_objects:
                    return

                selected_action = selected_objects[0]

                if selected_action in ["Watch", "Syncplay"]:
                    self.folder_selection.hidden = True
                    self.aniskip_selection.hidden = False

                    if USES_DEFAULT_PROVIDER:
                        provider_index = self._get_provider_index(
                            supported_providers, DEFAULT_PROVIDER_WATCH
                        )
                        if self.provider_selection.value != [provider_index]:
                            self.provider_selection.value = [provider_index]
                else:
                    self.folder_selection.hidden = False
                    self.aniskip_selection.hidden = True

                    if USES_DEFAULT_PROVIDER:
                        provider_index = self._get_provider_index(
                            supported_providers, DEFAULT_PROVIDER_DOWNLOAD
                        )
                        if self.provider_selection.value != [provider_index]:
                            self.provider_selection.value = [provider_index]

                form.display()
            except Exception as err:
                logging.error("Error in update_visibility: %s", err)

        return update_visibility

    def _get_provider_index(
        self, supported_providers: List[str], default_provider: str
    ) -> int:
        """Get the index of the default provider in the supported providers list."""
        try:
            return supported_providers.index(default_provider)
        except ValueError:
            return 0

    def main(self) -> None:
        """
        Main method to create and display the interactive menu.

        This method orchestrates the creation of all UI widgets and sets up
        the event handlers for user interactions.
        """
        try:
            # Extract anime data
            (
                available_languages,
                season_episode_count,
                movie_episode_count,
                available_providers,
            ) = self._get_anime_data()

            # Filter supported providers
            supported_providers = self._filter_supported_providers(available_providers)

            # Build episode dictionary
            self.episode_dict = self._build_episode_dict(
                season_episode_count, movie_episode_count
            )
            available_episodes = list(self.episode_dict.values())

            # Calculate layout
            max_episode_height, _ = self._calculate_layout(
                available_languages, supported_providers
            )

            # Create form
            form = self._create_form()
            self.form = form

            # Create widgets
            self.action_selection = self._create_action_widget(form)

            action_rely = self.action_selection.rely + self.action_selection.height + 1
            self.aniskip_selection = self._create_aniskip_widget(form, action_rely)
            self.folder_selection = self._create_folder_widget(form, action_rely)

            language_rely = self.aniskip_selection.rely + self.aniskip_selection.height
            self.language_selection = self._create_language_widget(
                form, available_languages, language_rely
            )

            provider_rely = (
                self.language_selection.rely + self.language_selection.height + 1
            )
            self.provider_selection = self._create_provider_widget(
                form, supported_providers, provider_rely
            )

            episode_rely = (
                self.provider_selection.rely + self.provider_selection.height + 1
            )
            self.episode_selection = self._create_episode_widget(
                form, available_episodes, max_episode_height, episode_rely
            )

            button_rely = (
                self.episode_selection.rely + self.episode_selection.height + 1
            )
            self.select_all_button = self._create_select_all_button(form, button_rely)

            # Set up event handlers
            toggle_handler = self._create_toggle_select_all_handler(
                available_episodes, form
            )
            self.select_all_button.whenPressed = toggle_handler

            update_handler = self._create_update_visibility_handler(
                supported_providers, form
            )
            self.action_selection.when_value_edited = update_handler

            self.episode_selection.when_value_edited = self.on_ok

            # Initialize visibility
            update_handler()

            # Start the form
            form.edit()

        except Exception as err:
            logging.error("Error in main menu setup: %s", err)
            raise

    def on_ok(self) -> None:
        """
        Handle episode selection updates.

        This method is called when the user changes their episode selection
        and updates the internal list of selected episodes.
        """
        try:
            selected_link_formatted = (
                self.episode_selection.get_selected_objects() or []
            )

            self.selected_episodes = [
                link
                for link, name in self.episode_dict.items()
                if name in selected_link_formatted
            ]

            logging.debug(
                "Updated selected episodes: %d items", len(self.selected_episodes)
            )

        except Exception as err:
            logging.error("Error updating selected episodes: %s", err)
            self.selected_episodes = []

    def _get_selected_values_safely(self) -> Tuple[str, str, str, str, bool]:
        """
        Safely extract selected values from UI widgets.

        Returns:
            Tuple of (action, language, provider, output_dir, aniskip)
        """
        try:
            selected_action = self.action_selection.get_selected_objects()[0]
        except (IndexError, AttributeError):
            selected_action = "Watch"

        try:
            selected_language = self.language_selection.get_selected_objects()[0]
        except (IndexError, AttributeError):
            selected_language = "German Sub"

        try:
            selected_provider = self.provider_selection.get_selected_objects()[0]
        except (IndexError, AttributeError):
            selected_provider = "VOE"

        try:
            output_dir = self.folder_selection.value or ""
        except AttributeError:
            output_dir = ""

        try:
            selected_aniskip = bool(self.aniskip_selection.value)
        except AttributeError:
            selected_aniskip = False

        return (
            selected_action,
            selected_language,
            selected_provider,
            output_dir,
            selected_aniskip,
        )

    def _create_episode_list(
        self, selected_language: str, selected_provider: str
    ) -> List[Episode]:
        """
        Create episode list from selected episodes.

        Args:
            selected_language: Selected language option
            selected_provider: Selected provider option

        Returns:
            List of Episode objects
        """
        return [
            Episode(
                slug=self.anime.slug,
                link=link,
                _selected_language=selected_language,
                _selected_provider=selected_provider,
            )
            for link in self.selected_episodes
        ]

    def _log_selected_values(
        self,
        selected_action: str,
        selected_language: str,
        selected_provider: str,
        output_dir: str,
        selected_aniskip: bool,
    ) -> None:
        """
        Log the selected values for debugging purposes.

        Args:
            selected_action: Selected action (Watch/Download/Syncplay)
            selected_language: Selected language
            selected_provider: Selected provider
            output_dir: Output directory for downloads
            selected_aniskip: Whether aniskip is enabled
        """
        log_message = f"Selected Values:\nSelected Action: {selected_action}\n"

        if selected_action == "Watch":
            log_message += f"Selected Aniskip: {selected_aniskip}\n"
        elif selected_action == "Download":
            log_message += f"Selected Output Directory: {output_dir}\n"

        log_message += (
            f"Selected Language: {selected_language}\n"
            f"Selected Provider: {selected_provider}\n"
            f"Selected Episodes: {len(self.selected_episodes)} items\n"
        )

        logging.debug(log_message)

    def get_selected_values(self) -> Anime:
        """
        Get the selected values from the UI and return as an Anime object.

        Returns:
            Anime object with selected configuration and episodes

        Raises:
            RuntimeError: If there's an error creating the Anime object
        """
        try:
            # Extract selected values safely
            (
                selected_action,
                selected_language,
                selected_provider,
                output_dir,
                selected_aniskip,
            ) = self._get_selected_values_safely()

            # Update parser arguments
            if hasattr(parser, "arguments"):
                parser.arguments.output_dir = output_dir
                parser.arguments.action = selected_action

            # Log selected values
            self._log_selected_values(
                selected_action,
                selected_language,
                selected_provider,
                output_dir,
                selected_aniskip,
            )

            # Create episode list
            episode_list = self._create_episode_list(
                selected_language, selected_provider
            )

            # Create and return Anime object
            return Anime(
                title=self.anime.title,
                episode_list=episode_list,
                action=selected_action,
                language=selected_language,
                provider=selected_provider,
                aniskip=selected_aniskip,
            )

        except urllib3.exceptions.ReadTimeoutError as err:
            logging.error("Network timeout error: %s", err)
            print("Request timed out. Please try again later or use a VPN.")
            sys.exit(1)
        except Exception as err:
            logging.error("Error getting selected values: %s", err)
            raise RuntimeError(f"Failed to get selected values: {err}") from err


def menu(arguments: Any, slug: str) -> Anime:
    """
    Create and run the interactive menu for episode selection.

    Args:
        arguments: Parsed command-line arguments
        slug: Anime slug identifier

    Returns:
        Anime object with selected configuration and episodes

    Raises:
        KeyboardInterrupt: If user cancels the menu
        RuntimeError: If there's an error creating or running the menu
    """
    try:
        app = SelectionMenu(arguments=arguments, slug=slug)
        app.run()
        return app.get_selected_values()

    except KeyboardInterrupt:
        logging.info("Menu cancelled by user")
        curses.endwin()
        sys.exit(0)
    except Exception as err:
        logging.error("Error in menu: %s", err)
        curses.endwin()
        raise RuntimeError(f"Menu error: {err}") from err
    finally:
        # Ensure terminal is properly restored
        try:
            curses.endwin()
        except Exception:
            pass


if __name__ == "__main__":
    selected_episodes = menu(slug="dan-da-dan", arguments=None)
    print("Selected Episodes:", selected_episodes)
