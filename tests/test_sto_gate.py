#!/usr/bin/env python3
"""
Live test for the new s.to redirect gate (frame-bridge + CSRF POST).

s.to no longer 302-redirects on a plain GET of ``/r?t=...``; the hoster URL is
returned by a form POST to ``/r``. This test verifies the resolver end to end.

Run with:
    python3 tests/test_sto_gate.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from aniworld.models import Episode  # noqa: E402

EPISODE_URL = "https://serienstream.to/serie/what-if-2021/staffel-3/episode-5"

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, bool(condition)))
    print(f"[{status}] {name}{' - ' + detail if detail else ''}")


def main():
    print("=== s.to redirect gate ===")
    episode = Episode(link=EPISODE_URL, site="s.to")
    episode._selected_provider = "VOE"
    episode._selected_language = "German Dub"

    redirect = episode.get_redirect_link()
    check(
        "redirect link resolved",
        bool(redirect and "/r?" in redirect),
        (redirect or "")[:70],
    )

    embed = episode.get_embeded_link()
    check(
        "gate resolves to hoster embed",
        bool(embed and "voe.sx" in embed),
        (embed or "")[:70],
    )

    if embed:
        direct = episode.get_direct_link()
        check(
            "direct HLS link",
            bool(direct and direct.startswith("http")),
            (direct or "")[:70],
        )

    failed = [name for name, ok in results if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print(f"All {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
