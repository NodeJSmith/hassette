"""E2E tests for the Log Viewer page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_log_page_loads(page: Page, base_url: str) -> None:
    page.goto(base_url + "/logs")
    expect(page.locator("body")).to_contain_text("Log Viewer")
    # Verify the log table component initializes (filter controls are present)
    expect(page.locator("select").first).to_be_visible()
    expect(page.locator("input[placeholder='Search...']")).to_be_visible()


def test_level_filter_options_present(page: Page, base_url: str) -> None:
    page.goto(base_url + "/logs")
    level_select = page.locator("select").first
    expect(level_select).to_be_visible()
    # Verify all log level options exist
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        expect(level_select.locator(f"option[value='{level}']")).to_have_count(1)


def test_sort_column_headers_clickable(page: Page, base_url: str) -> None:
    page.goto(base_url + "/logs")
    # The Timestamp column header has a sort button inside it
    sort_button = page.locator("[data-testid='sort-timestamp'] button").first
    expect(sort_button).to_be_visible()
    # Click to toggle sort - should not error
    sort_button.click()


def test_search_input_present(page: Page, base_url: str) -> None:
    page.goto(base_url + "/logs")
    search_input = page.locator("input[placeholder='Search...']")
    expect(search_input).to_be_visible()
    # Type into the search field - should not error
    search_input.fill("test query")
    expect(search_input).to_have_value("test query")


def _wait_for_log_entries(page: Page) -> None:
    """Wait for log table component to finish loading entries."""
    page.locator("text=/\\d+ entries/").wait_for(timeout=5000)


def test_log_entries_render_from_seed_data(page: Page, base_url: str) -> None:
    """Verify that seeded log entries appear in the table body."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    body = page.locator("tbody")
    expect(body).to_contain_text("Hassette started successfully")
    expect(body).to_contain_text("MyApp initialized")


def test_log_entries_show_error_level(page: Page, base_url: str) -> None:
    """Verify ERROR level entries from seed data are visible."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    body = page.locator("tbody")
    expect(body).to_contain_text("Failed to call service")


def test_level_filter_to_error_hides_info(page: Page, base_url: str) -> None:
    """Select ERROR filter, verify INFO entries are hidden."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    # Select ERROR level
    page.locator("select").first.select_option("ERROR")
    # Wait for Preact reactivity to filter
    page.wait_for_timeout(300)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Failed to call service")
    expect(tbody).not_to_contain_text("Hassette started successfully")
    expect(tbody).not_to_contain_text("MyApp initialized")


def test_search_filter_narrows_entries(page: Page, base_url: str) -> None:
    """Type a search term and verify only matching entries remain."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    search_input = page.locator("input[placeholder='Search...']")
    search_input.fill("unresponsive")
    # Wait for reactivity
    page.wait_for_timeout(500)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Light kitchen unresponsive")
    expect(tbody).not_to_contain_text("Hassette started successfully")


# ──────────────────────────────────────────────────────────────────────
# Accessibility: expand button, filter aria labels
# ──────────────────────────────────────────────────────────────────────


def test_log_expand_button_toggles_message(page: Page, base_url: str) -> None:
    """Log rows have an expand button that toggles aria-expanded."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    # Find the first expand button
    expand_btn = page.locator("button.ht-log-expand-btn").first
    expect(expand_btn).to_be_attached()
    expect(expand_btn).to_have_attribute("aria-expanded", "false")
    # The button has an accessible label
    expect(expand_btn).to_have_attribute(
        "aria-label",
        "Expand log message",
    )
    # Click to expand (hover first since button uses opacity:0)
    expand_btn.click(force=True)
    page.wait_for_timeout(200)
    expect(expand_btn).to_have_attribute("aria-expanded", "true")
    expect(expand_btn).to_have_attribute(
        "aria-label",
        "Collapse log message",
    )


def test_log_filter_controls_have_aria_labels(
    page: Page,
    base_url: str,
) -> None:
    """Log filter controls have accessible labels."""
    page.goto(base_url + "/logs")
    expect(
        page.locator("select[aria-label='Minimum log level']"),
    ).to_be_visible()
    expect(
        page.locator("input[aria-label='Search log messages']"),
    ).to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Layout: column overflow regression guard
# ──────────────────────────────────────────────────────────────────────


def test_log_table_columns_do_not_visually_overlap(page: Page, base_url: str) -> None:
    """No table cell's bounding box overlaps its neighbor.

    Regression guard: the Source column previously bled into Message
    because overflow:hidden was missing on the fixed-width cell.
    Uses bounding-box comparison instead of scrollWidth/clientWidth
    (which false-positives on intentionally truncated cells).
    """
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    # Compare adjacent cell bounding boxes in the first 5 data rows
    overlaps = page.evaluate("""() => {
        const rows = document.querySelectorAll('.ht-table-log tbody tr');
        const problems = [];
        for (let i = 0; i < Math.min(rows.length, 5); i++) {
            const cells = Array.from(rows[i].querySelectorAll('td'));
            for (let j = 0; j < cells.length - 1; j++) {
                const a = cells[j].getBoundingClientRect();
                const b = cells[j + 1].getBoundingClientRect();
                const overlap = a.right - b.left;
                if (overlap > 1) {
                    const msg = `Row ${i}: col ${j} right=${a.right.toFixed(0)}`
                        + ` overlaps col ${j+1} left=${b.left.toFixed(0)}`
                        + ` by ${overlap.toFixed(0)}px`;
                    problems.push(msg);
                }
            }
        }
        return problems;
    }""")
    assert overlaps == [], f"Column visual overlap detected: {overlaps}"


def test_source_column_has_overflow_hidden(page: Page, base_url: str) -> None:
    """Source column cells have overflow:hidden to prevent text bleed."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    source_cell = page.locator("td.ht-col-source").first
    overflow = source_cell.evaluate("el => getComputedStyle(el).overflow")
    text_overflow = source_cell.evaluate("el => getComputedStyle(el).textOverflow")
    assert overflow == "hidden", f"Expected overflow:hidden on .ht-col-source, got {overflow}"
    assert text_overflow == "ellipsis", f"Expected text-overflow:ellipsis, got {text_overflow}"


def test_log_message_truncates_with_ellipsis(page: Page, base_url: str) -> None:
    """Long log messages are truncated to one line with text-overflow: ellipsis."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    # Find a message cell and verify the text element has overflow hidden + ellipsis
    msg_text = page.locator(".ht-log-message__text").first
    overflow = msg_text.evaluate("el => getComputedStyle(el).overflow")
    white_space = msg_text.evaluate("el => getComputedStyle(el).whiteSpace")
    text_overflow = msg_text.evaluate("el => getComputedStyle(el).textOverflow")
    assert overflow == "hidden", f"Expected overflow:hidden, got {overflow}"
    assert white_space == "nowrap", f"Expected white-space:nowrap, got {white_space}"
    assert text_overflow == "ellipsis", f"Expected text-overflow:ellipsis, got {text_overflow}"
