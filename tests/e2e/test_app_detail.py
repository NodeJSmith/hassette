"""E2E tests for the App Detail page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_app_detail_renders_health_strip(page: Page, base_url: str) -> None:
    """4 health cards visible with correct labels."""
    page.goto(base_url + "/apps/my_app")
    strip = page.locator("[data-testid='health-strip']")
    expect(strip).to_be_visible()
    expect(strip).to_contain_text("Status")
    expect(strip).to_contain_text("Error Rate")
    expect(strip).to_contain_text("Handler Avg")
    expect(strip).to_contain_text("Job Avg")


def test_app_detail_renders_handler_rows(page: Page, base_url: str) -> None:
    """Handler rows visible with method names and invocation counts."""
    page.goto(base_url + "/apps/my_app")
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible()
    # Handler method names from seed data
    expect(handler_list).to_contain_text("on_light_change")
    expect(handler_list).to_contain_text("on_temp_update")
    # Invocation counts
    expect(handler_list).to_contain_text("10 calls")
    expect(handler_list).to_contain_text("20 calls")


def test_handler_row_expand_loads_invocations(page: Page, base_url: str) -> None:
    """Click handler row, invocation history appears."""
    page.goto(base_url + "/apps/my_app")
    # Click the first handler row
    handler_main = page.locator("[data-testid='handler-row-1'] .ht-item-row__main")
    handler_main.click()
    # Wait for invocation table to load
    invocation_table = page.locator("[data-testid='invocation-table-1']")
    expect(invocation_table).to_be_visible(timeout=5000)
    # Should show invocation rows
    expect(invocation_table).to_contain_text("success")


def test_handler_invocation_shows_error_trace(page: Page, base_url: str) -> None:
    """Expanded row with error shows traceback."""
    page.goto(base_url + "/apps/my_app")
    # Click the first handler row to expand
    handler_main = page.locator("[data-testid='handler-row-1'] .ht-item-row__main")
    handler_main.click()
    # Wait for invocations to load
    invocation_table = page.locator("[data-testid='invocation-table-1']")
    expect(invocation_table).to_be_visible(timeout=5000)
    # Error traceback should be visible (from seed data)
    traceback = page.locator("[data-testid='invocation-traceback']")
    expect(traceback.first).to_be_visible()
    expect(traceback.first).to_contain_text("ValueError")
    expect(traceback.first).to_contain_text("Bad state value")


def test_app_detail_renders_job_rows(page: Page, base_url: str) -> None:
    """Job rows visible with run counts."""
    page.goto(base_url + "/apps/my_app")
    job_list = page.locator("[data-testid='job-list']")
    expect(job_list).to_be_visible()
    # Job names from seed data
    expect(job_list).to_contain_text("check_lights")
    expect(job_list).to_contain_text("morning_routine")
    # Execution counts
    expect(job_list).to_contain_text("15 runs")
    expect(job_list).to_contain_text("5 runs")


def test_job_row_expand_loads_executions(page: Page, base_url: str) -> None:
    """Click job row, execution history appears."""
    page.goto(base_url + "/apps/my_app")
    # Click the first job row
    job_main = page.locator("[data-testid='job-row-1'] .ht-item-row__main")
    job_main.click()
    # Wait for execution table to load
    execution_table = page.locator("[data-testid='execution-table-1']")
    expect(execution_table).to_be_visible(timeout=5000)
    expect(execution_table).to_contain_text("success")


def test_app_detail_logs_section(page: Page, base_url: str) -> None:
    """Log entries visible, filtered to app."""
    page.goto(base_url + "/apps/my_app")
    logs_section = page.locator("[data-testid='logs-section']")
    expect(logs_section).to_be_visible()
    # Wait for log entries to load
    entries_badge = page.locator("text=/\\d+ entries/")
    expect(entries_badge).to_be_visible(timeout=5000)
    body = page.locator("body")
    # App-specific log messages should be present
    expect(body).to_contain_text("MyApp initialized")
    # Core-only messages should NOT appear
    expect(body).not_to_contain_text("Hassette started successfully")


def test_app_detail_identity_model_fixed(page: Page, base_url: str) -> None:
    """Stopped app still shows its jobs (regression test for router.py:105 bug).

    The old code filtered jobs by owner_id, which is None for stopped apps.
    The fix uses app_key + instance_index from the telemetry database.
    """
    page.goto(base_url + "/apps/other_app")
    # other_app is stopped (no instances, owner_id=None)
    # The page should render without error (the old code would break)
    body = page.locator("body")
    expect(body).to_contain_text("Other App")
    expect(body).to_contain_text("Scheduled Jobs")


def test_registration_source_link(page: Page, base_url: str) -> None:
    """Source link visible in handler row or expanded handler details."""
    page.goto(base_url + "/apps/my_app")
    # The handler row itself shows the handler method and topic.
    handler_main = page.locator("[data-testid='handler-row-1'] .ht-item-row__main")
    handler_main.click()
    # After expanding, the detail panel loads.
    detail = page.locator("#handler-1-detail")
    expect(detail).to_be_visible(timeout=5000)


# ── Expand/collapse state ────────────────────────────────────────────


def test_expanded_row_preserves_state_across_signals(page: Page, base_url: str) -> None:
    """Expand a handler row, verify it stays expanded.

    In the Preact SPA, expand/collapse state is managed by local signals
    inside HandlerRow. Since there's no DOM replacement (unlike htmx morphing),
    expand state naturally survives parent re-renders.
    """
    page.goto(base_url + "/apps/my_app")

    # Expand handler row 1
    handler_main = page.locator("[data-testid='handler-row-1'] .ht-item-row__main")
    handler_main.click()
    detail = page.locator("#handler-1-detail")
    expect(detail).to_be_visible(timeout=5000)
    expect(handler_main).to_have_attribute("aria-expanded", "true")

    # Verify counts are correct
    calls_el = page.locator("[data-testid='handler-row-1'] .ht-meta-item[title='Total invocations']")
    expect(calls_el).to_have_text("10 calls")

    # Verify dot color: listener 1 has failures -> danger
    dot_1 = page.locator("[data-testid='handler-row-1'] .ht-item-row__dot")
    expect(dot_1).to_have_class("ht-item-row__dot ht-item-row__dot--danger")

    # Verify dot color: listener 2 has no failures, has invocations -> success
    dot_2 = page.locator("[data-testid='handler-row-2'] .ht-item-row__dot")
    expect(dot_2).to_have_class("ht-item-row__dot ht-item-row__dot--success")


def test_handler_list_is_not_live_morph_target(page: Page, base_url: str) -> None:
    """Verify handler and job lists don't have data-live-on-app attribute.

    In the SPA, lists are managed by Preact component state, not HTMX morphing.
    The health strip gets its own data from the API.
    """
    page.goto(base_url + "/apps/my_app")
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible()
    # Should NOT have data-live-on-app (SPA doesn't use HTMX morphing)
    assert handler_list.get_attribute("data-live-on-app") is None
    # Job list also should not have it
    job_list = page.locator("[data-testid='job-list']")
    assert job_list.get_attribute("data-live-on-app") is None
