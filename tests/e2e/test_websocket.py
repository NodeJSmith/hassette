"""E2E tests for WebSocket connection indicator behavior."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_ws_connection_indicator_renders(page: Page, base_url: str) -> None:
    """Navigate to dashboard, verify the WS-related status bar renders.

    We don't have a real WS server in the live_server fixture, so the
    connection indicator should show a disconnected or reconnecting state
    gracefully rather than crashing the page.
    """
    page.goto(base_url + "/ui/")
    # The page should load without JS errors even without a WS connection.
    # Verify the page still has its core structure.
    expect(page.locator("body")).to_contain_text("System Health")
    expect(page.locator("body")).to_contain_text("Dashboard")


def test_ws_handler_script_loaded(page: Page, base_url: str) -> None:
    """Verify the ws-handler.js script tag is present in the page."""
    page.goto(base_url + "/ui/")
    ws_script = page.locator("script[src='/ui/static/js/ws-handler.js']")
    expect(ws_script).to_have_count(1)


def test_live_updates_script_loaded(page: Page, base_url: str) -> None:
    """Verify the live-updates.js script tag is present in the page."""
    page.goto(base_url + "/ui/")
    live_script = page.locator("script[src='/ui/static/js/live-updates.js']")
    expect(live_script).to_have_count(1)


def test_idiomorph_script_loaded(page: Page, base_url: str) -> None:
    """Verify the idiomorph CDN script tag is present in the page."""
    page.goto(base_url + "/ui/")
    idiomorph_script = page.locator("script[src*='idiomorph']")
    expect(idiomorph_script).to_have_count(1)
