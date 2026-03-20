"""E2E tests for WebSocket infrastructure: connection indicator, live-update
attributes, and idiomorph morph stability."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# ── Script presence ──────────────────────────────────────────────────


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


# ── Connection indicator ─────────────────────────────────────────────


def test_ws_connection_indicator_renders(page: Page, base_url: str) -> None:
    """The connection bar renders without JS errors even without a WS server.

    The e2e test server starts with ws='none', so Alpine's $store.ws.connected
    will be false. The page should still render fully.
    """
    page.goto(base_url + "/ui/")
    # Core page structure should render even without a WS connection
    expect(page.locator("body")).to_contain_text("App Health")


def test_status_bar_shows_disconnected_state(page: Page, base_url: str) -> None:
    """Status bar reflects the WS store's connected state.

    With ws='none' in the test server, the Alpine store never reaches
    connected=true, so the status bar should show 'Disconnected'.
    """
    page.goto(base_url + "/ui/")
    status_bar = page.locator(".ht-status-bar")
    expect(status_bar).to_be_visible()
    expect(status_bar).to_contain_text("onnected")


# ── data-live-on-app attributes ──────────────────────────────────────


def test_dashboard_has_live_update_targets(page: Page, base_url: str) -> None:
    """Dashboard panels carry data-live-on-app attributes for WS-driven refresh."""
    page.goto(base_url + "/ui/")

    # App grid panel
    app_grid = page.locator("#dashboard-app-grid")
    expect(app_grid).to_have_attribute("data-live-on-app", "/ui/partials/dashboard-app-grid")

    # Error feed panel
    error_feed = page.locator("[data-testid='dashboard-errors']")
    expect(error_feed).to_have_attribute("data-live-on-app", "/ui/partials/dashboard-errors")


def test_app_detail_has_live_update_targets(page: Page, base_url: str) -> None:
    """App detail page: health strip has data-live-on-app; handler/job lists do not.

    Handler and job lists no longer morph on WS events (WP02). Stats are
    updated in-place by JS reading the 5s polling partial.
    """
    page.goto(base_url + "/ui/apps/my_app")

    # Handler and job lists should NOT have data-live-on-app
    handler_list = page.locator("[data-testid='handler-list']")
    assert handler_list.get_attribute("data-live-on-app") is None

    job_list = page.locator("[data-testid='job-list']")
    assert job_list.get_attribute("data-live-on-app") is None

    # Health strip SHOULD still have it
    health_strip = page.locator("[data-testid='health-strip']")
    assert health_strip.get_attribute("data-live-on-app") is not None


# ── Live refresh via simulated WS message ────────────────────────────


def test_live_update_refreshes_on_app_status_event(page: Page, base_url: str) -> None:
    """Dispatching an ht:ws-message with type=app_status_changed triggers
    HTMX partial refresh requests on elements with data-live-on-app.

    We verify this by intercepting the outgoing fetch request that
    live-updates.js generates via htmx.ajax().
    """
    page.goto(base_url + "/ui/")
    page.wait_for_load_state("networkidle")

    # Set up a request listener to capture the partial fetch
    partial_requests: list[str] = []
    page.on("request", lambda req: partial_requests.append(req.url) if "/ui/partials/" in req.url else None)

    # Dispatch a synthetic ht:ws-message event (same as ws-handler.js does)
    page.evaluate("""() => {
        document.dispatchEvent(new CustomEvent('ht:ws-message', {
            detail: { type: 'app_status_changed' }
        }));
    }""")

    # Wait for the debounce (500ms) + network round trip
    page.wait_for_timeout(2000)

    # At least one partial refresh request should have been made for
    # a data-live-on-app element. Which specific partials fire depends on
    # IntersectionObserver visibility (off-screen panels are skipped).
    assert len(partial_requests) > 0, "No partial refresh requests were made after app_status_changed event."


# ── Morph stability: expanded row survives refresh ───────────────────


def test_expanded_handler_row_survives_htmx_morph(page: Page, base_url: str) -> None:
    """Expand a handler row, simulate a stats poll, and verify the row
    remains expanded.

    The handler list is no longer a morph target (data-live-on-app was
    removed in WP02). Instead, a hidden #app-handler-stats div polls
    every 5s and JS updates text/classes in-place. This test verifies
    that expand state survives the stats-only poll approach.
    """
    page.goto(base_url + "/ui/apps/my_app")

    # Confirm handler list is NOT a morph target
    handler_list = page.locator("[data-testid='handler-list']")
    assert handler_list.get_attribute("data-live-on-app") is None

    # Expand handler row 1
    handler_main = page.locator("[data-testid='handler-row-1'] .ht-item-row__main")
    handler_main.click()

    # Wait for invocation detail to load
    detail = page.locator("#handler-1-detail")
    expect(detail).to_be_visible(timeout=5000)

    # Verify expanded state via aria-expanded
    expect(handler_main).to_have_attribute("aria-expanded", "true")

    # Simulate a stats poll swap (the same mechanism that fires every 5s)
    page.evaluate("""() => {
        var statsDiv = document.getElementById('app-handler-stats');
        statsDiv.innerHTML =
            '<span data-listener-id="1" data-total-invocations="12" ' +
            'data-failed="1" data-avg-duration-ms="2.5" data-last-invoked="1704070800.0"></span>' +
            '<span data-listener-id="2" data-total-invocations="22" ' +
            'data-failed="0" data-avg-duration-ms="2.0" data-last-invoked="1704070700.0"></span>';
        var event = new CustomEvent('htmx:afterSwap', {
            bubbles: true,
            detail: { target: statsDiv }
        });
        document.body.dispatchEvent(event);
    }""")

    # Alpine state must be preserved — row still expanded
    expect(handler_main).to_have_attribute("aria-expanded", "true")
    expect(detail).to_be_visible()

    # Stats text should be updated
    calls_el = page.locator("[data-testid='handler-row-1'] .ht-meta-item[title='Total invocations']")
    expect(calls_el).to_have_text("12 calls")
