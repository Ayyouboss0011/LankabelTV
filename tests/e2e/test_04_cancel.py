"""
Test 4: Cancel a running download and immediately start a new one.

This verifies the "Cancel" button works and that after cancelling,
the user can start a fresh download without UI hangs.
"""

import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio


async def test_cancel_running_download_frees_queue(
    browser_page, base_url, fake_ytdlp_server
):
    """Cancelling a download should let a new one start immediately."""
    page = browser_page
    fake_host, fake_port = fake_ytdlp_server

    url_a = f"http://{fake_host}:{fake_port}/stream?dur=30&/anime/stream/cancel-a/staffel-1/episode-1"
    url_b = f"http://{fake_host}:{fake_port}/stream?dur=30&/anime/stream/cancel-b/staffel-1/episode-1"

    await page.goto(base_url, wait_until="domcontentloaded")

    # Start a long download
    res_a = await page.evaluate(
        """
        async ({url, base}) => {
            const r = await fetch(base + '/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ episode_url: url, language: 'German Dub', provider: 'VOE', anime_title: 'Cancel A' }),
            });
            return { status: r.status, body: await r.text() };
        }
        """,
        {"url": url_a, "base": base_url},
    )
    import json as _json
    body_a = _json.loads(res_a["body"])
    queue_id_a = body_a["queue_id"]
    assert res_a["status"] == 200

    # Wait a moment so yt-dlp starts
    await asyncio.sleep(2)

    # Cancel the download
    cancel_res = await page.evaluate(
        """
        async ({qid, base}) => {
            const r = await fetch(base + '/api/download/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ queue_id: qid }),
            });
            return { status: r.status, body: await r.text() };
        }
        """,
        {"qid": queue_id_a, "base": base_url},
    )
    assert cancel_res["status"] == 200, f"Cancel failed: {cancel_res}"
    print(f"[INFO] Cancelled job {queue_id_a}: {cancel_res['body']}")

    # Wait a moment for cancellation to propagate
    await asyncio.sleep(1)

    # Now start a new download - this should not hang
    t0 = time.monotonic()
    res_b = await page.evaluate(
        """
        async ({url, base}) => {
            const r = await fetch(base + '/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ episode_url: url, language: 'German Dub', provider: 'VOE', anime_title: 'Cancel B' }),
            });
            return { status: r.status, body: await r.text() };
        }
        """,
        {"url": url_b, "base": base_url},
    )
    elapsed = time.monotonic() - t0
    print(f"[INFO] Post-cancel download took {elapsed:.2f}s")
    assert res_b["status"] == 200, f"Post-cancel download failed: {res_b}"
    assert elapsed < 10.0, f"Post-cancel download took {elapsed:.2f}s"
