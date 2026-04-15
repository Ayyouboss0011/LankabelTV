import logging
from .parser import arguments


def _detect_site_from_url(url: str) -> str:
    """
    Detect the site (aniworld.to or s.to) from a given URL.
    
    Args:
        url: The URL to check
        
    Returns:
        The site identifier ("aniworld.to" or "s.to")
    """
    from . import config
    if config.S_TO in url:
        return "s.to"
    return "aniworld.to"


def _group_episodes_by_series(urls: list[str]) -> list:
    """
    Groups episode URLs by their series and creates Anime objects.
    
    Args:
        urls: List of episode URLs
        
    Returns:
        List of Anime objects
    """
    from .models import Anime, Episode
    from .common import generate_links
    
    # Simple implementation: convert each URL to an Anime object
    # This might be simplified depending on how it's used in the web interface
    # In the web UI, it seems to be used to calculate the total number of episodes
    
    anime_objects = []
    # Deduplicate and sort
    all_urls = generate_links(urls, arguments)
    
    # We need to group these by series slug to create Anime objects
    series_map = {}
    for url in all_urls:
        site = _detect_site_from_url(url)
        from . import config
        
        # Extract slug
        slug = None
        if "/anime/stream/" in url:
            slug = url.split("/anime/stream/")[-1].split("/")[0]
        elif "/serie/stream/" in url:
            slug = url.split("/serie/stream/")[-1].split("/")[0]
        elif "/serie/" in url:
            slug = url.split("/serie/")[-1].split("/")[0]
            
        if slug:
            if slug not in series_map:
                series_map[slug] = {"site": site, "episodes": []}
            
            # Parse season and episode from URL
            import re
            season_match = re.search(r"staffel-(\d+)", url)
            episode_match = re.search(r"episode-(\d+)", url)
            movie_match = re.search(r"film-(\d+)", url)
            
            season = int(season_match.group(1)) if season_match else (0 if movie_match else 1)
            episode_num = int(episode_match.group(1)) if episode_match else (int(movie_match.group(1)) if movie_match else 1)
            
            series_map[slug]["episodes"].append(
                Episode(link=url, slug=slug, season=season, episode=episode_num, site=site)
            )
            
    for slug, data in series_map.items():
        anime_objects.append(
            Anime(slug=slug, episode_list=data["episodes"], site=data["site"])
        )
        
    return anime_objects


def lankabeltv() -> None:
    """
    Main entry point for the LankabelTV downloader.
    Starts the Flask web interface directly.
    """
    try:
        from .web.app import start_web_interface

        # Always start web interface
        start_web_interface(
            arguments, 
            port=arguments.web_port, 
            debug=arguments.debug
        )

    except KeyboardInterrupt:
        pass
    except Exception as err:
        logging.error("Unexpected error: %s", err, exc_info=True)
        print(f"\nAn unexpected error occurred: {err}")


if __name__ == "__main__":
    lankabeltv()
