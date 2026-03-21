"""E2E tests for WebSocket infrastructure: connection indicator and SPA
rendering stability when WS is unavailable."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# ── Connection indicator ─────────────────────────────────────────────


def test_ws_connection_indicator_renders(page: Page, base_url: str) -> None:
    """The connection bar renders without JS errors even without a WS server.

    The e2e test server starts with ws='none', so the Preact WS hook
    will fail to connect. The page should still render fully.
    """
    page.goto(base_url + "/")
    # Core page structure should render even without a WS connection
    expect(page.locator("body")).to_contain_text("App Health")


def test_status_bar_shows_disconnected_state(page: Page, base_url: str) -> None:
    """Status bar reflects the WS connection state.

    With ws='none' in the test server, the WebSocket never connects,
    so the status bar should show 'Disconnected' or 'Reconnecting'.
    """
    page.goto(base_url + "/")
    status_bar = page.locator(".ht-status-bar")
    expect(status_bar).to_be_visible()
    expect(status_bar).to_contain_text("onnect")


# ── SPA renders all pages without WS ─────────────────────────────────


def test_dashboard_renders_without_ws(page: Page, base_url: str) -> None:
    """Dashboard renders app grid and error feed from REST API without WS."""
    page.goto(base_url + "/")

    # App grid panel
    app_grid = page.locator("#dashboard-app-grid")
    expect(app_grid).to_be_visible()

    # Error feed panel
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_be_visible()


def test_app_detail_renders_without_ws(page: Page, base_url: str) -> None:
    """App detail page renders health strip, handler list, and job list from REST API."""
    page.goto(base_url + "/apps/my_app")

    # Handler list should be visible
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible()

    # Job list should be visible
    job_list = page.locator("[data-testid='job-list']")
    expect(job_list).to_be_visible()

    # Health strip should be visible
    health_strip = page.locator("[data-testid='health-strip']")
    expect(health_strip).to_be_visible()


# ── Expand state stability ────────────────────────────────────────────


def test_expanded_handler_row_stable_without_ws(page: Page, base_url: str) -> None:
    """Expand a handler row and verify it stays expanded.

    In the Preact SPA, expand/collapse state is managed by local signals
    in HandlerRow. Without WS-driven DOM morphing, the state naturally
    persists across any parent re-renders.
    """
    page.goto(base_url + "/apps/my_app")

    # Expand handler row 1
    handler_main = page.locator("[data-testid='handler-row-1'] .ht-item-row__main")
    handler_main.click()

    # Wait for invocation detail to load
    detail = page.locator("#handler-1-detail")
    expect(detail).to_be_visible(timeout=5000)

    # Verify expanded state via aria-expanded
    expect(handler_main).to_have_attribute("aria-expanded", "true")

    # Stats text should be present
    calls_el = page.locator("[data-testid='handler-row-1'] .ht-meta-item[title='Total invocations']")
    expect(calls_el).to_have_text("10 calls")
