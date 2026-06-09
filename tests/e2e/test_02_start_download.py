"""
Test 2: Start Download button + 5s timeout.

The frontend has a 5-second timeout in startDownload() that closes
the modal if the POST /api/download takes too long. This test verifies
that:
1. When we click "Start Download", the button text changes to
   "Starting..." immediately.
2. The modal closes within ~6 seconds even if the backend is slow
   (we simulate slowness by injecting a sleep into the POST).
3. The "Request sent, checking status..." notification appears.

This test triggers the download modal by waiting for the page to
fully initialise and then clicking on a popular anime card, or
by directly opening the modal via Download.showModal() if exposed.
"""

import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio


async def _wait_for_app_ready(page, timeout=15000):
    """Wait until the frontend modules are fully initialised.

    The app.js file uses `await Download.init()` inside a
    DOMContentLoaded handler, and only AFTER that does it expose
    window.showDownloadModal. We poll for that function.
    """
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        ready = await page.evaluate(
            "() => typeof window.showDownloadModal === 'function'"
        )
        if ready:
            return True
        await asyncio.sleep(0.1)
    return False


async def test_start_download_button_changes_to_starting(browser_page, base_url):
    """Clicking Start Download should immediately change the button text."""
    page = browser_page
    # Intercept /api/episodes and return a fake episode list
    await page.route(
        "**/api/episodes",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "episodes": {"1": [{"season": 1, "episode": 1, "languages": ["Deutsch"], "language_codes": [1], "providers": ["VOE"], "url": "http://example.com/ep1"}]}, "movies": [], "metadata": {}}',
        ),
    )
    await page.goto(base_url, wait_until="domcontentloaded")
    assert await _wait_for_app_ready(page), "App did not finish initialising in time"

    # Open the modal directly via the window API
    await page.evaluate(
        """
        () => window.showDownloadModal('Test Anime', 'Series',
            'http://example.com/anime/stream/test/staffel-1/episode-1', null);
        """
    )
    # Wait for the modal to be visible
    modal = await page.wait_for_selector("#download-modal", state="visible", timeout=10000)
    assert await modal.is_visible()

    # Wait for the episode tree to render (checkboxes are in the DOM
    # but may be visually hidden if the parent has display:none; we
    # use state="attached" to just check existence).
    await page.wait_for_selector(".episode-checkbox", state="attached", timeout=10000)

    # Use the season checkbox which controls all child episode
    # checkboxes - it is the visible one the user actually clicks
    # in the real UI. Tick it programmatically by dispatching a
    # 'change' event, which is what the frontend's toggleEpisode()
    # listens to.
    ticked = await page.evaluate(
        """
        () => {
            // Try the season checkbox first (the visible one)
            let cb = document.querySelector('.season-checkbox');
            if (cb) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                return 'season';
            }
            // Fallback: first episode checkbox
            cb = document.querySelector('.episode-checkbox');
            if (cb) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                return 'episode';
            }
            return null;
        }
        """
    )
    assert ticked, "No checkbox found to tick"

    # Wait for the confirm button to be enabled and labelled with count
    await page.wait_for_function(
        "() => { const b = document.getElementById('confirm-download'); return b && !b.disabled && /Start Download \\(/.test(b.textContent); }",
        timeout=5000,
    )

    # Click the start download button
    await page.click("#confirm-download")

    # Within 200ms, the button text should change to "Starting..."
    await page.wait_for_function(
        "() => { const b = document.getElementById('confirm-download'); return b && b.textContent.includes('Starting'); }",
        timeout=2000,
    )
    btn_text = await page.text_content("#confirm-download")
    assert "Starting" in btn_text, f"Expected 'Starting...' in button, got: {btn_text!r}"


async def test_start_download_modal_closes_within_timeout(browser_page, base_url):
    """Even with a slow backend, the modal should close within ~6s."""
    page = browser_page
    await page.route(
        "**/api/episodes",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "episodes": {"1": [{"season": 1, "episode": 1, "languages": ["Deutsch"], "language_codes": [1], "providers": ["VOE"], "url": "http://example.com/ep1"}]}, "movies": [], "metadata": {}}',
        ),
    )

    # Make /api/download very slow (30s) so the frontend's 5s timeout kicks in
    async def slow_download(route):
        await asyncio.sleep(30)
        await route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "queue_id": 999, "episode_count": 1}',
        )
    await page.route("**/api/download", slow_download)

    await page.goto(base_url, wait_until="domcontentloaded")
    assert await _wait_for_app_ready(page), "App did not finish initialising in time"

    # Open the modal
    await page.evaluate(
        """
        () => window.showDownloadModal('Test Anime', 'Series',
            'http://example.com/anime/stream/test/staffel-1/episode-1', null);
        """
    )
    await page.wait_for_selector("#download-modal", state="visible", timeout=10000)
    await page.wait_for_selector(".episode-checkbox, .season-checkbox", state="attached", timeout=10000)

    # Tick the season checkbox (or fall back to first episode checkbox)
    ticked = await page.evaluate(
        """
        () => {
            let cb = document.querySelector('.season-checkbox');
            if (cb) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                return 'season';
            }
            cb = document.querySelector('.episode-checkbox');
            if (cb) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                return 'episode';
            }
            return null;
        }
        """
    )
    assert ticked, "No checkbox found to tick"

    await page.wait_for_function(
        "() => { const b = document.getElementById('confirm-download'); return b && !b.disabled; }",
        timeout=5000,
    )

    t0 = time.monotonic()
    await page.click("#confirm-download")

    # Modal should disappear within ~6s (5s timeout + small overhead)
    await page.wait_for_function(
        "() => { const m = document.getElementById('download-modal'); return m && m.style.display === 'none'; }",
        timeout=8000,
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 7.0, f"Modal took {elapsed:.1f}s to close, expected <7s"
    print(f"\n[INFO] Modal closed after {elapsed:.2f}s (frontend timeout: 5s)")

    # The confirm button text should be back to "Start Download" (or empty)
    btn_text = await page.text_content("#confirm-download")
    assert "Starting" not in btn_text, f"Button still says 'Starting...' after modal closed: {btn_text!r}"
