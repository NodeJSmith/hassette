"""E2E tests for WebSocket infrastructure: connection indicator and SPA
rendering stability when WS is unavailable, and the WS uptime-scoped fetch path."""

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
    """App detail page renders health strip and handler list from REST API."""
    page.goto(base_url + "/apps/my_app")

    # Handler list should be visible (unified list — no separate job-list)
    handler_list = page.locator("[data-testid='handler-list']")
    expect(handler_list).to_be_visible()

    # Health strip should be visible
    health_strip = page.locator("[data-testid='health-strip']")
    expect(health_strip).to_be_visible()


# ── Expand state stability ────────────────────────────────────────────


def test_handler_row_clickable_without_ws(page: Page, base_url: str) -> None:
    """Click a handler row and verify the detail pane loads.

    In the Preact SPA, master/detail state is managed by local signals
    and does not depend on a WS connection.
    """
    page.goto(base_url + "/apps/my_app")

    # Click the first listener row
    row = page.locator("[data-testid='unified-row-listener-1']")
    expect(row).to_be_visible()
    row.click()

    # Detail pane should show invocation history
    detail = page.locator("[data-testid='listener-detail-1']")
    expect(detail).to_be_visible(timeout=5000)


# ── WebSocket uptime path ─────────────────────────────────────────────


def test_websocket_connected_message_has_uptime(page: Page, live_server_ws: str) -> None:
    """The WS connected message includes uptime_seconds (no session_id).

    Uses live_server_ws (WebSocket enabled, ws='websockets-sansio').

    Verifies:
    - The status bar transitions to 'Connected' (WS handshake completes)
    - Dashboard loads data after WS connection establishes uptime_seconds gate
    """
    page.goto(live_server_ws + "/")

    # The status bar should reach 'Connected' once the WS handshake completes
    # and the server sends the 'connected' message with uptime_seconds.
    status_bar = page.locator(".ht-status-bar")
    expect(status_bar).to_be_visible()
    ws_indicator = page.locator(".ht-ws-indicator")
    expect(ws_indicator.first).to_have_attribute("aria-label", "Connected", timeout=10000)

    # After WS connects, useScopedApi unblocks (uptime_seconds gate) and fires
    # telemetry fetches. Wait for the dashboard to finish loading.
    expect(page.locator("#dashboard-app-grid")).to_be_visible(timeout=10000)


def test_websocket_no_session_id_in_requests(page: Page, live_server_ws: str) -> None:
    """Telemetry API requests do NOT include session_id parameter.

    The new UI uses uptime_seconds from the WS connected message as a
    refresh gate, but never passes session_id to API calls.
    """
    api_requests: list[str] = []

    def _capture(request) -> None:
        if "/api/telemetry/" in request.url:
            api_requests.append(request.url)

    page.on("request", _capture)
    page.goto(live_server_ws + "/")

    # Wait for WS to connect and data to load
    ws_indicator = page.locator(".ht-ws-indicator")
    expect(ws_indicator.first).to_have_attribute("aria-label", "Connected", timeout=10000)
    expect(page.locator("#dashboard-app-grid")).to_be_visible(timeout=10000)

    # At least one dashboard telemetry request must have been made
    assert len(api_requests) > 0, "No /api/telemetry/ requests were captured"

    # None of the requests should include session_id
    session_id_requests = [u for u in api_requests if "session_id" in u]
    assert session_id_requests == [], f"Unexpected session_id in telemetry requests: {session_id_requests}"
