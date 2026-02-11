"""Integration tests for the Hassette Web UI (pages, partials, static assets)."""

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.core.data_sync_service import DataSyncService
from hassette.web.app import create_fastapi_app

try:
    from httpx import ASGITransport, AsyncClient

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

pytestmark = pytest.mark.skipif(not HAS_HTTPX, reason="httpx not installed")


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance with UI enabled."""
    hassette = MagicMock()
    hassette.config.run_web_api = True
    hassette.config.run_web_ui = True
    hassette.config.web_api_cors_origins = ("http://localhost:3000",)
    hassette.config.web_api_event_buffer_size = 100
    hassette.config.web_api_log_level = "INFO"
    hassette.config.dev_mode = True
    hassette.config.allow_reload_in_prod = False

    # Mock state proxy
    hassette._state_proxy.states = {
        "light.kitchen": {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"brightness": 255},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
    }
    hassette._state_proxy.get_state.side_effect = lambda eid: hassette._state_proxy.states.get(eid)
    hassette._state_proxy.is_ready.return_value = True

    # Mock websocket service
    from hassette.types.enums import ResourceStatus

    hassette._websocket_service.status = ResourceStatus.RUNNING

    # Mock app handler
    snapshot = SimpleNamespace(
        running=[
            SimpleNamespace(
                app_key="my_app",
                index=0,
                instance_name="MyApp[0]",
                class_name="MyApp",
                status=SimpleNamespace(value="running"),
                error_message=None,
            )
        ],
        failed=[],
        total_count=1,
        running_count=1,
        failed_count=0,
        only_app=None,
    )
    hassette._app_handler.get_status_snapshot.return_value = snapshot

    # Mock bus service
    hassette._bus_service.get_all_listener_metrics.return_value = []
    hassette._bus_service.get_listener_metrics_by_owner.return_value = []

    # Mock children for system status
    hassette.children = []

    return hassette


@pytest.fixture
def mock_hassette_no_ui():
    """Create a mock Hassette instance with UI disabled."""
    hassette = MagicMock()
    hassette.config.run_web_api = True
    hassette.config.run_web_ui = False
    hassette.config.web_api_cors_origins = ("http://localhost:3000",)
    hassette.config.web_api_event_buffer_size = 100
    hassette.config.web_api_log_level = "INFO"
    hassette.config.dev_mode = True
    hassette.config.allow_reload_in_prod = False
    hassette._state_proxy.states = {}
    hassette._state_proxy.is_ready.return_value = True

    from hassette.types.enums import ResourceStatus

    hassette._websocket_service.status = ResourceStatus.RUNNING
    hassette._app_handler.get_status_snapshot.return_value = SimpleNamespace(
        running=[], failed=[], total_count=0, running_count=0, failed_count=0, only_app=None
    )
    hassette._bus_service.get_all_listener_metrics.return_value = []
    hassette.children = []
    return hassette


@pytest.fixture
def data_sync_service(mock_hassette):
    """Create a DataSyncService with mocked Hassette."""
    ds = DataSyncService.__new__(DataSyncService)
    ds.hassette = mock_hassette
    ds._event_buffer = deque(maxlen=100)
    ds._ws_clients = set()
    ds._lock = asyncio.Lock()
    ds._start_time = 1704067200.0
    ds._subscriptions = []
    ds.logger = MagicMock()
    mock_hassette._data_sync_service = ds
    return ds


@pytest.fixture
def data_sync_service_no_ui(mock_hassette_no_ui):
    """Create a DataSyncService for the no-UI variant."""
    ds = DataSyncService.__new__(DataSyncService)
    ds.hassette = mock_hassette_no_ui
    ds._event_buffer = deque(maxlen=100)
    ds._ws_clients = set()
    ds._lock = asyncio.Lock()
    ds._start_time = 1704067200.0
    ds._subscriptions = []
    ds.logger = MagicMock()
    mock_hassette_no_ui._data_sync_service = ds
    return ds


@pytest.fixture
def app(mock_hassette, data_sync_service):  # noqa: ARG001
    return create_fastapi_app(mock_hassette)


@pytest.fixture
def app_no_ui(mock_hassette_no_ui, data_sync_service_no_ui):  # noqa: ARG001
    return create_fastapi_app(mock_hassette_no_ui)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def client_no_ui(app_no_ui):
    transport = ASGITransport(app=app_no_ui)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestRootRedirect:
    async def test_root_redirects_to_ui(self, client: "AsyncClient") -> None:
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/ui/"

    async def test_root_no_redirect_when_ui_disabled(self, client_no_ui: "AsyncClient") -> None:
        response = await client_no_ui.get("/", follow_redirects=False)
        # No root route registered when UI is disabled
        assert response.status_code == 404


class TestStaticFiles:
    async def test_css_accessible(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/css/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    async def test_js_accessible(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/js/ws-handler.js")
        assert response.status_code == 200

    async def test_static_not_found(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/nonexistent.css")
        assert response.status_code == 404


class TestDashboardPage:
    async def test_dashboard_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_dashboard_contains_nav(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        body = response.text
        assert "Dashboard" in body
        assert "Apps" in body
        assert "Logs" in body

    async def test_dashboard_contains_htmx(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "htmx.org" in response.text

    async def test_dashboard_contains_health_data(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        body = response.text
        # Should contain system health info
        assert "System Health" in body

    async def test_dashboard_contains_bus_metrics(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "Event Bus" in body if (body := response.text) else False

    async def test_dashboard_shows_app_counts(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        body = response.text
        # App summary with running count
        assert "1" in body  # 1 running app


class TestAppsPage:
    async def test_apps_page_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_apps_page_contains_app_table(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        body = response.text
        assert "my_app" in body
        assert "MyApp" in body

    async def test_apps_page_contains_action_buttons(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        body = response.text
        assert "hx-post" in body
        assert "/api/apps/my_app/" in body

    async def test_apps_page_shows_status_badge(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        assert "running" in response.text


class TestLogsPage:
    async def test_logs_page_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/logs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_logs_page_contains_filter_controls(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/logs")
        body = response.text
        assert "log-level-filter" in body
        assert "log-app-filter" in body

    async def test_logs_page_contains_level_options(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/logs")
        body = response.text
        assert "DEBUG" in body
        assert "ERROR" in body
        assert "CRITICAL" in body


class TestPartials:
    """Partial endpoints return HTML fragments, not full pages."""

    async def test_health_badge_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/health-badge")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" not in response.text
        assert "<head" not in response.text

    async def test_event_feed_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/event-feed")
        assert response.status_code == 200
        assert "<html" not in response.text
        # Empty events => shows message
        assert "No recent events" in response.text

    async def test_event_feed_partial_with_events(
        self, client: "AsyncClient", data_sync_service: DataSyncService
    ) -> None:
        data_sync_service._event_buffer.append(
            {"type": "state_changed", "entity_id": "light.kitchen", "timestamp": 1704067200.0}
        )
        response = await client.get("/ui/partials/event-feed")
        assert response.status_code == 200
        assert "state_changed" in response.text

    async def test_app_list_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-list")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "my_app" in response.text

    async def test_app_row_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-row/my_app")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "my_app" in response.text

    async def test_app_row_partial_unknown_app(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-row/nonexistent")
        assert response.status_code == 200
        # Template should handle None app gracefully

    async def test_log_entries_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/log-entries")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_log_entries_partial_with_filters(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/log-entries?level=ERROR&app_key=my_app&limit=10")
        assert response.status_code == 200


class TestEmptyStates:
    """Pages handle empty data gracefully."""

    async def test_dashboard_no_apps(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette._app_handler.get_status_snapshot.return_value = SimpleNamespace(
            running=[], failed=[], total_count=0, running_count=0, failed_count=0, only_app=None
        )
        response = await client.get("/ui/")
        assert response.status_code == 200
        assert "No apps configured" in response.text

    async def test_apps_page_no_apps(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette._app_handler.get_status_snapshot.return_value = SimpleNamespace(
            running=[], failed=[], total_count=0, running_count=0, failed_count=0, only_app=None
        )
        response = await client.get("/ui/apps")
        assert response.status_code == 200
        assert "No apps are configured" in response.text


class TestUIDisabled:
    async def test_ui_routes_not_available(self, client_no_ui: "AsyncClient") -> None:
        response = await client_no_ui.get("/ui/")
        assert response.status_code == 404

    async def test_api_still_works(self, client_no_ui: "AsyncClient") -> None:
        response = await client_no_ui.get("/api/healthz")
        assert response.status_code == 200
