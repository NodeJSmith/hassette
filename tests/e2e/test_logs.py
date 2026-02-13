"""E2E tests for the Log Viewer page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_log_page_loads(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/logs")
    expect(page.locator("body")).to_contain_text("Log Viewer")
    # Verify the Alpine.js logTable component initializes (filter controls are present)
    expect(page.locator("select[x-model='filters.level']")).to_be_visible()
    expect(page.locator("input[placeholder='Search...']")).to_be_visible()


def test_level_filter_options_present(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/logs")
    level_select = page.locator("select[x-model='filters.level']")
    expect(level_select).to_be_visible()
    # Verify all log level options exist
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        expect(level_select.locator(f"option[value='{level}']")).to_have_count(1)


def test_sort_column_headers_clickable(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/logs")
    # The Level column header should be clickable (has @click="toggleSort('level')")
    level_header = page.locator("th:has-text('Level')").first
    expect(level_header).to_be_visible()
    # Click to toggle sort - should not error
    level_header.click()
    # The sort icon should be present
    expect(level_header.locator("i.fas")).to_be_visible()


def test_search_input_present(page: Page, base_url: str) -> None:
    page.goto(base_url + "/ui/logs")
    search_input = page.locator("input[placeholder='Search...']")
    expect(search_input).to_be_visible()
    # Type into the search field - should not error
    search_input.fill("test query")
    expect(search_input).to_have_value("test query")
