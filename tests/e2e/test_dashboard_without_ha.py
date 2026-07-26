"""E2E tests: the dashboard UI renders and reports accurate status when HA is unreachable.

Uses ``live_server_starting`` — a separate uvicorn instance backed by a mock Hassette whose
WebsocketService never connected — so this scenario cannot bleed into the happy-path
``live_server`` shared by every other e2e test.

See design/specs/018-dashboard-without-ha/design.md for the full rationale. The frontend has
no dedicated UI chrome for degraded status (explicit Non-Goal in the design doc) — these
tests confirm the existing UI renders correctly under a "starting" backend rather than
asserting on new chrome.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import seed_time_preset_1h

pytestmark = pytest.mark.e2e


def test_health_endpoint_reports_starting(page: Page, live_server_starting: str) -> None:
    """GET /api/health (via the browser's network stack) reports 'starting' with no HA."""
    response = page.request.get(f"{live_server_starting}/api/health")
    assert response.status == 200

    body = response.json()
    assert body["status"] == "starting"
    assert body["websocket_connected"] is False


def test_apps_page_renders_when_starting(page: Page, live_server_starting: str) -> None:
    """Apps page still renders and lists apps when the backend reports 'starting'."""
    page.goto(live_server_starting + "/apps")
    page.wait_for_load_state("networkidle")

    expect(page.locator("[data-testid='apps-page']")).to_be_visible()
    expect(page.locator("[data-testid='app-row-my_app']")).to_be_visible()


def test_app_detail_renders_when_starting(page: Page, live_server_starting: str) -> None:
    """App detail page renders from REST API when the backend reports 'starting'."""
    # live_server_starting is a separate origin from live_server — the autouse
    # set_time_preset_to_1h fixture only seeds the latter, so seed this origin too.
    seed_time_preset_1h(page, live_server_starting)
    page.goto(live_server_starting + "/apps/my_app")

    expect(page.locator("[data-testid='overview-tab']")).to_be_visible()
