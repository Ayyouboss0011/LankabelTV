"""
Test 1: Smoke test - the UI loads, the home page renders, and
basic UI elements are present and responsive.

This test does NOT start any downloads. It just verifies that the
front-end boots up correctly and is interactive.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_ui_loads_and_shows_home(browser_page, base_url):
    """The web UI should load and show the home tab by default."""
    page = browser_page
    await page.goto(base_url, wait_until="domcontentloaded")

    # Title should be LankabelTV
    title = await page.title()
    assert "LankabelTV" in title, f"Expected 'LankabelTV' in title, got: {title!r}"

    # Brand and tab buttons should be present
    brand = await page.text_content(".nav-brand, .brand, #nav-logo")
    assert brand is not None, "Brand element not found"

    # Tabs should be present
    home_tab = await page.query_selector("#tab-home")
    downloads_tab = await page.query_selector("#tab-downloads")
    assert home_tab is not None, "Home tab not found"
    assert downloads_tab is not None, "Downloads tab not found"

    # Search input should be present
    search = await page.query_selector("#search-input")
    assert search is not None, "Search input not found"


async def test_switch_to_downloads_tab(browser_page, base_url):
    """The Downloads tab should be clickable and show the downloads view."""
    page = browser_page
    await page.goto(base_url, wait_until="domcontentloaded")
    await page.click("#tab-downloads")
    # Give the JS a moment to switch the visible view
    await page.wait_for_timeout(300)

    downloads_view = await page.query_selector("#downloads-view")
    assert downloads_view is not None, "Downloads view not found"

    # The downloads view should be visible (display != 'none')
    is_visible = await downloads_view.is_visible()
    assert is_visible, "Downloads view is not visible after clicking the tab"


async def test_search_input_accepts_typing(browser_page, base_url):
    """The search input should accept text and not be locked."""
    page = browser_page
    await page.goto(base_url, wait_until="domcontentloaded")
    search = await page.wait_for_selector("#search-input", timeout=5000)
    await search.click()
    await search.fill("test-anime")
    value = await search.input_value()
    assert value == "test-anime", f"Search input did not accept text, value={value!r}"
