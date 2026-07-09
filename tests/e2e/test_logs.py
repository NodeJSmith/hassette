"""E2E tests for the Log Viewer page in the new Ink UI."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_log_page_loads(page: Page, base_url: str) -> None:
    """Log Viewer page loads with log table and search input."""
    page.goto(base_url + "/logs")
    expect(page.locator("body")).to_contain_text("logs")
    expect(page.locator("[data-testid='log-table']")).to_be_visible()
    expect(page.locator("input[aria-label='Search logs']")).to_be_visible()


def test_level_filter_options_present(page: Page, base_url: str) -> None:
    """Level filter select has all log level options."""
    page.goto(base_url + "/logs")
    # The level filter is inside a popover — open it first
    page.locator("[data-testid='sort-level'] [data-testid='filter-btn']").click()
    level_select = page.locator("[data-testid='filter-level']")
    expect(level_select).to_be_visible()
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        expect(level_select.locator(f"option[value='{level}']")).to_have_count(1)


def test_sort_column_headers_clickable(page: Page, base_url: str) -> None:
    """Timestamp column header has a sort button."""
    page.goto(base_url + "/logs")
    # data-testid="sort-timestamp" IS the button itself in the new architecture
    sort_button = page.locator("[data-testid='sort-timestamp']").first
    expect(sort_button).to_be_visible()
    sort_button.click()


def test_search_input_present(page: Page, base_url: str) -> None:
    """Search input is present and accepts text input."""
    page.goto(base_url + "/logs")
    search_input = page.locator("input[aria-label='Search logs']")
    expect(search_input).to_be_visible()
    search_input.fill("test query")
    expect(search_input).to_have_value("test query")


def wait_for_log_entries(page: Page) -> None:
    """Wait for log table component to finish loading entries."""
    # Footer shows either "N entries" / "N entry" or "showing 500 of N"
    page.locator("text=/\\d+ entr|showing \\d+/").wait_for(timeout=5000)


def test_log_entries_render_from_seed_data(page: Page, base_url: str) -> None:
    """Seeded log entries appear in the table body.

    The global logs page defaults to the 'app' tier filter, which hides
    framework-level logs (entries with no app_key). Switch to 'all' tier
    to verify both app and framework entries are present.
    """
    page.goto(base_url + "/logs?tier=all")
    wait_for_log_entries(page)
    body = page.locator("tbody")
    expect(body).to_contain_text("Hassette started successfully")
    expect(body).to_contain_text("MyApp initialized")


def test_log_entries_show_error_level(page: Page, base_url: str) -> None:
    """ERROR level entries from seed data are visible."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    expect(page.locator("tbody")).to_contain_text("Failed to call service")


def test_level_filter_to_error_hides_info(page: Page, base_url: str) -> None:
    """Selecting ERROR level hides INFO entries."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    # Level filter is behind a popover — open it first
    page.locator("[data-testid='sort-level'] [data-testid='filter-btn']").click()
    page.locator("[data-testid='filter-level']").select_option("ERROR")
    # Close popover by clicking elsewhere
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Failed to call service")
    expect(tbody).not_to_contain_text("Hassette started successfully")
    expect(tbody).not_to_contain_text("MyApp initialized")


def test_search_filter_narrows_entries(page: Page, base_url: str) -> None:
    """Typing a search term filters visible log entries."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    search_input = page.locator("input[aria-label='Search logs']")
    search_input.fill("unresponsive")
    page.wait_for_timeout(500)
    tbody = page.locator("tbody")
    expect(tbody).to_contain_text("Light kitchen unresponsive")
    expect(tbody).not_to_contain_text("MyApp initialized")


def test_log_expand_button_toggles_message(page: Page, base_url: str) -> None:
    """Clicking a log row opens the detail drawer; close button dismisses it."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    # Rows have role="button" — click the first to open the detail drawer
    first_row = page.locator("[data-testid='log-table'] tbody tr").first
    expect(first_row).to_be_visible()
    first_row.click()
    page.wait_for_timeout(200)
    drawer = page.locator("aside[role='complementary'][aria-label='Log entry detail']")
    expect(drawer).to_be_visible()
    # Close the drawer via the close button
    page.locator("button[aria-label='Close detail panel']").click()
    page.wait_for_timeout(200)
    expect(drawer).not_to_be_attached()


def test_log_filter_controls_have_aria_labels(page: Page, base_url: str) -> None:
    """Log filter controls have accessible labels."""
    page.goto(base_url + "/logs")
    expect(page.locator("[data-testid='sort-level'] [data-testid='filter-btn']")).to_be_visible()
    expect(page.locator("input[aria-label='Search logs']")).to_be_visible()


def test_log_table_columns_do_not_visually_overlap(page: Page, base_url: str) -> None:
    """No table cell's bounding box overlaps its neighbor."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
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
    """Function column cells have overflow:hidden to prevent text bleed."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    # Check the message cell td which has overflow:hidden via the .messageCell CSS module class
    msg_cell = page.locator("[data-testid='log-table'] tbody tr:first-child td:last-child").first
    overflow = msg_cell.evaluate("el => getComputedStyle(el).overflow")
    assert overflow == "hidden", f"Expected overflow:hidden on message cell, got {overflow}"


def test_truncation_affordance_appears_on_narrow_viewport(page: Page, base_url: str) -> None:
    """At narrow viewport, message text div has text-overflow: ellipsis."""
    page.set_viewport_size({"width": 800, "height": 600})
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    page.wait_for_timeout(500)
    # The messageText div has text-overflow: ellipsis — verify at least one exists
    msg_text_div = page.locator("[data-testid='log-table'] tbody tr:first-child td:last-child div").first
    expect(msg_text_div).to_be_attached()
    text_overflow = msg_text_div.evaluate("el => getComputedStyle(el).textOverflow")
    assert text_overflow == "ellipsis", f"Expected text-overflow:ellipsis on messageText, got {text_overflow}"


def test_truncation_affordance_disappears_on_wide_viewport(page: Page, base_url: str) -> None:
    """Widening viewport reduces text overflow in message cells."""
    page.set_viewport_size({"width": 800, "height": 600})
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    page.wait_for_timeout(500)

    # Measure scroll overflow on message text divs at narrow viewport
    narrow_overflow = page.evaluate("""() => {
        const els = document.querySelectorAll('[data-testid="log-table"] tbody tr td:last-child div');
        let maxOverflow = 0;
        els.forEach(el => {
            const overflow = el.scrollWidth - el.clientWidth;
            if (overflow > maxOverflow) maxOverflow = overflow;
        });
        return maxOverflow;
    }""")

    page.set_viewport_size({"width": 2400, "height": 600})
    page.wait_for_timeout(500)

    # Measure scroll overflow at wide viewport
    wide_overflow = page.evaluate("""() => {
        const els = document.querySelectorAll('[data-testid="log-table"] tbody tr td:last-child div');
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
    """Long log messages have text-overflow: ellipsis in the messageText div."""
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    # The .messageText div (last td, first div) has overflow:clip, white-space:nowrap, text-overflow:ellipsis
    msg_text = page.locator("[data-testid='log-table'] tbody tr:first-child td:last-child div").first
    overflow = msg_text.evaluate("el => getComputedStyle(el).overflow")
    white_space = msg_text.evaluate("el => getComputedStyle(el).whiteSpace")
    text_overflow = msg_text.evaluate("el => getComputedStyle(el).textOverflow")
    assert overflow in ("hidden", "clip"), f"Expected overflow:hidden or clip, got {overflow}"
    assert white_space == "nowrap", f"Expected white-space:nowrap, got {white_space}"
    assert text_overflow == "ellipsis", f"Expected text-overflow:ellipsis, got {text_overflow}"


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


def test_log_table_app_column_hidden_at_mobile(page: Page, base_url: str) -> None:
    """Log table at mobile hides the App and Function columns (viewport filter)."""
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(base_url + "/logs")
    wait_for_log_entries(page)
    # At mobile (<768px), app/instance/execution/function/module columns are not rendered
    # Verify by checking that no thead th with text "App" exists
    thead = page.locator("[data-testid='log-table'] thead")
    app_headers = thead.locator("th").filter(has_text="App")
    assert app_headers.count() == 0, "Expected App column header to be absent at mobile viewport"
    # Function column ("Function") should also be absent
    fn_headers = thead.locator("th").filter(has_text="Function")
    assert fn_headers.count() == 0, "Expected Function column header to be absent at mobile viewport"
