"""E2E tests for the Sessions page."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_sessions_page_renders(page: Page, base_url: str) -> None:
    """Navigate to /sessions and verify the table renders with session data."""
    page.goto(base_url + "/sessions")
    expect(page.locator("body")).to_contain_text("Sessions")

    # Table should be visible
    table = page.locator("[data-testid='sessions-table']")
    expect(table).to_be_visible()

    # Verify column headers
    thead = table.locator("thead")
    expect(thead).to_contain_text("Status")
    expect(thead).to_contain_text("Started At")
    expect(thead).to_contain_text("Stopped At")
    expect(thead).to_contain_text("Duration")
    expect(thead).to_contain_text("Error Type")
    expect(thead).to_contain_text("Error Message")

    # Verify at least one session row with status badge
    tbody = table.locator("tbody")
    rows = tbody.locator("tr")
    expect(rows.first).to_be_visible()
    assert rows.count() >= 1

    # Verify status badges render (seed data has running, success, failure)
    expect(tbody).to_contain_text("running")
    expect(tbody).to_contain_text("success")
    expect(tbody).to_contain_text("failure")

    # Verify formatted timestamps appear (not raw floats)
    # Seed data started_at=1704067200.0 → should show formatted date, not "1704067200"
    expect(tbody).not_to_contain_text("1704067200")

    # Verify error info from the failed session
    expect(tbody).to_contain_text("RuntimeError")
    expect(tbody).to_contain_text("WebSocket connection lost")


def test_sidebar_sessions_navigation(page: Page, base_url: str) -> None:
    """Click the Sessions nav item and verify navigation to /sessions."""
    page.goto(base_url + "/")
    # Wait for the dashboard to load
    page.wait_for_load_state("networkidle")

    # Click the Sessions nav item
    nav_link = page.locator("[data-testid='nav-sessions']")
    expect(nav_link).to_be_visible()
    nav_link.click()

    # Verify URL changed to /sessions
    page.wait_for_url("**/sessions")

    # Verify the sessions page content loaded
    expect(page.locator("[data-testid='sessions-table']")).to_be_visible()
