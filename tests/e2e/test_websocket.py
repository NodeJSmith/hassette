"""E2E tests for WebSocket infrastructure: connection indicator and SPA
rendering stability when WS is unavailable, and the WS session-scoped fetch path."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.mock_fixtures import LISTENER_MY_APP_1_TOTAL_INVOCATIONS

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
    expect(calls_el).to_have_text(f"{LISTENER_MY_APP_1_TOTAL_INVOCATIONS} calls")


# ── WebSocket session path ────────────────────────────────────────────


def test_websocket_session_scoped_fetch(page: Page, live_server_ws: str) -> None:
    """The default user flow: WS connects → session_id received → API calls include session_id.

    Uses live_server_ws (WebSocket enabled, ws='websockets-sansio').
    The _default_scope_all autouse fixture runs on the ws='none' server's
    origin and does not affect localStorage on the WS server's distinct port
    origin, so sessionScope defaults to 'current' here.

    Verifies:
    - The status bar transitions to 'Connected' (WS handshake completes)
    - Dashboard API calls include ?session_id=N matching the session from
      the mock Hassette stub (session_id=1 as set in conftest.py)
    """
    # Collect all API requests made by the dashboard while it loads.
    api_requests: list[str] = []

    def _capture(request) -> None:
        if "/api/telemetry/" in request.url:
            api_requests.append(request.url)

    page.on("request", _capture)

    # Navigate to the WS-enabled server. sessionScope defaults to 'current'
    # (no prior localStorage on this origin), so useScopedApi waits for a
    # session_id before firing any telemetry fetch.
    page.goto(live_server_ws + "/")

    # The status bar should reach 'Connected' once the WS handshake completes
    # and the server sends the 'connected' message with session_id.
    # When connected, StatusBar renders only the dot (no text label) — check
    # the aria-label attribute instead of visible text.
    status_bar = page.locator(".ht-status-bar")
    expect(status_bar).to_be_visible()
    ws_indicator = page.locator(".ht-ws-indicator")
    expect(ws_indicator.first).to_have_attribute("aria-label", "Connected", timeout=10000)

    # After WS connects, useScopedApi unblocks and fires telemetry fetches.
    # Wait for the dashboard to finish loading (spinner disappears or data appears).
    expect(page.locator("#dashboard-app-grid")).to_be_visible(timeout=10000)

    # At least one dashboard telemetry request must have been made.
    assert len(api_requests) > 0, "No /api/telemetry/ requests were captured"

    # Every session-scoped request must include ?session_id=1 (the mock stub's
    # session_id set in conftest.py: hassette.session_id = 1).
    # The 'all'-scope endpoints (e.g. /telemetry/status, /telemetry/sessions)
    # do not include session_id — filter to the scoped ones.
    scoped_requests = [u for u in api_requests if "session_id" in u]
    assert len(scoped_requests) > 0, f"No session-scoped telemetry requests found. All requests: {api_requests}"
    for url in scoped_requests:
        assert "session_id=1" in url, f"Expected session_id=1 in URL but got: {url}"
