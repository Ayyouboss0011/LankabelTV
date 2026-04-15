import json
import html
from urllib.parse import quote
import logging
import re
import time
import random
from typing import List, Dict, Optional, Union
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

import curses
import requests

from .ascii_art import display_ascii_art
from .config import DEFAULT_REQUEST_TIMEOUT, ANIWORLD_TO, S_TO


# Forbidden search patterns (case-insensitive)
FORBIDDEN_SEARCHES = ["boku no piko", "boku no pico", "pico boku", "piko boku"]

def _validate_keyword(keyword: str) -> str:
    """
    Validate and sanitize the search keyword.

    Args:
        keyword: Raw keyword input

    Returns:
        str: Cleaned keyword

    Raises:
        ValueError: If keyword is forbidden or invalid
    """
    if not keyword or not keyword.strip():
        raise ValueError("Search keyword cannot be empty")

    cleaned_keyword = keyword.strip().lower()

    # Check against forbidden search patterns
    for forbidden in FORBIDDEN_SEARCHES:
        if forbidden in cleaned_keyword:
            raise ValueError("Really? This is not on LankabelTV...")

    return keyword.strip()  # Return original case but trimmed


def _get_user_input() -> str:
    """Get search keyword from user input."""
    logging.debug("Prompting user for search.")
    keyword = input("Search for a series: ").strip()
    return _validate_keyword(keyword)


@lru_cache(maxsize=128)
def _cached_search_request(search_url: str, headers_json: str = "{}") -> str:
    """
    Cached HTTP request for search results.

    Args:
        search_url: The URL to fetch data from
        headers_json: JSON string of headers (for caching)

    Returns:
        str: Raw response text
    """
    headers = json.loads(headers_json)
    response = requests.get(search_url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text.strip()


def fetch_anime_list(url: str, headers: Optional[Dict] = None) -> Union[List[Dict], Dict]:
    """
    Fetch and parse anime list from search API.

    Args:
        url: The search API URL
        headers: Optional HTTP headers

    Returns:
        Union[List[Dict], Dict]: List of anime dictionaries or dict for s.to

    Raises:
        ValueError: If unable to fetch or parse anime data
    """
    try:
        headers_json = json.dumps(headers or {})
        clean_text = _cached_search_request(url, headers_json=headers_json)

        # First attempt: direct JSON parsing
        try:
            decoded_data = json.loads(html.unescape(clean_text))
            return decoded_data
        except json.JSONDecodeError:
            # Second attempt: clean problematic characters
            cleaned_text = _clean_json_text(clean_text)
            try:
                decoded_data = json.loads(cleaned_text)
                return decoded_data
            except json.JSONDecodeError as err:
                logging.error("Failed to parse JSON after cleaning: %s", err)
                raise ValueError("Could not parse anime search results") from err

    except requests.RequestException as err:
        logging.error("Failed to fetch anime list: %s", err)
        raise ValueError("Could not fetch anime data from server") from err


def search_anime(
    keyword: Optional[str] = None, only_return: bool = False, site: str = "aniworld.to"
) -> Union[str, List[Dict]]:
    """
    Search for anime on aniworld.to or s.to.

    Args:
        keyword: The search keyword (anime name)
        only_return: If True, returns raw anime list instead of processing
        site: The site to search on ("aniworld.to" or "s.to")

    Returns:
        Union[str, List[Dict]]: Either selected anime link or list of anime

    Raises:
        ValueError: If no anime found or invalid input
    """
    if not only_return:
        print(display_ascii_art())

    if not keyword:
        keyword = _get_user_input()
    else:
        keyword = _validate_keyword(keyword)

    headers = {}
    if site == "s.to":
        search_url = f"{S_TO}/api/search/suggest?term={quote(keyword)}"
        headers["X-Requested-With"] = "XMLHttpRequest"
    else:
        search_url = f"{ANIWORLD_TO}/ajax/seriesSearch?keyword={quote(keyword)}"

    anime_list = fetch_anime_list(search_url, headers=headers)

    # For s.to, the response is {"shows": [...], "people": [], "genres": []}
    if site == "s.to" and isinstance(anime_list, dict):
        shows = anime_list.get("shows", [])
        # Map s.to format to our standard format
        anime_list = []
        for show in shows:
            # s.to uses "url" instead of "link" and it's often absolute or missing base
            link = show.get("url", "")
            if link.startswith("/"):
                link = link.lstrip("/")
            
            anime_list.append({
                "name": show.get("name"),
                "link": link,
                "productionYear": "" # s.to suggest API doesn't provide year
            })
        
        # Fetch covers for s.to results in parallel if we are returning the list
        if only_return and anime_list:
            def fetch_sto_cover(anime):
                try:
                    full_url = f"{S_TO}/{anime['link']}"
                    resp = requests.get(full_url, timeout=DEFAULT_REQUEST_TIMEOUT)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        # Based on provided HTML: find picture -> img[data-src]
                        # The user pointed out col-lg-2 for desktop cover
                        img = soup.select_one(".col-lg-2 picture img")
                        if img:
                            cover = img.get("data-src") or img.get("src")
                            if cover and cover.startswith("/"):
                                cover = S_TO + cover
                            anime["cover"] = cover
                except Exception as e:
                    logging.debug(f"Failed to fetch cover for {anime['name']}: {e}")
                return anime

            with ThreadPoolExecutor(max_workers=5) as executor:
                anime_list = list(executor.map(fetch_sto_cover, anime_list))

    if only_return:
        return anime_list

    if len(anime_list) == 1:
        return anime_list[0].get("link", None)

    if not anime_list:
        raise ValueError("Could not get valid anime")

    return curses.wrapper(show_menu, anime_list)


def _clean_json_text(text: str) -> str:
    """
    Clean problematic characters from JSON text.

    Args:
        text: Raw JSON text

    Returns:
        str: Cleaned JSON text
    """
    # Remove BOM and problematic characters
    clean_text = text.encode("utf-8").decode("utf-8-sig")
    # Remove control characters that can break JSON parsing
    clean_text = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", clean_text)
    return clean_text




def search_tmdb_movies(keyword: str) -> List[Dict]:
    """
    Search for movies on TMDB using search/trending and enriching from spans.

    Args:
        keyword: Search term

    Returns:
        List[Dict]: List of movie dictionaries
    """
    try:
        search_url = f"https://www.themoviedb.org/search/trending?query={quote(keyword)}"
        response = requests.get(search_url, timeout=DEFAULT_REQUEST_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        results = data.get("results", [])
        
        movie_list = []
        seen_ids = set()
        seen_names = set()

        def add_movie(m_data):
            tmdb_id = m_data.get("id")
            name = m_data.get("title") or m_data.get("name") or m_data.get("original_title") or m_data.get("original_name")
            if not name:
                return

            if tmdb_id and tmdb_id in seen_ids:
                return
            
            if not tmdb_id and name in seen_names:
                return

            movie_entry = {
                "name": name,
                "id": tmdb_id,
                "tmdb_id": tmdb_id,
                "poster_path": m_data.get("poster_path"),
                "release_date": m_data.get("release_date"),
                "overview": m_data.get("overview") or m_data.get("description"),
                "vote_average": m_data.get("vote_average"),
                "media_type": "movie"
            }
            movie_list.append(movie_entry)
            if tmdb_id:
                seen_ids.add(tmdb_id)
            seen_names.add(name)

        # 1. Process full objects first (except persons)
        for item in results:
            if isinstance(item, dict) and item.get("media_type") == "movie":
                add_movie(item)

        # 2. Process spans to find all related movie titles
        span_titles = []
        for item in results:
            if isinstance(item, str) and 'data-media-type="/movie"' in item:
                try:
                    name_match = re.search(r'data-search-name="([^"]+)"', item)
                    if name_match:
                        name = html.unescape(name_match.group(1))
                        if name not in seen_names:
                            span_titles.append(name)
                except Exception:
                    continue

        # 3. Enrich missing movies from span titles
        if span_titles:
            def fetch_movie_details(name):
                try:
                    # Clean title for better matching (remove text in parentheses)
                    clean_name = re.sub(r'\s*\([^)]*\)', '', name).strip()
                    # We use the 'multi' search which is very robust for exact names
                    enrich_url = f"https://www.themoviedb.org/search/multi?query={quote(clean_name)}"
                    headers = {
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest"
                    }
                    resp = requests.get(enrich_url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
                    if resp.status_code == 200:
                        try:
                            movie_data = resp.json()
                            movie_results = movie_data.get("results", [])
                        except Exception:
                            return {"title": name}
                        
                        if movie_results:
                            # Filter for movies only and prefer exact matches
                            movies_only = [m for m in movie_results if m.get("media_type") == "movie"]
                            if not movies_only:
                                movies_only = movie_results # Fallback
                                
                            for m in movies_only:
                                m_title = m.get("title") or m.get("original_title") or m.get("name")
                                if m_title and (m_title == name or m_title == clean_name):
                                    return m
                            return movies_only[0]
                except Exception:
                    pass
                return {"title": name} # Fallback with just the name

            with ThreadPoolExecutor(max_workers=10) as executor:
                enriched_results = list(executor.map(fetch_movie_details, span_titles))
                for m_data in enriched_results:
                    if m_data:
                        add_movie(m_data)
        
        return movie_list

    except Exception as err:
        logging.error("Failed to fetch movies from TMDB: %s", err)
        return []


@lru_cache(maxsize=512)
def search_tmdb_series(keyword: str) -> List[Dict]:
    """
    Search for TV series on TMDB.

    Args:
        keyword: Search term

    Returns:
        List[Dict]: List of TV series dictionaries
    """
    try:
        # Simple rate limiting: small random delay to avoid 429
        time.sleep(random.uniform(0.1, 0.5))

        # We use multi search to find TV series with higher relevance
        search_url = f"https://www.themoviedb.org/search/multi?query={quote(keyword)}"
        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(search_url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
        
        if response.status_code == 429:
            logging.warning(f"TMDB rate limit hit for {keyword}, skipping...")
            return []
            
        response.raise_for_status()
        
        data = response.json()
        results = data.get("results", [])
        
        series_list = []
        for item in results:
            if isinstance(item, dict) and item.get("media_type") == "tv":
                name = item.get("name") or item.get("original_name")
                if name:
                    series_list.append({
                        "name": name,
                        "tmdb_id": item.get("id"),
                        "poster_path": item.get("poster_path"),
                        "first_air_date": item.get("first_air_date"),
                        "overview": item.get("overview"),
                        "vote_average": item.get("vote_average"),
                        "media_type": "tv"
                    })
        
        return series_list

    except Exception as err:
        logging.error("Failed to fetch series from TMDB: %s", err)
        return []


def fetch_popular_and_new_anime() -> Dict[str, List[Dict[str, str]]]:
    """
    Fetch HTML from LankabelTV homepage for popular and new anime parsing.

    Extracts anime titles and cover URLs from "Beliebt bei LankabelTV" and "Neue Animes" sections.

    Returns:
        Dictionary with 'popular' and 'new' keys containing lists of anime data
    """
    try:
        response = requests.get(ANIWORLD_TO, timeout=DEFAULT_REQUEST_TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        result = {"popular": [], "new": []}

        # Extract popular anime section
        popular_section = soup.find(
            "h2", string=lambda text: text and "beliebt" in text.lower()
        )
        if popular_section:
            popular_carousel = popular_section.find_parent().find_next_sibling(
                "div", class_="previews"
            )
            if popular_carousel:
                result["popular"] = extract_anime_from_carousel(popular_carousel)

        # Extract new anime section
        new_section = soup.find(
            "h2",
            string=lambda text: text
            and "neue" in text.lower()
            and "anime" in text.lower(),
        )
        if new_section:
            new_carousel = new_section.find_parent().find_next_sibling(
                "div", class_="previews"
            )
            if new_carousel:
                result["new"] = extract_anime_from_carousel(new_carousel)

        # Enrich with TMDB images for both sections
        def enrich_with_tmdb(anime_list):
            def enrich_single(anime):
                try:
                    tmdb_results = search_tmdb_series(anime["name"])
                    if tmdb_results:
                        # Find best match for name
                        best_match = None
                        for res in tmdb_results:
                            if res["name"].lower() == anime["name"].lower():
                                best_match = res
                                break
                        
                        if not best_match:
                            best_match = tmdb_results[0]
                        
                        if best_match.get("poster_path"):
                            anime["cover"] = f"https://image.tmdb.org/t/p/w500{best_match['poster_path']}"
                        if best_match.get("overview"):
                            anime["description"] = best_match["overview"]
                        if best_match.get("vote_average"):
                            anime["rating"] = best_match["vote_average"]
                except Exception:
                    pass
                return anime

            # Reduced workers to avoid rate limiting
            with ThreadPoolExecutor(max_workers=3) as executor:
                return list(executor.map(enrich_single, anime_list))

        result["popular"] = enrich_with_tmdb(result["popular"])
        result["new"] = enrich_with_tmdb(result["new"])

        return result

    except requests.RequestException as err:
        logging.error("Failed to fetch LankabelTV homepage: %s", err)
        raise ValueError("Could not fetch homepage data") from err


def extract_anime_from_carousel(carousel_div):
    """
    Extract anime data from a carousel div section.

    Args:
        carousel_div: BeautifulSoup element containing the carousel

    Returns:
        List of dictionaries with 'name' and 'cover' keys
    """
    anime_list = []

    # Find all cover list items
    cover_items = carousel_div.find_all("div", class_="coverListItem")

    for item in cover_items:
        try:
            # Extract link and name
            link_tag = item.find("a")
            link = None
            if link_tag:
                link = link_tag.get("href")

            # Extract name from h3 tag or title attribute
            name = None
            h3_tag = item.find("h3")
            if h3_tag:
                name = h3_tag.get_text(strip=True)
                # Remove any trailing dots or special characters
                name = name.split(" •")[0].strip()

            # Fallback to title attribute from link
            if not name:
                if link_tag and link_tag.get("title"):
                    title_text = link_tag.get("title")
                    # Extract name before "alle Folgen ansehen" or similar text
                    name = (
                        title_text.split(" alle Folgen")[0]
                        .split(" jetzt online")[0]
                        .strip()
                    )

            # Extract cover URL from img tag
            cover = None
            img_tag = item.find("img")
            if img_tag:
                # Try data-src first (lazy loading), then src
                cover = img_tag.get("data-src") or img_tag.get("src")
                # Make absolute URL if relative
                if cover and cover.startswith("/"):
                    cover = ANIWORLD_TO + cover

            if name and cover:
                anime_list.append({"name": name, "cover": cover, "link": link})

        except Exception:
            # Skip this item if extraction fails
            continue

    return anime_list


def _render_menu(stdscr: curses.window, options: List[Dict], current_row: int) -> None:
    """
    Render the anime selection menu.

    Args:
        stdscr: Curses window object
        options: List of anime options
        current_row: Currently selected row index
    """
    stdscr.clear()

    max_y, max_x = stdscr.getmaxyx()

    for idx, anime in enumerate(options):
        if idx >= max_y - 1:  # Prevent drawing beyond screen
            break

        name = anime.get("name", "No Name")
        year = anime.get("productionYear", "Unknown Year")
        display_text = f"{name} {year}"

        # Truncate text if it's too long for the screen
        if len(display_text) >= max_x:
            display_text = display_text[: max_x - 4] + "..."

        highlight = curses.A_REVERSE if idx == current_row else 0

        try:
            stdscr.attron(highlight)
            stdscr.addstr(idx, 0, display_text)
            stdscr.attroff(highlight)
        except curses.error:
            # Handle cases where we can't draw to the screen
            pass

    stdscr.refresh()


def show_menu(stdscr: curses.window, options: List[Dict]) -> Optional[str]:
    """
    Display interactive menu for anime selection.

    Args:
        stdscr: Curses window object
        options: List of anime dictionaries

    Returns:
        Optional[str]: Selected anime link or None if cancelled
    """
    if not options:
        return None

    current_row = 0

    try:
        while True:
            _render_menu(stdscr, options, current_row)
            key = stdscr.getch()

            # Handle navigation
            if key == curses.KEY_DOWN:
                current_row = (current_row + 1) % len(options)
            elif key == curses.KEY_UP:
                current_row = (current_row - 1 + len(options)) % len(options)
            elif key == ord("\n"):
                return options[current_row].get("link", "No Link")
            elif key == ord("q") or key == 27:  # 'q' or ESC
                break

    except curses.error as err:
        logging.error("Curses error in menu: %s", err)
    except KeyboardInterrupt:
        pass

    return None


if __name__ == "__main__":
    print(search_anime())
