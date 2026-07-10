"""E2E tests for the Cmd-K command palette in the new Ink UI."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ANIMATION_SETTLE_MS, DATA_LOAD_TIMEOUT_MS

pytestmark = pytest.mark.e2e


def open_palette(page: Page) -> None:
    """Open the command palette via Ctrl+K."""
    page.keyboard.press("Control+k")
    expect(page.locator("[role='dialog'][aria-label='Command palette']")).to_be_visible()


def test_cmd_k_opens_palette(page: Page, base_url: str) -> None:
    """Ctrl+K opens the command palette dialog."""
    page.goto(base_url + "/")
    open_palette(page)


def test_meta_k_opens_palette(page: Page, base_url: str) -> None:
    """Meta+K (Mac Cmd) also opens the command palette."""
    page.goto(base_url + "/")
    page.keyboard.press("Meta+k")
    # Either Ctrl or Meta opens it — just verify dialog appears
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    expect(palette).to_be_visible()


def test_palette_has_search_input(page: Page, base_url: str) -> None:
    """Command palette has a search input field."""
    page.goto(base_url + "/")
    open_palette(page)
    search = page.locator("input[aria-label='Search command palette']")
    expect(search).to_be_visible()
    expect(search).to_be_focused()


def test_palette_shows_page_items(page: Page, base_url: str) -> None:
    """Command palette lists static page navigation items."""
    page.goto(base_url + "/")
    open_palette(page)
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    # Static page items from buildStaticPageItems
    expect(palette).to_contain_text("apps")
    expect(palette).to_contain_text("logs")
    expect(palette).to_contain_text("config")


def test_palette_shows_app_items(page: Page, base_url: str) -> None:
    """Command palette lists app items from seed data."""
    page.goto(base_url + "/")
    open_palette(page)
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    # App items from seed data (display names)
    expect(palette).to_contain_text("My App")


def test_palette_search_filters_items(page: Page, base_url: str) -> None:
    """Typing in the search input filters the results."""
    page.goto(base_url + "/")
    open_palette(page)
    search = page.locator("input[aria-label='Search command palette']")
    search.fill("logs")
    page.wait_for_timeout(200)
    # "Logs" page item should match
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    expect(palette).to_contain_text("logs")
    # "apps" should not match "logs" query
    expect(palette).not_to_contain_text("/apps")


def test_palette_empty_state_for_no_match(page: Page, base_url: str) -> None:
    """Searching for a nonsense query shows the empty state."""
    page.goto(base_url + "/")
    open_palette(page)
    search = page.locator("input[aria-label='Search command palette']")
    search.fill("zzzznonexistentxxx")
    page.wait_for_timeout(200)
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    empty = palette.locator("[data-testid='cmd-palette-empty']")
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("No results for")


def test_palette_closes_on_escape(page: Page, base_url: str) -> None:
    """Pressing Escape closes the command palette."""
    page.goto(base_url + "/")
    open_palette(page)
    page.keyboard.press("Escape")
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    expect(palette).to_have_count(0)


def test_palette_closes_on_backdrop_click(page: Page, base_url: str) -> None:
    """Clicking the backdrop closes the command palette."""
    page.goto(base_url + "/")
    open_palette(page)
    backdrop = page.locator("[data-testid='cmd-palette-backdrop']")
    expect(backdrop).to_be_visible()
    backdrop.click(position={"x": 10, "y": 10})
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    expect(palette).to_have_count(0)


def test_palette_navigates_to_logs_on_select(page: Page, base_url: str) -> None:
    """Selecting the Logs page item navigates to /logs."""
    page.goto(base_url + "/")
    open_palette(page)
    # Type to narrow to "Logs"
    search = page.locator("input[aria-label='Search command palette']")
    search.fill("logs")
    page.wait_for_timeout(200)
    # Click the logs result
    logs_result = page.locator("[role='option']", has_text="logs").first
    expect(logs_result).to_be_visible()
    logs_result.click()
    expect(page).to_have_url(re.compile(r"/logs"))
    expect(page.locator("[data-testid='log-table']")).to_be_visible()


def test_palette_keyboard_navigation(page: Page, base_url: str) -> None:
    """Arrow keys navigate through palette results."""
    page.goto(base_url + "/")
    open_palette(page)
    palette = page.locator("[role='dialog'][aria-label='Command palette']")
    # Wait for options to render before pressing ArrowDown
    palette.locator("[role='option']").first.wait_for(timeout=DATA_LOAD_TIMEOUT_MS)
    page.keyboard.press("ArrowDown")
    # First result should now be active (aria-selected=true)
    active = palette.locator("[role='option'][aria-selected='true']")
    expect(active).to_have_count(1)


def test_palette_navigates_to_app_on_select(page: Page, base_url: str) -> None:
    """Selecting an app item in the palette navigates to app detail."""
    page.goto(base_url + "/")
    open_palette(page)
    search = page.locator("input[aria-label='Search command palette']")
    search.fill("My App")
    page.wait_for_timeout(ANIMATION_SETTLE_MS)
    app_result = page.locator("[role='option']", has_text="My App").first
    expect(app_result).to_be_visible()
    app_result.click()
    expect(page).to_have_url(re.compile(r"/apps/my_app"))
