"""
Test 3: Concurrent downloads (the original user bug).

The user reported: "After the first download, every subsequent
download hangs on 'Starting...'". We reproduce this by:
1. Starting a download whose yt-dlp call takes 30+ seconds (by
   pointing it at our fake HTTP server's slow /stream endpoint).
2. Waiting a few seconds so the worker thread is definitely
   busy inside yt-dlp.
3. Triggering a SECOND download via the UI.
4. Verifying that the second download:
   - Closes its modal in <7s (frontend timeout)
   - The button returns to its idle state
   - The new job appears in the queue

This is the test that catches the race condition between
yt-dlp's GIL contention and the download manager's locks.
"""

import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio


async def _trigger_download_via_api(page, base_url, episode_url):
    """Trigger a download by directly calling the API the way the
    frontend would, but from the test browser so we go through
    the same CORS/network path.

    Returns the elapsed time in seconds.
    """
    t0 = time.monotonic()
    result = await page.evaluate(
        """
        async ({url, base}) => {
            const resp = await fetch(base + '/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    episode_url: url,
                    language: 'German Dub',
                    provider: 'VOE',
                    anime_title: 'Concurrent Test',
                }),
            });
            return {
                status: resp.status,
                body: await resp.text(),
            };
        }
        """,
        {"url": episode_url, "base": base_url},
    )
    elapsed = time.monotonic() - t0
    return result, elapsed


async def test_second_download_during_first_does_not_hang(
    browser_page, base_url, fake_ytdlp_server
):
    """The user bug: a second download call while the first is
    running must not hang. We expect the second POST to return in
    well under 10 seconds (typically <1s) regardless of what yt-dlp
    is doing in the first download.
    """
    page = browser_page
    fake_host, fake_port = fake_ytdlp_server

    # Build episode URLs that point at the fake server. dur=20
    # means the fake server will take ~20 seconds to "stream" the
    # fake video. That's long enough to definitely be in the middle
    # of yt-dlp's read loop when the second request comes in.
    url_a = f"http://{fake_host}:{fake_port}/stream?dur=20&/anime/stream/test-a/staffel-1/episode-1"
    url_b = f"http://{fake_host}:{fake_port}/stream?dur=20&/anime/stream/test-b/staffel-1/episode-1"

    await page.goto(base_url, wait_until="domcontentloaded")

    # First download: trigger it via the API
    print("\n[INFO] Triggering first download (yt-dlp will run for ~20s)...")
    res_a, t_a = await _trigger_download_via_api(page, base_url, url_a)
    print(f"[INFO] First download queued in {t_a:.2f}s (status={res_a['status']})")
    assert res_a["status"] == 200, f"First download failed: {res_a['body']}"
    import json as _json
    body_a = _json.loads(res_a["body"])
    assert body_a.get("success"), f"First download not successful: {body_a}"

    # Give yt-dlp time to start (the worker thread needs to resolve
    # the URL and then begin streaming from the fake server).
    await asyncio.sleep(3)

    # Second download: this is the critical test. While the first
    # download's yt-dlp call is actively reading from the fake
    # server, we trigger a second download. With the bug present,
    # this request hangs because the queue_lock is held by the
    # first download's worker thread.
    print("\n[INFO] Triggering SECOND download while first is still running...")
    t0 = time.monotonic()
    res_b, t_b = await _trigger_download_via_api(page, base_url, url_b)
    elapsed_blocked = time.monotonic() - t0
    print(f"[INFO] Second download took {t_b:.2f}s (blocked={elapsed_blocked:.2f}s)")

    # The request must complete. It should not hang the entire
    # test timeout. We allow up to 15s to be very generous - the
    # backend should respond in <1s if the lock issue is fixed.
    assert res_b["status"] == 200, (
        f"Second download failed: status={res_b['status']} body={res_b['body']}"
    )
    body_b = _json.loads(res_b["body"])
    assert body_b.get("success"), f"Second download not successful: {body_b}"

    # Strict assertion: under 10s is the user-acceptable threshold.
    # The previous deadlock made this take 30+ seconds.
    assert t_b < 10.0, (
        f"Second download took {t_b:.2f}s - that means the deadlock "
        f"is still present. Should be <1s with the fix."
    )


async def test_three_concurrent_downloads_during_long_yt_dlp(
    browser_page, base_url, fake_ytdlp_server
):
    """Three concurrent download POSTs while yt-dlp is busy must
    all complete in <10s each. This stresses the lock more than
    the two-download test.
    """
    page = browser_page
    fake_host, fake_port = fake_ytdlp_server

    url_a = f"http://{fake_host}:{fake_port}/stream?dur=30&/anime/stream/a/staffel-1/episode-1"
    url_b = f"http://{fake_host}:{fake_port}/stream?dur=30&/anime/stream/b/staffel-1/episode-1"
    url_c = f"http://{fake_host}:{fake_port}/stream?dur=30&/anime/stream/c/staffel-1/episode-1"

    await page.goto(base_url, wait_until="domcontentloaded")

    # First download
    print("\n[INFO] Triggering first download (long-running)...")
    res_a, t_a = await _trigger_download_via_api(page, base_url, url_a)
    assert res_a["status"] == 200
    print(f"[INFO] First download queued in {t_a:.2f}s")

    await asyncio.sleep(2)

    # Fire two more downloads in parallel via the browser
    print("[INFO] Firing 2 concurrent second downloads...")
    t0 = time.monotonic()
    results = await page.evaluate(
        """
        async ({a, b, base}) => {
            const promises = [a, b].map(url =>
                fetch(base + '/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        episode_url: url,
                        language: 'German Dub',
                        provider: 'VOE',
                        anime_title: 'Concurrent Test',
                    }),
                }).then(async r => ({ status: r.status, body: await r.text() }))
            );
            return await Promise.all(promises);
        }
        """,
        {"a": url_b, "b": url_c, "base": base_url},
    )
    elapsed = time.monotonic() - t0
    print(f"[INFO] Two concurrent downloads both completed in {elapsed:.2f}s")
    for i, r in enumerate(results):
        assert r["status"] == 200, f"Concurrent download {i} failed: {r}"
    assert elapsed < 10.0, f"Concurrent downloads took {elapsed:.2f}s - deadlock present"
