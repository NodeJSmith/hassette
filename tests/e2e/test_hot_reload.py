"""E2E tests for SPA behavior: verifies the Preact SPA loads and renders
correctly, handling the absence of a WebSocket connection gracefully.

The old htmx-based hot-reload tests (Alpine WS store, dev_reload messages)
are no longer applicable — the Preact SPA uses Vite HMR during development
and does not implement a custom dev_reload protocol.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_spa_loads_without_ws(page: Page, base_url: str) -> None:
    """SPA loads and renders the dashboard even without a WebSocket connection.

    The e2e test server starts with ws='none'. The Preact app's useWebSocket
    hook will fail silently and the app renders from REST API data.
    """
    page.goto(base_url + "/")

    # Core dashboard content should be visible
    expect(page.locator("body")).to_contain_text("App Health")
    expect(page.locator("[data-testid='kpi-strip']")).to_be_visible()
    expect(page.locator("#dashboard-app-grid")).to_be_visible()


def test_spa_navigates_without_full_reload(page: Page, base_url: str) -> None:
    """Client-side navigation between pages does not trigger a full page reload."""
    page.goto(base_url + "/")

    # Set a marker to detect full reload
    page.evaluate("window.__test_marker = true")

    # Navigate to Apps page via sidebar
    page.locator("[data-testid='nav-apps']").click()
    expect(page.locator("body")).to_contain_text("App Management")

    # Page was NOT reloaded — marker survives
    assert page.evaluate("window.__test_marker") is True

    # Navigate back to Dashboard
    page.locator("[data-testid='nav-dashboard']").click()
    expect(page.locator("body")).to_contain_text("App Health")

    # Still no full reload
    assert page.evaluate("window.__test_marker") is True


def test_spa_handles_direct_deep_link(page: Page, base_url: str) -> None:
    """Direct navigation to a deep link (e.g., /apps/my_app) works.

    The server serves index.html for all non-API paths, so the SPA
    handles routing client-side via wouter.
    """
    page.goto(base_url + "/apps/my_app")
    expect(page.locator("body")).to_contain_text("My App")
    expect(page.locator("[data-testid='health-strip']")).to_be_visible()
