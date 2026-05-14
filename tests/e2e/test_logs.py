"""E2E tests for the Log Viewer page in the new Ink UI."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_log_page_loads(page: Page, base_url: str) -> None:
    """Log Viewer page loads with filter controls."""
    page.goto(base_url + "/logs")
    expect(page.locator("body")).to_contain_text("logs")
    expect(page.locator("select[aria-label='Minimum log level']")).to_be_visible()
    expect(page.locator("input[aria-label='Search logs']")).to_be_visible()


def test_level_filter_options_present(page: Page, base_url: str) -> None:
    """Level filter select has all log level options."""
    page.goto(base_url + "/logs")
    level_select = page.locator("select[aria-label='Minimum log level']")
    expect(level_select).to_be_visible()
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        expect(level_select.locator(f"option[value='{level}']")).to_have_count(1)


def test_sort_column_headers_clickable(page: Page, base_url: str) -> None:
    """Timestamp column header has a sort button."""
    page.goto(base_url + "/logs")
    sort_button = page.locator("[data-testid='sort-timestamp'] button").first
    expect(sort_button).to_be_visible()
    sort_button.click()


def test_search_input_present(page: Page, base_url: str) -> None:
    """Search input is present and accepts text input."""
    page.goto(base_url + "/logs")
    search_input = page.locator("input[aria-label='Search logs']")
    expect(search_input).to_be_visible()
    search_input.fill("test query")
    expect(search_input).to_have_value("test query")


def _wait_for_log_entries(page: Page) -> None:
    """Wait for log table component to finish loading entries."""
    page.locator("text=/\\d+ entr/").wait_for(timeout=5000)


def test_log_entries_render_from_seed_data(page: Page, base_url: str) -> None:
    """Seeded log entries appear in the table body.

    The global logs page defaults to the 'app' tier filter, which hides
    framework-level logs (entries with no app_key). Switch to 'all' tier
    to verify both app and framework entries are present.
    """
    page.goto(base_url + "/logs?tier=all")
    _wait_for_log_entries(page)
    body = page.locator("tbody")
    expect(body).to_contain_text("Hassette started successfully")
    expect(body).to_contain_text("MyApp initialized")


def test_log_entries_show_error_level(page: Page, base_url: str) -> None:
    """ERROR level entries from seed data are visible."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    expect(page.locator("tbody")).to_contain_text("Failed to call service")


def test_level_filter_to_error_hides_info(page: Page, base_url: str) -> None:
    """Selecting ERROR level hides INFO entries."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    page.locator("select[aria-label='Minimum log level']").select_option("ERROR")
    page.wait_for_timeout(300)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Failed to call service")
    expect(tbody).not_to_contain_text("Hassette started successfully")
    expect(tbody).not_to_contain_text("MyApp initialized")


def test_search_filter_narrows_entries(page: Page, base_url: str) -> None:
    """Typing a search term filters visible log entries."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    search_input = page.locator("input[aria-label='Search logs']")
    search_input.fill("unresponsive")
    page.wait_for_timeout(500)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Light kitchen unresponsive")
    expect(tbody).not_to_contain_text("MyApp initialized")


# ──────────────────────────────────────────────────────────────────────
# Accessibility: expand button, filter aria labels
# ──────────────────────────────────────────────────────────────────────


def test_log_expand_button_toggles_message(page: Page, base_url: str) -> None:
    """Truncated log message cells are expandable via click."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    msg_cell = page.locator("td[data-testid='log-message-cell'][role='button']").first
    expect(msg_cell).to_be_attached()
    expect(msg_cell).to_have_attribute("aria-expanded", "false")
    expect(msg_cell).to_have_attribute("aria-label", "Expand log message")
    msg_cell.click()
    page.wait_for_timeout(200)
    expect(msg_cell).to_have_attribute("aria-expanded", "true")
    expect(msg_cell).to_have_attribute("aria-label", "Collapse log message")


def test_log_filter_controls_have_aria_labels(page: Page, base_url: str) -> None:
    """Log filter controls have accessible labels."""
    page.goto(base_url + "/logs")
    expect(page.locator("select[aria-label='Minimum log level']")).to_be_visible()
    expect(page.locator("input[aria-label='Search logs']")).to_be_visible()


# ──────────────────────────────────────────────────────────────────────
# Layout: column overflow regression guard
# ──────────────────────────────────────────────────────────────────────


def test_log_table_columns_do_not_visually_overlap(page: Page, base_url: str) -> None:
    """No table cell's bounding box overlaps its neighbor."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    overlaps = page.evaluate("""() => {
        const rows = document.querySelectorAll('[data-testid="log-table"] tbody tr');
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


# ──────────────────────────────────────────────────────────────────────
# Reactive truncation detection
# ──────────────────────────────────────────────────────────────────────


def test_truncation_affordance_appears_on_narrow_viewport(page: Page, base_url: str) -> None:
    """At narrow viewport, long messages gain the expand affordance."""
    page.set_viewport_size({"width": 800, "height": 600})
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    page.wait_for_timeout(500)
    expandable_cells = page.locator("td[data-testid='log-message-cell'][role='button']")
    expect(expandable_cells.first).to_be_attached()
    count = expandable_cells.count()
    assert count >= 1, f"Expected at least 1 expandable cell at narrow viewport, got {count}"


def test_truncation_affordance_disappears_on_wide_viewport(page: Page, base_url: str) -> None:
    """Widening viewport reduces text overflow in message cells."""
    page.set_viewport_size({"width": 800, "height": 600})
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    page.wait_for_timeout(500)

    expandable_cells = page.locator("td[data-testid='log-message-cell'][role='button']")
    narrow_count = expandable_cells.count()
    assert narrow_count >= 1, "Precondition failed: no expandable cells at narrow viewport"

    narrow_overflow = page.evaluate("""() => {
        const els = document.querySelectorAll('[data-row-key]');
        let maxOverflow = 0;
        els.forEach(el => {
            const overflow = el.scrollWidth - el.clientWidth;
            if (overflow > maxOverflow) maxOverflow = overflow;
        });
        return maxOverflow;
    }""")

    page.set_viewport_size({"width": 2400, "height": 600})
    page.wait_for_timeout(500)

    wide_overflow = page.evaluate("""() => {
        const els = document.querySelectorAll('[data-row-key]');
        let maxOverflow = 0;
        els.forEach(el => {
            const overflow = el.scrollWidth - el.clientWidth;
            if (overflow > maxOverflow) maxOverflow = overflow;
        });
        return maxOverflow;
    }""")

    assert wide_overflow < narrow_overflow, (
        f"Expected less text overflow after widening viewport (narrow={narrow_overflow}px, wide={wide_overflow}px)"
    )


def test_log_message_truncates_with_ellipsis(page: Page, base_url: str) -> None:
    """Long log messages have text-overflow: ellipsis."""
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    msg_text = page.locator("[data-row-key]").first
    overflow = msg_text.evaluate("el => getComputedStyle(el).overflow")
    white_space = msg_text.evaluate("el => getComputedStyle(el).whiteSpace")
    text_overflow = msg_text.evaluate("el => getComputedStyle(el).textOverflow")
    assert overflow in ("hidden", "clip"), f"Expected overflow:hidden or clip, got {overflow}"
    assert white_space == "nowrap", f"Expected white-space:nowrap, got {white_space}"
    assert text_overflow == "ellipsis", f"Expected text-overflow:ellipsis, got {text_overflow}"


# ──────────────────────────────────────────────────────────────────────
# App filter
# ──────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────
# Error toast (#556)
# ──────────────────────────────────────────────────────────────────────


def test_toast_appears_on_log_fetch_error(page: Page, base_url: str) -> None:
    """A sonner error toast appears when the log API returns a server error."""
    page.route("**/api/logs/recent*", lambda route: route.fulfill(status=500, body="Internal Server Error"))
    page.goto(base_url + "/logs")
    toast = page.locator("[data-sonner-toast][data-type='error']")
    expect(toast).to_be_visible(timeout=5000)


def test_toast_dismiss_via_close_button(page: Page, base_url: str) -> None:
    """Error toast can be dismissed by clicking its close button."""
    page.route("**/api/logs/recent*", lambda route: route.fulfill(status=500, body="Internal Server Error"))
    page.goto(base_url + "/logs")
    toast = page.locator("[data-sonner-toast][data-type='error']")
    expect(toast).to_be_visible(timeout=5000)
    page.locator("[data-sonner-toast] [data-close-button]").click()
    expect(toast).not_to_be_visible(timeout=5000)


# ──────────────────────────────────────────────────────────────────────
# App filter
# ──────────────────────────────────────────────────────────────────────


def test_log_table_app_column_hidden_at_mobile(page: Page, base_url: str) -> None:
    """Log table at mobile hides the App column and Source column."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(base_url + "/logs")
    _wait_for_log_entries(page)
    # At mobile (<768px), the App column header should be absent
    app_header = page.locator("th.ht-col-app")
    assert app_header.count() == 0, "Expected App column header to be absent at mobile viewport"
    # Source column should be hidden via CSS (display:none at <=1024px)
    source_header = page.locator("th.ht-col-source")
    expect(source_header).to_be_hidden()
