#!/usr/bin/env python3
"""
Tests for the hardened VOE redirect parsing.

Offline tests for the redirect variants (normal / escaped / relative / player
page) plus an optional live check.

Run with:
    python3 tests/test_voe_redirect.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from aniworld.extractors.provider.voe import (  # noqa: E402
    extract_redirect_url,
    normalize_redirect_url,
)

BASE = "https://voe.sx/e/abc123"

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, bool(condition)))
    print(f"[{status}] {name}{' - ' + detail if detail else ''}")


def test_redirect_variants():
    variants = {
        "plain js redirect": (
            "window.location.href = 'https://mirror.example/e/abc123';",
            "https://mirror.example/e/abc123",
        ),
        "escaped slashes": (
            "window.location.href = 'https:\\/\\/mirror.example\\/e\\/abc123';",
            "https://mirror.example/e/abc123",
        ),
        "relative url": (
            "window.location.href = '/e/abc123';",
            "https://voe.sx/e/abc123",
        ),
        "protocol relative": (
            "window.location.href = '//mirror.example/e/abc123';",
            "https://mirror.example/e/abc123",
        ),
        "location.replace": (
            "location.replace('https://mirror.example/e/abc123');",
            "https://mirror.example/e/abc123",
        ),
        "location.assign": (
            "window.location.assign('https://mirror.example/e/abc123');",
            "https://mirror.example/e/abc123",
        ),
        "escaped json url": (
            '{"url":"https:\\/\\/mirror.example\\/e\\/abc123"}',
            "https://mirror.example/e/abc123",
        ),
    }

    for name, (html, expected) in variants.items():
        got = extract_redirect_url(html, BASE)
        if expected is None:
            check(f"redirect: {name}", got is None, f"got {got}")
        else:
            check(f"redirect: {name}", got == expected, f"got {got}")


def test_asset_hosts_are_ignored():
    player_page = (
        "<link href='https://fonts.gstatic.com/some.css'>"
        "<script>var player = true;</script>"
    )
    got = extract_redirect_url(player_page, BASE)
    check("asset hosts ignored", got is None, f"got {got}")

    player_page_with_mirror = (
        "<link href='https://fonts.gstatic.com/some.css'>"
        "<script>window.location.href = 'https://mirror.example/e/abc123';</script>"
    )
    got = extract_redirect_url(player_page_with_mirror, BASE)
    check(
        "js redirect preferred over assets",
        got == "https://mirror.example/e/abc123",
        f"got {got}",
    )


def test_normalize_helpers():
    check("normalize empty", normalize_redirect_url("", BASE) is None)
    check(
        "normalize escaped",
        normalize_redirect_url("https:\\/\\/x.example\\/e\\/1", BASE)
        == "https://x.example/e/1",
    )
    check(
        "normalize relative",
        normalize_redirect_url("/e/1", BASE) == "https://voe.sx/e/1",
    )


def test_live_extraction():
    try:
        from aniworld.extractors.provider.voe import get_direct_link_from_voe

        link = get_direct_link_from_voe("https://voe.sx/e/rd3wbokfbxvq")
        check("live VOE extraction", bool(link and link.startswith("http")), (link or "")[:70])
    except Exception as err:  # noqa: BLE001
        check("live VOE extraction", False, str(err)[:120])


def main():
    tests = [
        test_redirect_variants,
        test_asset_hosts_are_ignored,
        test_normalize_helpers,
        test_live_extraction,
    ]
    for test in tests:
        print(f"\n=== {test.__name__} ===")
        test()

    failed = [name for name, ok in results if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)} check(s): {', '.join(failed)}")
        return 1
    print(f"All {len(results)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
