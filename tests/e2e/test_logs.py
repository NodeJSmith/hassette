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


def _wait_for_log_entries(page: Page) -> None:
    """Wait for Alpine.js logTable component to finish loading entries."""
    page.wait_for_function(
        """() => {
            const el = document.querySelector('[x-data*="logTable"]');
            if (!el || !el._x_dataStack) return false;
            const data = el._x_dataStack[0];
            return data && !data.loading && data.entries.length > 0;
        }""",
        timeout=5000,
    )


def test_log_entries_render_from_seed_data(page: Page, base_url: str) -> None:
    """Verify that seeded log entries appear in the table body."""
    page.goto(base_url + "/ui/logs")
    _wait_for_log_entries(page)
    body = page.locator("tbody")
    expect(body).to_contain_text("Hassette started successfully")
    expect(body).to_contain_text("MyApp initialized")


def test_log_entries_show_error_level(page: Page, base_url: str) -> None:
    """Verify ERROR level entries from seed data are visible."""
    page.goto(base_url + "/ui/logs")
    _wait_for_log_entries(page)
    body = page.locator("tbody")
    expect(body).to_contain_text("Failed to call service")


def test_level_filter_to_error_hides_info(page: Page, base_url: str) -> None:
    """Select ERROR filter, verify INFO entries are hidden."""
    page.goto(base_url + "/ui/logs")
    _wait_for_log_entries(page)
    # Select ERROR level
    page.locator("select[x-model='filters.level']").select_option("ERROR")
    # Wait for Alpine reactivity to filter
    page.wait_for_timeout(300)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Failed to call service")
    expect(tbody).not_to_contain_text("Hassette started successfully")
    expect(tbody).not_to_contain_text("MyApp initialized")


def test_search_filter_narrows_entries(page: Page, base_url: str) -> None:
    """Type a search term and verify only matching entries remain."""
    page.goto(base_url + "/ui/logs")
    _wait_for_log_entries(page)
    search_input = page.locator("input[placeholder='Search...']")
    search_input.fill("unresponsive")
    # Wait for debounce (200ms) + reactivity
    page.wait_for_timeout(500)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Light kitchen unresponsive")
    expect(tbody).not_to_contain_text("Hassette started successfully")
