#!/usr/bin/env python3
"""
Test script to verify the s.to URL construction fix
"""

import sys
sys.path.insert(0, 'src')

from aniworld.models import Episode
from aniworld import config

def test_sto_episode_url_construction():
    """Test that s.to episode URLs are constructed correctly without stream_path"""

    print("Testing s.to episode URL construction fix...")
    print("=" * 60)

    # Test case 1: Regular episode
    print("\nTest 1: Regular episode (Season 1, Episode 1)")
    ep1 = Episode(
        slug="kung-fu-panda-legenden-mit-fell-und-fu",
        season=1,
        episode=1,
        site="s.to"
    )

    expected_url = f"{config.S_TO}/serie/kung-fu-panda-legenden-mit-fell-und-fu/staffel-1/episode-1"
    actual_url = ep1.link

    print(f"Expected: {expected_url}")
    print(f"Actual:   {actual_url}")

    if actual_url == expected_url:
        print("✓ PASS: URL constructed correctly")
    else:
        print("✗ FAIL: URL mismatch")
        return False

    # Test case 2: Movie
    print("\nTest 2: Movie (Season 0, Episode 1)")
    ep2 = Episode(
        slug="test-movie",
        season=0,
        episode=1,
        site="s.to"
    )

    expected_url2 = f"{config.S_TO}/serie/test-movie/filme/film-1"
    actual_url2 = ep2.link

    print(f"Expected: {expected_url2}")
    print(f"Actual:   {actual_url2}")

    if actual_url2 == expected_url2:
        print("✓ PASS: Movie URL constructed correctly")
    else:
        print("✗ FAIL: Movie URL mismatch")
        return False

    # Test case 3: aniworld.to should still work with stream_path
    print("\nTest 3: aniworld.to episode (should include stream_path)")
    ep3 = Episode(
        slug="test-anime",
        season=1,
        episode=1,
        site="aniworld.to"
    )

    expected_url3 = f"{config.ANIWORLD_TO}/anime/stream/test-anime/staffel-1/episode-1"
    actual_url3 = ep3.link

    print(f"Expected: {expected_url3}")
    print(f"Actual:   {actual_url3}")

    if actual_url3 == expected_url3:
        print("✓ PASS: aniworld.to URL constructed correctly")
    else:
        print("✗ FAIL: aniworld.to URL mismatch")
        return False

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    return True

if __name__ == "__main__":
    success = test_sto_episode_url_construction()
    sys.exit(0 if success else 1)