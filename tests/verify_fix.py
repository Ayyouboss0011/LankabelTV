import logging
import sys
import os

# Add src to path
sys.path.append(os.path.abspath("src"))

from aniworld.common.common import get_season_episode_count, get_season_episodes_details
from aniworld.models import Episode, Anime

# Set up logging to see what's happening
logging.basicConfig(level=logging.DEBUG)

def test_sto_parsing():
    slug = "game-of-thrones"
    sto_link = "https://s.to/serie/stream/game-of-thrones"
    
    print(f"\nTesting s.to parsing for {slug}...")
    try:
        counts = get_season_episode_count(slug, sto_link)
        print(f"Season counts: {counts}")
        
        if counts:
            details = get_season_episodes_details(slug, sto_link)
            print(f"Details for Season 1 (first 2 episodes): {details.get(1, [])[:2]}")
            
            # Test Episode model slug extraction
            ep = Episode(link="https://s.to/serie/game-of-thrones/staffel-1/episode-1", site="s.to")
            print(f"Episode model slug: {ep.slug}, season: {ep.season}, episode: {ep.episode}")
            
    except Exception as e:
        print(f"Error during s.to testing: {e}")

def test_aniworld_parsing():
    slug = "solo-leveling"
    ani_link = "https://aniworld.to/anime/stream/solo-leveling"
    
    print(f"\nTesting aniworld parsing for {slug}...")
    try:
        counts = get_season_episode_count(slug, ani_link)
        print(f"Season counts: {counts}")
        
        if counts:
            # Test Episode model slug extraction
            ep = Episode(link="https://aniworld.to/anime/stream/solo-leveling/staffel-1/episode-1")
            print(f"Episode model slug: {ep.slug}, season: {ep.season}, episode: {ep.episode}")
            
    except Exception as e:
        print(f"Error during aniworld testing: {e}")

if __name__ == "__main__":
    test_sto_parsing()
    test_aniworld_parsing()
