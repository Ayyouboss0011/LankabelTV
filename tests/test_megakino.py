#!/usr/bin/env python3
"""
Network tests for the MegaKino integration (megakino23.com).

Run with:
    python3 tests/test_megakino.py

These tests hit the live site, so they require an internet connection.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from aniworld.megakino.megakino import MegakinoClient  # noqa: E402

SEARCH_QUERY = "matrix"
MOVIE_URL = "https://megakino23.com/films/6527-resident-evil.html"
SERIES_URL = "https://megakino23.com/serials/5877-stranger-things-5-stafffel.html"

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, bool(condition)))
    print(f"[{status}] {name}{' - ' + detail if detail else ''}")


def test_search():
    client = MegakinoClient()
    found = client.search(SEARCH_QUERY)
    check("search returns results", len(found) > 0, f"{len(found)} results")
    check("search result fields", all(
        r.get("name") and r.get("url") and r.get("media_type") in ("movie", "series")
        for r in found
    ))
    check("search short query returns empty", client.search("ab") == [])


def test_movie_details():
    client = MegakinoClient()
    movie = client.get_movie(MOVIE_URL)
    check("movie details parsed", bool(movie and movie.get("title")), movie.get("title") if movie else "")
    if movie:
        providers = [s["provider"] for s in movie["streams"]]
        check("movie has VOE stream", "VOE" in providers, str(providers))
        check("movie has GXPlayer stream", "GXPlayer" in providers, str(providers))


def test_series_details():
    client = MegakinoClient()
    series = client.get_series_season(SERIES_URL)
    check("series details parsed", bool(series and series.get("episodes")), series.get("title") if series else "")
    if series:
        check("series season detected", series.get("season") == 5, str(series.get("season")))
        check("series episodes detected", len(series["episodes"]) == 8, str(len(series["episodes"])))
        streams = client.get_streams(SERIES_URL, episode=3)
        check("series episode streams", bool(streams), str(streams))


def test_voe_extractor():
    from aniworld.extractors.provider.voe import get_direct_link_from_voe

    link = get_direct_link_from_voe("https://voe.sx/e/we8skxm9ocpi")
    check("VOE direct link", bool(link and link.startswith("http")), (link or "")[:80])


def test_gxplayer_extractor():
    from aniworld.extractors.provider.gxplayer import get_direct_link_from_gxplayer

    link = get_direct_link_from_gxplayer("https://watch.gxplayer.xyz/watch?v=AGCJVUQH")
    check("GXPlayer direct link", bool(link and link.startswith("http")), (link or "")[:80])


def test_download_bridge():
    from aniworld.megakino.megakino_stream_finder import create_anime_object

    anime = create_anime_object(
        "https://voe.sx/e/we8skxm9ocpi", "Test Movie", "German Dub", "VOE"
    )
    episode = anime.episode_list[0]
    direct = episode.get_direct_link()
    check("download bridge VOE", bool(direct and direct.startswith("http")), (direct or "")[:80])


def main():
    tests = [
        test_search,
        test_movie_details,
        test_series_details,
        test_voe_extractor,
        test_gxplayer_extractor,
        test_download_bridge,
    ]
    for test in tests:
        print(f"\n=== {test.__name__} ===")
        try:
            test()
        except Exception:
            traceback.print_exc()
            check(test.__name__, False, "exception")

    failed = [name for name, ok in results if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print(f"All {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
