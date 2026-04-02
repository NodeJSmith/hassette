"""E2E tests for the session scope toggle (This Session / All Time)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_scope_toggle_visible_on_dashboard(page: Page, base_url: str) -> None:
    """The segmented scope toggle is visible in the status bar on the dashboard."""
    page.goto(base_url + "/")
    toggle = page.locator("[data-testid='scope-toggle']")
    expect(toggle).to_be_visible()

    # Both buttons should be present
    expect(page.locator("[data-testid='scope-current']")).to_be_visible()
    expect(page.locator("[data-testid='scope-all']")).to_be_visible()


def test_scope_toggle_visible_on_app_detail(page: Page, base_url: str) -> None:
    """The scope toggle is also visible on app detail pages."""
    page.goto(base_url + "/apps/my_app")
    toggle = page.locator("[data-testid='scope-toggle']")
    expect(toggle).to_be_visible()


def test_scope_toggle_switches_data(page: Page, base_url: str) -> None:
    """Toggling scope changes which data is shown on the dashboard.

    Since the E2E server returns the same mock data for all requests
    (regardless of session_id), we verify the toggle *functions* by:
    1. Confirming 'All Time' shows data (KPIs visible)
    2. Switching to 'This Session' (scope='current' with null sessionId
       shows loading state since WS is disabled)
    3. Switching back to 'All Time' and confirming data reappears
    """
    page.goto(base_url + "/")

    # Start with 'All Time' active (set by autouse fixture)
    all_btn = page.locator("[data-testid='scope-all']")
    current_btn = page.locator("[data-testid='scope-current']")

    expect(all_btn).to_have_attribute("aria-pressed", "true")

    # KPI strip should be visible with data
    kpi_strip = page.locator("[data-testid='kpi-strip']")
    expect(kpi_strip).to_be_visible()

    # Switch to "This Session" — without WS, sessionId is null, so useScopedApi
    # returns loading state and no data renders
    current_btn.click()
    expect(current_btn).to_have_attribute("aria-pressed", "true")
    expect(all_btn).to_have_attribute("aria-pressed", "false")

    # Dashboard should show spinner (loading state)
    expect(page.locator(".ht-spinner")).to_be_visible(timeout=3000)

    # Switch back to "All Time" — data should reappear
    all_btn.click()
    expect(all_btn).to_have_attribute("aria-pressed", "true")
    expect(kpi_strip).to_be_visible(timeout=5000)


def test_scope_toggle_persists_across_reload(page: Page, base_url: str) -> None:
    """Setting scope to 'All Time' persists across page reload."""
    page.goto(base_url + "/")

    # The autouse fixture sets "all" — verify it stuck
    all_btn = page.locator("[data-testid='scope-all']")
    expect(all_btn).to_have_attribute("aria-pressed", "true")

    # Now switch to "This Session"
    current_btn = page.locator("[data-testid='scope-current']")
    current_btn.click()
    expect(current_btn).to_have_attribute("aria-pressed", "true")

    # Verify localStorage was updated
    stored = page.evaluate('localStorage.getItem("hassette:sessionScope")')
    assert stored == '"current"'

    # Reload and verify persistence
    page.reload()
    current_btn = page.locator("[data-testid='scope-current']")
    expect(current_btn).to_have_attribute("aria-pressed", "true")

    # Clean up — set back to "all" for other tests
    page.evaluate('localStorage.setItem("hassette:sessionScope", JSON.stringify("all"))')
    page.reload()
