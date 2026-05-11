"""E2E tests for the App Detail page in the new Ink UI.

Tests handler list with human_description, modifier chips, timed_out count,
master/detail layout, action buttons, code tab, config tab.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.mock_fixtures import (
    JOB_MY_APP_1_TOTAL_EXECUTIONS,
    JOB_MY_APP_2_TOTAL_EXECUTIONS,
    LISTENER_MY_APP_1_TOTAL_INVOCATIONS,
    LISTENER_MY_APP_2_TOTAL_INVOCATIONS,
)

pytestmark = pytest.mark.e2e


# ── Health strip ─────────────────────────────────────────────────────


def test_app_detail_renders_health_strip(page: Page, base_url: str) -> None:
    """Health strip is visible on the handlers tab with correct labels."""
    page.goto(base_url + "/apps/my_app/handlers")
    strip = page.locator("[data-testid='handlers-health-strip']")
    expect(strip).to_be_visible()
    expect(strip).to_contain_text("Handlers")
    expect(strip).to_contain_text("Success Rate")


# ── Action buttons ───────────────────────────────────────────────────


def test_running_app_shows_stop_and_reload_buttons(page: Page, base_url: str) -> None:
    """Running app shows Stop and Reload buttons."""
    page.goto(base_url + "/apps/my_app")
    expect(page.get_by_label("Stop app")).to_be_visible()
    expect(page.get_by_label("Reload app")).to_be_visible()


def test_failed_app_shows_start_button(page: Page, base_url: str) -> None:
    """Failed app shows Start button."""
    page.goto(base_url + "/apps/broken_app")
    expect(page.get_by_label("Start app")).to_be_visible()


def test_stop_button_shows_confirm_dialog(page: Page, base_url: str) -> None:
    """Clicking Stop opens a confirmation dialog."""
    page.goto(base_url + "/apps/my_app")
    stop_btn = page.get_by_label("Stop app")
    expect(stop_btn).to_be_visible()
    stop_btn.click()
    # Confirm dialog should appear
    dialog = page.locator(".ht-confirm-dialog, [role='alertdialog'], [role='dialog']")
    expect(dialog.first).to_be_visible()
    expect(dialog.first).to_contain_text("Stop")


def test_failed_app_shows_error_message(page: Page, base_url: str) -> None:
    """Failed app detail shows its error message."""
    page.goto(base_url + "/apps/broken_app")
    expect(page.locator("body")).to_contain_text("Init error: bad config")


# ── Handler list (master list) ───────────────────────────────────────


def test_app_detail_renders_handler_list(page: Page, base_url: str) -> None:
    """Handler list renders with handler names and invocation counts."""
    page.goto(base_url + "/apps/my_app/handlers")
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible()
    # Unified list shows handler_method names
    expect(handler_list).to_contain_text("on_light_change")
    expect(handler_list).to_contain_text("on_temp_update")
    # Invocation counts
    expect(handler_list).to_contain_text(f"{LISTENER_MY_APP_1_TOTAL_INVOCATIONS}")
    expect(handler_list).to_contain_text(f"{LISTENER_MY_APP_2_TOTAL_INVOCATIONS}")


def test_handler_row_shows_human_description(page: Page, base_url: str) -> None:
    """Handler row with human_description shows it as a subtitle."""
    page.goto(base_url + "/apps/my_app/handlers")
    handler_list = page.locator("[data-testid='handler-list']")
    # Listener 2 (on_temp_update) has human_description
    expect(handler_list).to_contain_text("React to temperature sensor changes above threshold")


def test_handler_row_shows_modifier_chips(page: Page, base_url: str) -> None:
    """Handler rows show modifier chips for debounce/throttle/once."""
    page.goto(base_url + "/apps/my_app/handlers")
    # Click the on_light_change row (listener 1, has debounce=0.5)
    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()
    page.wait_for_timeout(300)
    # Modifier chips visible in detail pane
    modifier_chips = page.locator("[data-testid='modifier-chips']")
    expect(modifier_chips).to_be_visible()
    expect(modifier_chips).to_contain_text("debounce")


def test_handler_row_shows_timed_out_count(page: Page, base_url: str) -> None:
    """Handler row shows timed_out count when > 0 (listener 1 has timed_out=1)."""
    page.goto(base_url + "/apps/my_app/handlers")
    # Listener 1 has timed_out=1 in seed data
    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    expect(row).to_contain_text("timed out")


# ── Job list ─────────────────────────────────────────────────────────


def test_app_detail_renders_job_rows(page: Page, base_url: str) -> None:
    """Job rows visible with run counts in the unified handler list."""
    page.goto(base_url + "/apps/my_app/handlers")
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible()
    # Job names from seed data
    expect(handler_list).to_contain_text("check_lights")
    expect(handler_list).to_contain_text("morning_routine")
    # Execution counts
    expect(handler_list).to_contain_text(f"{JOB_MY_APP_1_TOTAL_EXECUTIONS}")
    expect(handler_list).to_contain_text(f"{JOB_MY_APP_2_TOTAL_EXECUTIONS}")


# ── Master/detail layout ─────────────────────────────────────────────


def test_clicking_handler_row_shows_detail_pane(page: Page, base_url: str) -> None:
    """Clicking a handler row loads invocation history in the detail pane."""
    page.goto(base_url + "/apps/my_app/handlers")
    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()
    # Detail pane shows invocations for listener 1
    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)


def test_clicking_job_row_shows_detail_pane(page: Page, base_url: str) -> None:
    """Clicking a job row loads execution history in the detail pane."""
    page.goto(base_url + "/apps/my_app/handlers")
    # Job row (job_id=1)
    job_row = page.locator("[data-testid='unified-row-job-1']")
    expect(job_row).to_be_visible()
    job_row.click()
    detail = page.locator("[data-testid='job-detail-1']")
    expect(detail).to_be_visible(timeout=5000)


def test_detail_pane_shows_invocation_history(page: Page, base_url: str) -> None:
    """Detail pane shows success and error invocations after selecting a handler."""
    page.goto(base_url + "/apps/my_app/handlers")
    row = page.locator("[data-testid='unified-row-listener-1']")
    row.click()
    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)
    # Should show invocation stats and history from seed data
    expect(detail).to_contain_text("Successful")
    expect(detail).to_contain_text("invocations")


def test_empty_detail_placeholder_visible_by_default(page: Page, base_url: str) -> None:
    """Detail pane shows placeholder text before any row is selected."""
    page.goto(base_url + "/apps/my_app/handlers")
    placeholder = page.locator("[data-testid='detail-placeholder']")
    expect(placeholder).to_be_visible()


def test_stats_strip_renders(page: Page, base_url: str) -> None:
    """Handlers health strip above handler list shows handler count and call totals."""
    page.goto(base_url + "/apps/my_app/handlers")
    stats_strip = page.locator("[data-testid='handlers-health-strip']")
    expect(stats_strip).to_be_visible()
    expect(stats_strip).to_contain_text("Handler")


# ── Code tab ─────────────────────────────────────────────────────────


def test_code_tab_renders_source(page: Page, base_url: str) -> None:
    """Code tab renders the source file content."""
    page.goto(base_url + "/apps/my_app")
    # Click Code tab
    code_tab_btn = page.locator("[role='tab']", has_text="Code")
    expect(code_tab_btn).to_be_visible()
    code_tab_btn.click()
    page.wait_for_timeout(500)
    # Code tab content should be visible
    code_content = page.locator("[data-testid='code-tab-content']")
    expect(code_content).to_be_visible(timeout=5000)
    # Filename shown in header
    expect(code_content).to_contain_text("my_app.py")


def test_code_tab_nosource_shows_not_found(page: Page, base_url: str) -> None:
    """Code tab for app with missing source file shows 'not found' message."""
    page.goto(base_url + "/apps/nosource_app")
    code_tab_btn = page.locator("[role='tab']", has_text="Code")
    expect(code_tab_btn).to_be_visible()
    code_tab_btn.click()
    page.wait_for_timeout(500)
    # Should show error, not content
    error_display = page.locator("[data-testid='code-tab-error']")
    expect(error_display).to_be_visible(timeout=5000)
    expect(error_display).to_contain_text("not found")


# ── Config tab ───────────────────────────────────────────────────────


def test_config_tab_renders(page: Page, base_url: str) -> None:
    """Config tab renders app configuration values."""
    page.goto(base_url + "/apps/my_app")
    config_tab_btn = page.locator("[role='tab']", has_text="Config")
    expect(config_tab_btn).to_be_visible()
    config_tab_btn.click()
    config_content = page.locator("[data-testid='config-values-table']")
    expect(config_content).to_be_visible(timeout=5000)


def test_config_tab_shows_filename(page: Page, base_url: str) -> None:
    """Config tab shows the app filename."""
    page.goto(base_url + "/apps/my_app")
    config_tab_btn = page.locator("[role='tab']", has_text="Config")
    config_tab_btn.click()
    config_content = page.locator(".ht-config-tab")
    expect(config_content).to_be_visible(timeout=5000)
    expect(config_content).to_contain_text("my_app.py")


# ── Logs tab ─────────────────────────────────────────────────────────


def test_app_detail_logs_tab(page: Page, base_url: str) -> None:
    """Logs tab renders log entries filtered to the app."""
    page.goto(base_url + "/apps/my_app")
    logs_tab_btn = page.locator("[role='tab']", has_text="Logs")
    expect(logs_tab_btn).to_be_visible()
    logs_tab_btn.click()
    page.wait_for_timeout(500)
    logs_section = page.locator("[data-testid='logs-section']")
    expect(logs_section).to_be_visible()
    # App-specific log messages should be present
    entries_badge = page.locator("text=/\\d+ entries/")
    expect(entries_badge).to_be_visible(timeout=5000)
    body = page.locator("body")
    expect(body).to_contain_text("MyApp initialized")
    # Core-only messages should NOT appear (filtered by app_key)
    expect(body).not_to_contain_text("Hassette started successfully")


# ── Stopped/disabled app ─────────────────────────────────────────────


def test_stopped_app_renders_without_error(page: Page, base_url: str) -> None:
    """Stopped app detail page renders without errors."""
    page.goto(base_url + "/apps/other_app")
    expect(page.locator("body")).to_contain_text("Other App")


def test_app_detail_shows_display_name(page: Page, base_url: str) -> None:
    """App detail header shows the app_key as the title."""
    page.goto(base_url + "/apps/my_app")
    expect(page.locator("[data-testid='app-title']")).to_contain_text("my_app")


# ── Multi-instance ───────────────────────────────────────────────────


def test_multi_instance_app_shows_overview(page: Page, base_url: str) -> None:
    """Multi-instance app at /apps/multi_app shows instance overview grid."""
    page.goto(base_url + "/apps/multi_app")
    page.wait_for_load_state("networkidle")
    overview = page.locator("[data-testid='multi-instance-overview']")
    expect(overview).to_be_visible()
    instance_grid = page.locator("[data-testid='instance-grid']")
    expect(instance_grid).to_be_visible()


def test_multi_instance_detail_shows_switcher(page: Page, base_url: str) -> None:
    """Multi-instance detail at /apps/multi_app?instance=0 shows instance switcher."""
    page.goto(base_url + "/apps/multi_app?instance=0")
    page.wait_for_load_state("networkidle")
    switcher = page.locator("[data-testid='instance-switcher']")
    expect(switcher).to_be_visible()
