"""E2E tests for WebSocket infrastructure: connection indicator and SPA
rendering stability when WS is unavailable, and the WS uptime-scoped fetch path."""

import time

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# ── Connection indicator ─────────────────────────────────────────────


def test_ws_connection_indicator_renders(page: Page, base_url: str) -> None:
    """The connection bar renders without JS errors even without a WS server.

    The e2e test server starts with ws='none', so the Preact WS hook
    will fail to connect. The page should still render fully.
    """
    page.goto(base_url + "/apps")
    # Core page structure should render even without a WS connection
    expect(page.locator("[data-testid='apps-page']")).to_be_visible()


def test_status_bar_shows_disconnected_state(page: Page, base_url: str) -> None:
    """Status bar reflects the WS connection state.

    With ws='none' in the test server, the WebSocket never connects,
    so the status bar should show 'Disconnected' or 'Reconnecting'.
    """
    page.goto(base_url + "/")
    status_bar = page.locator("[data-testid='status-bar']")
    expect(status_bar).to_be_visible()
    expect(status_bar).to_contain_text("onnect")


# ── SPA renders all pages without WS ─────────────────────────────────


def test_apps_page_renders_without_ws(page: Page, base_url: str) -> None:
    """Apps page renders from REST API without WS."""
    page.goto(base_url + "/apps")
    page.wait_for_load_state("networkidle")

    # Apps page should be visible
    expect(page.locator("[data-testid='apps-page']")).to_be_visible()


def test_app_detail_renders_without_ws(page: Page, base_url: str) -> None:
    """App detail page renders overview tab content from REST API."""
    page.goto(base_url + "/apps/my_app")

    # Overview tab renders by default with handler health grid
    overview = page.locator("[data-testid='overview-tab']")
    expect(overview).to_be_visible()

    # Handler health grid should be visible on the overview tab
    health_grid = page.locator("[data-testid='overview-health-grid']")
    expect(health_grid).to_be_visible()


# ── Expand state stability ────────────────────────────────────────────


def test_handler_row_clickable_without_ws(page: Page, base_url: str) -> None:
    """Click a handler row and verify the detail pane loads.

    In the Preact SPA, master/detail state is managed by local signals
    and does not depend on a WS connection.
    """
    # Navigate to the handlers tab where the master/detail layout lives
    page.goto(base_url + "/apps/my_app/handlers")

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
    - Apps page loads data after WS connection establishes uptime_seconds gate
    """
    page.goto(live_server_ws + "/apps")

    # The status bar should reach 'Connected' once the WS handshake completes
    # and the server sends the 'connected' message with uptime_seconds.
    status_bar = page.locator("[data-testid='status-bar']")
    expect(status_bar).to_be_visible()
    ws_indicator = page.locator("[data-testid='ws-indicator']")
    expect(ws_indicator.first).to_have_text("Connected", timeout=10000)

    # After WS connects, useScopedApi unblocks (uptime_seconds gate) and fires
    # telemetry fetches. Wait for the apps page to finish loading.
    expect(page.locator("[data-testid='apps-page']")).to_be_visible(timeout=10000)


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
    page.goto(live_server_ws + "/apps")

    # Wait for WS to connect and data to load
    ws_indicator = page.locator("[data-testid='ws-indicator']")
    expect(ws_indicator.first).to_have_text("Connected", timeout=10000)
    expect(page.locator("[data-testid='apps-page']")).to_be_visible(timeout=10000)

    # At least one dashboard telemetry request must have been made
    assert len(api_requests) > 0, "No /api/telemetry/ requests were captured"

    # None of the requests should include session_id
    session_id_requests = [u for u in api_requests if "session_id" in u]
    assert session_id_requests == [], f"Unexpected session_id in telemetry requests: {session_id_requests}"


# ── execution_completed WS message ───────────────────────────────────────


def test_execution_completed_ws_message_triggers_activity_refetch(page: Page, live_server_ws_inject) -> None:
    """An execution_completed WS message carrying kind triggers an activity refetch.

    FR#11 — unified execution_completed message.

    Uses live_server_ws_inject (WebSocket enabled) to:
    1. Navigate to the app detail overview, which renders RecentActivitySection.
    2. Wait for the WS indicator to reach 'Connected' (uptime_seconds received).
    3. Start capturing network requests.
    4. Inject a unified execution_completed WS message for 'my_app' with kind='handler'.
    5. Assert the frontend re-fetches activity for my_app
       (GET /api/telemetry/app/my_app/activity).

    The useQueryInvalidator hook inside RecentActivitySection subscribes to the
    executionCompleted signal and invalidates the activity query when any event's
    app_key matches. The refetch is the observable proof that the message reached
    the frontend and was parsed correctly.

    Modelled on test_websocket_no_session_id_in_requests which also captures
    requests after WS connects and then asserts their shape.
    """
    base = live_server_ws_inject.url
    broadcast_sync = live_server_ws_inject.broadcast_sync

    page.goto(base + "/apps/my_app")

    # Wait for WS to connect — uptime_seconds gate unblocks useScopedApi.
    ws_indicator = page.locator("[data-testid='ws-indicator']")
    expect(ws_indicator.first).to_have_text("Connected", timeout=10000)

    # The overview tab (with RecentActivitySection) must be visible before injection.
    expect(page.locator("[data-testid='overview-tab']")).to_be_visible(timeout=10000)

    activity_refetch_requests: list[str] = []

    def _capture(request) -> None:
        if "/api/telemetry/app/my_app/activity" in request.url:
            activity_refetch_requests.append(request.url)

    page.on("request", _capture)

    # Inject a unified execution_completed WS message with kind='handler'.
    broadcast_sync(
        {
            "type": "execution_completed",
            "data": [
                {
                    "kind": "handler",
                    "app_key": "my_app",
                    "instance_index": 0,
                    "status": "success",
                    "duration_ms": 12.3,
                    "error_type": None,
                    "listener_id": 1,
                    "job_id": None,
                }
            ],
            "timestamp": time.time(),
        }
    )

    # The useQueryInvalidator hook refetches the activity endpoint when
    # execution_completed arrives with a matching app_key.
    # Poll for the refetch request with a short deadline.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if activity_refetch_requests:
            break
        time.sleep(0.1)

    assert activity_refetch_requests, (
        "Expected a GET /api/telemetry/app/my_app/activity refetch after "
        "execution_completed WS message, but none arrived within 5s"
    )
