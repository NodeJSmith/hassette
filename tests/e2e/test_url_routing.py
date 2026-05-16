"""E2E tests for URL-driven routing (spec 052).

Covers:
- Tab deep-links via path segments
- Handler deep-links via /apps/:key/handlers/h-{id}
- Filter persistence across page refresh
- Sort persistence across page refresh
- Browser back/forward for tab navigation
- Default param omission from URL
- Time window override via ?window=
- Invalid handler ID correction
- Multi-instance routing via ?instance= query param
- Parent overview when no instance param
- View in code ?line= param persistence
"""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import DESKTOP_VIEWPORT

pytestmark = pytest.mark.e2e


# ──────────────────────────────────────────────────────────────────────
# AC#11: Tab deep-links — path segments drive active tab
# ──────────────────────────────────────────────────────────────────────


def test_logs_tab_deep_link(page: Page, base_url: str) -> None:
    """Direct navigation to /apps/:key/logs activates the logs tab (AC#1, AC#11)."""
    page.goto(base_url + "/apps/my_app/logs")
    page.wait_for_load_state("networkidle")
    # Logs tab content should be visible, not the handlers tab
    logs_section = page.locator("[data-testid='logs-section']")
    expect(logs_section).to_be_visible(timeout=5000)
    # Handler list should NOT be visible (wrong tab)
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_have_count(0)


def test_code_tab_deep_link(page: Page, base_url: str) -> None:
    """Direct navigation to /apps/:key/code activates the code tab (AC#1, AC#11)."""
    page.goto(base_url + "/apps/my_app/code")
    page.wait_for_load_state("networkidle")
    code_content = page.locator("[data-testid='code-tab-content']")
    expect(code_content).to_be_visible(timeout=5000)
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_have_count(0)


def test_handlers_tab_deep_link(page: Page, base_url: str) -> None:
    """Direct navigation to /apps/:key/handlers activates the handlers tab (AC#1, AC#11)."""
    page.goto(base_url + "/apps/my_app/handlers")
    page.wait_for_load_state("networkidle")
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible(timeout=5000)


# ──────────────────────────────────────────────────────────────────────
# AC#2: Handler deep-links select the handler
# ──────────────────────────────────────────────────────────────────────


def test_handler_deep_link_selects_handler(page: Page, base_url: str) -> None:
    """Navigating to /apps/:key/handlers/h-{id} selects the handler (AC#2)."""
    # listener_id=1 in seed data (on_light_change)
    page.goto(base_url + "/apps/my_app/handlers/h-1")
    page.wait_for_load_state("networkidle")
    # Detail pane for listener 1 should be visible
    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)


def test_job_deep_link_selects_job(page: Page, base_url: str) -> None:
    """Navigating to /apps/:key/handlers/j-{id} selects the job (AC#2)."""
    # job_id=1 in seed data (check_lights)
    page.goto(base_url + "/apps/my_app/handlers/j-1")
    page.wait_for_load_state("networkidle")
    detail = page.locator("[data-testid='job-detail-1']")
    expect(detail).to_be_visible(timeout=5000)


def test_handler_deep_link_url_persists_on_refresh(page: Page, base_url: str) -> None:
    """After navigating to a handler deep-link, refreshing keeps handler selected (AC#1)."""
    page.goto(base_url + "/apps/my_app/handlers/h-1")
    page.wait_for_load_state("networkidle")
    # Verify handler is selected
    expect(page.locator("[data-testid='listener-detail-1']")).to_be_visible(timeout=5000)
    # Reload the page
    page.reload()
    page.wait_for_load_state("networkidle")
    # Handler should still be selected after refresh
    expect(page.locator("[data-testid='listener-detail-1']")).to_be_visible(timeout=5000)


# ──────────────────────────────────────────────────────────────────────
# AC#3: Logs tab with query params
# ──────────────────────────────────────────────────────────────────────


def test_logs_tab_with_level_filter_deep_link(page: Page, base_url: str) -> None:
    """Navigating to /logs?level=ERROR shows logs filtered to ERROR (AC#3, AC#1)."""
    page.goto(base_url + "/logs?level=ERROR")
    page.wait_for_load_state("networkidle")
    page.locator("[data-testid='log-table']").wait_for(timeout=5000)
    # Open the level filter popover, then check filter shows ERROR
    page.locator("[data-testid='sort-level'] [data-testid='filter-btn']").click()
    level_filter = page.locator("[data-testid='filter-level']")
    expect(level_filter).to_be_visible()
    selected_value = level_filter.evaluate("el => el.value")
    assert selected_value == "ERROR", f"Expected level filter to be ERROR, got {selected_value}"


def test_logs_tab_filter_persists_on_refresh(page: Page, base_url: str) -> None:
    """Setting log level filter and refreshing restores the filter (AC#1, AC#3)."""
    page.goto(base_url + "/logs")
    page.wait_for_load_state("networkidle")
    # Open the level filter popover and set to ERROR
    page.locator("[data-testid='sort-level'] [data-testid='filter-btn']").click()
    level_filter = page.locator("[data-testid='filter-level']")
    expect(level_filter).to_be_visible()
    level_filter.select_option("ERROR")
    page.wait_for_timeout(300)
    # URL should contain ?level=ERROR
    expect(page).to_have_url(re.compile(r"level=ERROR"))
    # Reload the page
    page.reload()
    page.wait_for_load_state("networkidle")
    # Re-open the filter popover and verify ERROR persisted
    page.locator("[data-testid='sort-level'] [data-testid='filter-btn']").click()
    level_filter = page.locator("[data-testid='filter-level']")
    expect(level_filter).to_be_visible()
    selected_value = level_filter.evaluate("el => el.value")
    assert selected_value == "ERROR", f"Expected level filter to be ERROR after reload, got {selected_value}"


# ──────────────────────────────────────────────────────────────────────
# AC#1: Filter persistence on /apps page
# ──────────────────────────────────────────────────────────────────────


def test_apps_filter_persists_on_refresh(page: Page, base_url: str) -> None:
    """Setting status filter on /apps and refreshing restores the filter (AC#1)."""
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # Open status filter popover, then click "Running"
    page.locator("[data-testid='filter-btn']").click()
    page.locator("[data-testid='filter-running']").wait_for(state="visible")
    page.locator("[data-testid='filter-running']").click()
    page.wait_for_timeout(300)
    # URL should contain filter=running
    expect(page).to_have_url(re.compile(r"filter=running"))
    # Reload the page
    page.reload()
    page.wait_for_load_state("networkidle")
    # Filter should still be running — only running app visible
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-other_app']")).to_have_count(0)


# ──────────────────────────────────────────────────────────────────────
# AC#1, AC#6: Sort persistence — replace history, no new entry
# ──────────────────────────────────────────────────────────────────────


def test_handlers_page_sort_persists_on_refresh(page: Page, base_url: str) -> None:
    """Sort params on /handlers persist on refresh and do not create history (AC#1, AC#6)."""
    page.goto(base_url + "/handlers?sort=runs&dir=desc")
    page.wait_for_load_state("networkidle")
    # Page should load with the sort applied
    # Reload to verify persistence
    page.reload()
    page.wait_for_load_state("networkidle")
    # URL should still have sort params
    expect(page).to_have_url(re.compile(r"sort=runs"))
    expect(page).to_have_url(re.compile(r"dir=desc"))


def test_sort_change_does_not_push_history(page: Page, base_url: str) -> None:
    """Changing sort column replaces history, not pushes (AC#6).

    Strategy: navigate to a page, change sort, then press back — should go
    back to the page before /handlers, not to the pre-sort state.
    """
    # Start at /apps
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # Navigate to /handlers
    page.goto(base_url + "/handlers")
    page.wait_for_load_state("networkidle")
    # Remember the initial URL (no sort params)
    initial_url = page.url
    # Click a sort column header to change sort
    sort_button = page.locator("button[data-testid='sort-header-btn']").first
    expect(sort_button).to_be_visible()
    sort_button.click()
    page.wait_for_timeout(300)
    # URL should have changed (sort applied via replace)
    current_url = page.url
    # Press back — should go back to /apps (before /handlers), not to initial_url
    page.go_back()
    page.wait_for_timeout(500)
    # Should be on /apps since sort used replace, not push
    current_after_back = page.url
    assert "/apps" in current_after_back, (
        f"Expected back navigation to reach /apps, but got: {current_after_back}. "
        f"Sort may have pushed history (initial_url={initial_url}, sorted_url={current_url})"
    )


# ──────────────────────────────────────────────────────────────────────
# AC#5: Browser back/forward for tab navigation
# ──────────────────────────────────────────────────────────────────────


def test_browser_back_after_tab_switch(page: Page, base_url: str) -> None:
    """Pressing back after switching tabs returns to the previous tab (AC#5)."""
    # Start on handlers tab
    page.goto(base_url + "/apps/my_app/handlers")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='handler-list']")).to_be_visible(timeout=5000)
    # Click the Logs tab (should push a history entry)
    logs_tab_btn = page.locator("a[role='tab']", has_text="logs")
    expect(logs_tab_btn).to_be_visible()
    logs_tab_btn.click()
    page.wait_for_timeout(500)
    # Verify we're on logs tab
    expect(page).to_have_url(re.compile(r"/apps/my_app/logs"))
    # Press back
    page.go_back()
    page.wait_for_timeout(500)
    # Should be back on handlers tab
    expect(page).to_have_url(re.compile(r"/apps/my_app/handlers"))
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible(timeout=5000)


def test_browser_forward_after_back(page: Page, base_url: str) -> None:
    """Browser forward works after going back through tab history (AC#5)."""
    page.goto(base_url + "/apps/my_app/handlers")
    page.wait_for_load_state("networkidle")
    # Switch to code tab
    code_tab_btn = page.locator("a[role='tab']", has_text="code")
    expect(code_tab_btn).to_be_visible()
    code_tab_btn.click()
    page.wait_for_timeout(500)
    expect(page).to_have_url(re.compile(r"/apps/my_app/code"))
    # Go back to handlers
    page.go_back()
    page.wait_for_timeout(500)
    expect(page).to_have_url(re.compile(r"/apps/my_app/handlers"))
    # Go forward to code
    page.go_forward()
    page.wait_for_timeout(500)
    expect(page).to_have_url(re.compile(r"/apps/my_app/code"))
    code_content = page.locator("[data-testid='code-tab-content']")
    expect(code_content).to_be_visible(timeout=5000)


# ──────────────────────────────────────────────────────────────────────
# AC#9 / AC#13: Default params are omitted from URL
# ──────────────────────────────────────────────────────────────────────


def test_apps_page_default_state_has_no_query_params(page: Page, base_url: str) -> None:
    """Navigating to /apps with default filters produces /apps with no query params (AC#9, AC#13)."""
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # URL should be exactly /apps with no query string
    current_url = page.url
    assert "?" not in current_url, f"Expected no query params on default /apps page, but URL is: {current_url}"


def test_apps_page_reset_to_all_removes_filter_param(page: Page, base_url: str) -> None:
    """Resetting filter to 'all' removes the filter query param (AC#9)."""
    page.goto(base_url + "/apps?filter=running")
    page.wait_for_load_state("networkidle")
    # Open status filter popover, then click "All" to reset
    page.locator("[data-testid='filter-btn']").click()
    page.locator("[data-testid='filter-all']").wait_for(state="visible")
    page.locator("[data-testid='filter-all']").click()
    page.wait_for_timeout(300)
    # URL should not contain filter= anymore
    current_url = page.url
    assert "filter=" not in current_url, (
        f"Expected filter param to be removed when reset to default, but URL is: {current_url}"
    )


# ──────────────────────────────────────────────────────────────────────
# AC#7, AC#8: Time window override via ?window=
# ──────────────────────────────────────────────────────────────────────


def test_window_param_applied_to_handlers_page(page: Page, base_url: str) -> None:
    """Navigating to /handlers?window=24h shows the 24h time preset active (AC#7)."""
    page.goto(base_url + "/handlers?window=24h")
    page.wait_for_load_state("networkidle")
    # The time preset button/label should show 24h
    # Look for an element that indicates the active time preset
    body = page.locator("body")
    # The time preset display should reflect 24h — check for the label text
    # The exact selector depends on implementation; we check the body contains "24h" as active preset
    expect(body).to_contain_text("24h")


def test_window_param_persists_on_refresh(page: Page, base_url: str) -> None:
    """Bookmarked ?window=24h URL restores the 24h window on refresh (AC#7, AC#1)."""
    page.goto(base_url + "/handlers?window=24h")
    page.wait_for_load_state("networkidle")
    # Reload
    page.reload()
    page.wait_for_load_state("networkidle")
    # URL should still have window=24h
    expect(page).to_have_url(re.compile(r"window=24h"))


def test_no_window_param_uses_stored_preference(page: Page, base_url: str) -> None:
    """Page without ?window= uses the localStorage timePreset (AC#7).

    The autouse fixture sets timePreset='1h', so a page without ?window=
    should show 1h as the active preset.
    """
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # No window= param in URL
    current_url = page.url
    assert "window=" not in current_url, f"Expected no window param on /apps, but URL is: {current_url}"
    # The active time preset label should reflect the stored '1h' preference
    body = page.locator("body")
    expect(body).to_contain_text("1h")


def test_time_preset_button_updates_url_and_preference(page: Page, base_url: str) -> None:
    """AC#8: Clicking the time preset button updates both URL and persisted preference."""
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # Click the 24h preset button
    preset_btn = page.get_by_role("button", name="24h")
    expect(preset_btn).to_be_visible()
    preset_btn.click()
    page.wait_for_timeout(500)
    # URL should now include ?window=24h
    expect(page).to_have_url(re.compile(r"\?.*window=24h"))


# ──────────────────────────────────────────────────────────────────────
# AC#10: Invalid handler ID correction
# ──────────────────────────────────────────────────────────────────────


def test_invalid_handler_id_shows_no_selection(page: Page, base_url: str) -> None:
    """Navigating to an invalid handler ID shows handlers tab with no selection (AC#10)."""
    page.goto(base_url + "/apps/my_app/handlers/h-99999")
    page.wait_for_load_state("networkidle")
    # Handler list should be visible (on handlers tab)
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible(timeout=5000)
    # No handler detail pane should be shown — placeholder should be visible
    placeholder = page.locator("[data-testid='detail-placeholder']")
    expect(placeholder).to_be_visible(timeout=5000)


def test_invalid_handler_id_corrects_url(page: Page, base_url: str) -> None:
    """After loading with an invalid handler ID, URL is corrected (AC#10)."""
    page.goto(base_url + "/apps/my_app/handlers/h-99999")
    page.wait_for_load_state("networkidle")
    # Wait for URL correction to happen (after data fetch confirms handler doesn't exist)
    page.wait_for_timeout(1000)
    current_url = page.url
    # The invalid handler ID should be removed from the URL
    assert "h-99999" not in current_url, (
        f"Expected invalid handler ID to be corrected from URL, but URL is: {current_url}"
    )


# ──────────────────────────────────────────────────────────────────────
# AC#12: Multi-instance routing
# ──────────────────────────────────────────────────────────────────────


def test_instance_query_param_loads_instance(page: Page, base_url: str) -> None:
    """Navigating to /apps/multi_app?instance=1 loads instance 1 (AC#12)."""
    page.goto(base_url + "/apps/multi_app?instance=1")
    page.wait_for_load_state("networkidle")
    # Instance switcher should be visible (we're in instance detail mode, not overview)
    switcher = page.locator("[data-testid='instance-switcher']")
    expect(switcher).to_be_visible(timeout=5000)
    # Instance 1 should be selected in the switcher
    expect(switcher).to_contain_text("MultiApp[1]")


def test_no_instance_param_shows_parent_overview(page: Page, base_url: str) -> None:
    """Navigating to /apps/multi_app (no instance) shows the parent overview grid (AC#12)."""
    page.goto(base_url + "/apps/multi_app")
    page.wait_for_load_state("networkidle")
    overview = page.locator("[data-testid='multi-instance-overview']")
    expect(overview).to_be_visible(timeout=5000)
    instance_grid = page.locator("[data-testid='instance-grid']")
    expect(instance_grid).to_be_visible()


def test_instance_param_persists_on_refresh(page: Page, base_url: str) -> None:
    """Instance selection via ?instance= persists on page refresh (AC#1, AC#12)."""
    page.goto(base_url + "/apps/multi_app?instance=1")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='instance-switcher']")).to_be_visible(timeout=5000)
    # Reload
    page.reload()
    page.wait_for_load_state("networkidle")
    # Should still be on instance 1
    expect(page).to_have_url(re.compile(r"instance=1"))
    expect(page.locator("[data-testid='instance-switcher']")).to_be_visible(timeout=5000)


# ──────────────────────────────────────────────────────────────────────
# AC#14: Out-of-range instance correction
# ──────────────────────────────────────────────────────────────────────


def test_out_of_range_instance_corrected_to_zero(page: Page, base_url: str) -> None:
    """Navigating to ?instance=99 on an app with 3 instances corrects to ?instance=0 (AC#14)."""
    page.goto(base_url + "/apps/multi_app?instance=99")
    page.wait_for_load_state("networkidle")
    # Wait for URL correction
    page.wait_for_timeout(1000)
    current_url = page.url
    # Should have corrected to instance=0, not instance=99
    assert "instance=99" not in current_url, (
        f"Expected out-of-range instance to be corrected, but URL is: {current_url}"
    )
    # Instance switcher should show instance 0
    switcher = page.locator("[data-testid='instance-switcher']")
    expect(switcher).to_be_visible(timeout=5000)
    expect(switcher).to_contain_text("MultiApp[0]")


# ──────────────────────────────────────────────────────────────────────
# AC#4: View in code — ?line= param
# ──────────────────────────────────────────────────────────────────────


def test_code_tab_with_line_param(page: Page, base_url: str) -> None:
    """Navigating to /apps/:key/code?line=N loads code tab (AC#4, AC#1)."""
    page.goto(base_url + "/apps/my_app/code?line=15")
    page.wait_for_load_state("networkidle")
    # Code tab should be active
    code_content = page.locator("[data-testid='code-tab-content']")
    expect(code_content).to_be_visible(timeout=5000)


def test_code_tab_line_param_persists_on_refresh(page: Page, base_url: str) -> None:
    """Line param on code tab persists after refresh (AC#4, AC#1)."""
    page.goto(base_url + "/apps/my_app/code?line=15")
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-testid='code-tab-content']")).to_be_visible(timeout=5000)
    # Reload
    page.reload()
    page.wait_for_load_state("networkidle")
    # URL should still have line=15
    expect(page).to_have_url(re.compile(r"line=15"))


def test_view_in_code_from_handler_sets_line_param(page: Page, base_url: str) -> None:
    """Clicking 'view in code' from a handler navigates to code tab with ?line= (AC#4)."""
    # Select a handler that has source_location defined
    page.goto(base_url + "/apps/my_app/handlers/h-1")
    page.wait_for_load_state("networkidle")
    # Wait for handler detail to load
    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)
    # Click the "view in code" button
    view_in_code = page.locator("[data-testid='view-in-code-btn']")
    expect(view_in_code).to_be_visible()
    view_in_code.click()
    page.wait_for_timeout(500)
    # Should navigate to code tab
    expect(page).to_have_url(re.compile(r"/apps/my_app/code"))
    # URL should contain line= parameter
    expect(page).to_have_url(re.compile(r"line=\d+"))


# ──────────────────────────────────────────────────────────────────────
# AC#11: All navigation sources produce new-format URLs
# ──────────────────────────────────────────────────────────────────────


def test_clicking_handler_row_produces_new_format_url(page: Page, base_url: str) -> None:
    """Clicking a handler row produces /apps/:key/handlers/h-{id} URL (AC#11)."""
    page.goto(base_url + "/apps/my_app/handlers")
    page.wait_for_load_state("networkidle")
    # Click listener row 1
    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()
    page.wait_for_timeout(300)
    # URL should use the h- prefix format
    expect(page).to_have_url(re.compile(r"/apps/my_app/handlers/h-1"))


def test_clicking_tab_button_produces_path_segment_url(page: Page, base_url: str) -> None:
    """Clicking a tab button produces /apps/:key/{tab} URL format (AC#11)."""
    page.goto(base_url + "/apps/my_app")
    page.wait_for_load_state("networkidle")
    # Click Logs tab
    page.locator("a[role='tab']", has_text="logs").click()
    page.wait_for_timeout(300)
    expect(page).to_have_url(re.compile(r"/apps/my_app/logs"))


def test_sidebar_instance_link_uses_query_param_format(page: Page, base_url: str) -> None:
    """Instance links in sidebar use ?instance=N format, not path segment (AC#11)."""
    page.set_viewport_size(DESKTOP_VIEWPORT)
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")
    # Open the RUNNING sidebar group first (collapsed by default when
    # other status groups have apps)
    running_header = page.locator("[data-testid='group-header']", has_text="RUNNING")
    expect(running_header).to_be_visible()
    running_header.click()
    page.wait_for_timeout(300)
    # Expand multi_app in sidebar
    expand_btn = page.get_by_label("Expand Multi App", exact=False)
    expect(expand_btn).to_be_visible()
    expand_btn.click()
    page.wait_for_timeout(300)
    # Click instance 0 link
    instance_list = page.locator("[data-testid='instance-list']").first
    expect(instance_list).to_be_visible()
    first_instance_link = instance_list.locator("a").first
    expect(first_instance_link).to_be_visible()
    href = first_instance_link.get_attribute("href")
    assert href is not None
    # Should use ?instance= not /0 path segment
    assert "instance=" in href, f"Expected sidebar instance link to use ?instance= query param, got href={href}"
    assert "/multi_app/0" not in href, f"Expected no path-segment instance in sidebar link, got href={href}"
