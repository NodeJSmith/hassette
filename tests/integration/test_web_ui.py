"""Integration tests for the Hassette Web UI (pages, partials, static assets)."""

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo
from hassette.core.data_sync_service import DataSyncService
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app

try:
    from httpx import ASGITransport, AsyncClient

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

pytestmark = pytest.mark.skipif(not HAS_HTTPX, reason="httpx not installed")


def _make_full_snapshot(
    manifests: list[AppManifestInfo] | None = None,
    only_app: str | None = None,
) -> AppFullSnapshot:
    """Build an AppFullSnapshot from a list of manifests."""
    manifests = manifests or []
    counts = {"running": 0, "failed": 0, "stopped": 0, "disabled": 0, "blocked": 0}
    for m in manifests:
        if m.status in counts:
            counts[m.status] += 1
    return AppFullSnapshot(
        manifests=manifests,
        only_app=only_app,
        total=len(manifests),
        **counts,
    )


def _make_manifest(
    app_key: str = "my_app",
    class_name: str = "MyApp",
    display_name: str = "My App",
    filename: str = "my_app.py",
    enabled: bool = True,
    auto_loaded: bool = False,
    status: str = "running",
    block_reason: str | None = None,
    instance_count: int = 1,
    instances: list[AppInstanceInfo] | None = None,
    error_message: str | None = None,
) -> AppManifestInfo:
    return AppManifestInfo(
        app_key=app_key,
        class_name=class_name,
        display_name=display_name,
        filename=filename,
        enabled=enabled,
        auto_loaded=auto_loaded,
        status=status,
        block_reason=block_reason,
        instance_count=instance_count,
        instances=instances or [],
        error_message=error_message,
    )


def _setup_registry(hassette: MagicMock, manifests: list[AppManifestInfo] | None = None) -> None:
    """Configure the mock registry to return a proper AppFullSnapshot."""
    snapshot = _make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot


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

    # Mock state proxy — wire public property to private mock
    hassette.state_proxy = hassette._state_proxy
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
    hassette._state_proxy.get_domain_states.side_effect = lambda domain: {
        eid: s for eid, s in hassette._state_proxy.states.items() if eid.startswith(f"{domain}.")
    }
    hassette._state_proxy.is_ready.return_value = True

    # Mock websocket service — wire public property
    hassette.websocket_service = hassette._websocket_service
    hassette._websocket_service.status = ResourceStatus.RUNNING

    # Mock app handler — wire public property
    hassette.app_handler = hassette._app_handler

    # Old snapshot (for get_app_status_snapshot)
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

    # Mock registry — new manifest snapshot (for get_all_manifests_snapshot)
    _setup_registry(hassette, [_make_manifest()])

    # Mock bus service — wire public property
    hassette.bus_service = hassette._bus_service
    hassette._bus_service.get_all_listener_metrics.return_value = []
    hassette._bus_service.get_listener_metrics_by_owner.return_value = []

    # Mock scheduler service — wire public property
    hassette.scheduler_service = hassette._scheduler_service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])
    hassette._scheduler_service.get_execution_history.return_value = []

    # Mock data_sync_service — wire public property (set later by data_sync_service fixture)
    hassette.data_sync_service = hassette._data_sync_service

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

    # Wire public properties
    hassette.state_proxy = hassette._state_proxy
    hassette.websocket_service = hassette._websocket_service
    hassette.app_handler = hassette._app_handler
    hassette.bus_service = hassette._bus_service
    hassette.scheduler_service = hassette._scheduler_service
    hassette.data_sync_service = hassette._data_sync_service

    hassette._state_proxy.states = {}
    hassette._state_proxy.is_ready.return_value = True

    hassette._websocket_service.status = ResourceStatus.RUNNING
    hassette._app_handler.get_status_snapshot.return_value = SimpleNamespace(
        running=[], failed=[], total_count=0, running_count=0, failed_count=0, only_app=None
    )
    _setup_registry(hassette, [])
    hassette._bus_service.get_all_listener_metrics.return_value = []
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])
    hassette._scheduler_service.get_execution_history.return_value = []
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
    mock_hassette.data_sync_service = ds
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
    mock_hassette_no_ui.data_sync_service = ds
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


# ──────────────────────────────────────────────────────────────────────
# Existing tests (updated for manifest-based apps page)
# ──────────────────────────────────────────────────────────────────────


class TestRootRedirect:
    async def test_root_redirects_to_ui(self, client: "AsyncClient") -> None:
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/ui/"

    async def test_root_no_redirect_when_ui_disabled(self, client_no_ui: "AsyncClient") -> None:
        response = await client_no_ui.get("/", follow_redirects=False)
        assert response.status_code == 404


class TestStaticFiles:
    async def test_css_accessible(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/css/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    async def test_js_accessible(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/js/ws-handler.js")
        assert response.status_code == 200

    async def test_live_updates_js_accessible(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/js/live-updates.js")
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
        assert "Scheduler" in body
        assert "Entities" in body

    async def test_dashboard_contains_htmx(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "htmx.org" in response.text

    async def test_dashboard_contains_health_data(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "System Health" in response.text

    async def test_dashboard_contains_bus_metrics(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "Event Bus" in response.text

    async def test_dashboard_shows_app_counts(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "1" in response.text

    async def test_dashboard_has_live_update_attributes(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        body = response.text
        assert "data-live-refresh" in body
        assert "data-live-on-app" in body

    async def test_dashboard_includes_live_updates_js(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "live-updates.js" in response.text

    async def test_dashboard_shows_scheduled_jobs_panel(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "Scheduled Jobs" in response.text

    async def test_dashboard_shows_recent_logs_panel(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "Recent Logs" in response.text

    async def test_dashboard_shows_bus_view_all_link(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert '/ui/bus"' in response.text or "/ui/bus" in response.text


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

    async def test_apps_page_shows_filter_tabs(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        body = response.text
        assert "tab-all" in body
        assert "tab-running" in body
        assert "tab-stopped" in body

    async def test_apps_page_shows_manifest_display_name(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        assert "My App" in response.text

    async def test_apps_page_shows_stopped_app(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(),
                _make_manifest(
                    app_key="stopped_app",
                    class_name="StoppedApp",
                    display_name="Stopped App",
                    status="stopped",
                ),
            ],
        )
        response = await client.get("/ui/apps")
        body = response.text
        assert "stopped_app" in body
        assert "ht-status-stopped" in body

    async def test_apps_page_shows_disabled_app(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="dis_app",
                    class_name="DisApp",
                    display_name="Disabled App",
                    enabled=False,
                    status="disabled",
                ),
            ],
        )
        response = await client.get("/ui/apps")
        assert "ht-status-disabled" in response.text

    async def test_apps_page_links_to_detail(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps")
        assert '/ui/apps/my_app"' in response.text or "/ui/apps/my_app" in response.text


class TestLogsPage:
    async def test_logs_page_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/logs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_logs_page_contains_filter_controls(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/logs")
        body = response.text
        assert "filters.level" in body
        assert "filters.app" in body
        assert "filters.search" in body

    async def test_logs_page_contains_level_options(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/logs")
        body = response.text
        assert "DEBUG" in body
        assert "ERROR" in body
        assert "CRITICAL" in body


class TestSchedulerPage:
    async def test_scheduler_page_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/scheduler")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_scheduler_page_contains_sections(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/scheduler")
        body = response.text
        assert "Scheduled Jobs" in body
        assert "Execution History" in body

    async def test_scheduler_page_empty_state(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/scheduler")
        assert "No scheduled jobs" in response.text


class TestEntitiesPage:
    async def test_entities_page_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/entities")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_entities_page_shows_domain_filter(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/entities")
        body = response.text
        assert "entity-domain-filter" in body
        assert "light" in body  # domain from mock state proxy

    async def test_entities_page_shows_entity_count(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/entities")
        assert "1 entities" in response.text


class TestAppDetailPage:
    async def test_app_detail_returns_html(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/my_app")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_app_detail_contains_manifest_info(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/my_app")
        body = response.text
        assert "My App" in body
        assert "MyApp" in body
        assert "my_app.py" in body

    async def test_app_detail_contains_sections(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/my_app")
        body = response.text
        assert "Configuration" in body
        assert "Bus Listeners" in body
        assert "Scheduled Jobs" in body
        assert "Recent Logs" in body

    async def test_app_detail_404_for_unknown(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/nonexistent")
        assert response.status_code == 404

    async def test_app_detail_has_action_buttons(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/my_app")
        body = response.text
        assert "hx-post" in body
        assert "/api/apps/my_app/" in body


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

    async def test_log_entries_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/log-entries")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_log_entries_partial_with_filters(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/log-entries?level=ERROR&app_key=my_app&limit=10")
        assert response.status_code == 200

    async def test_manifest_list_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/manifest-list")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "my_app" in response.text

    async def test_manifest_list_partial_filter_by_status(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(app_key="running_app", status="running"),
                _make_manifest(app_key="stopped_app", status="stopped"),
            ],
        )
        response = await client.get("/ui/partials/manifest-list?status=running")
        assert response.status_code == 200
        assert "running_app" in response.text
        assert "stopped_app" not in response.text

    async def test_bus_metrics_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/bus-metrics")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "Listeners" in response.text

    async def test_apps_summary_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/apps-summary")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_scheduler_jobs_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/scheduler-jobs")
        assert response.status_code == 200
        assert "No scheduled jobs" in response.text

    async def test_scheduler_history_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/scheduler-history")
        assert response.status_code == 200
        assert "No execution history" in response.text

    async def test_entity_list_partial_empty(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/entity-list")
        assert response.status_code == 200

    async def test_entity_list_partial_by_domain(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/entity-list?domain=light")
        assert response.status_code == 200
        assert "light.kitchen" in response.text

    async def test_entity_list_partial_search(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/entity-list?search=kitchen")
        assert response.status_code == 200
        assert "light.kitchen" in response.text

    async def test_entity_list_partial_search_no_match(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/entity-list?search=nonexistent")
        assert response.status_code == 200
        assert "No entities found" in response.text

    async def test_dashboard_scheduler_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/dashboard-scheduler")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "Active" in response.text
        assert "Total" in response.text
        assert "/ui/scheduler" in response.text

    async def test_dashboard_scheduler_partial_with_jobs(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        mock_hassette._scheduler_service.get_all_jobs = AsyncMock(
            return_value=[
                SimpleNamespace(
                    job_id="job-1",
                    name="check_lights",
                    owner="MyApp.MyApp[0]",
                    next_run="2024-01-01T00:05:00",
                    repeat=True,
                    cancelled=False,
                    trigger=type("interval", (), {})(),
                ),
            ]
        )
        response = await client.get("/ui/partials/dashboard-scheduler")
        assert response.status_code == 200
        # Should show count "1" for active/total/repeating
        body = response.text
        assert "Active" in body
        assert "Repeating" in body
        assert "/ui/scheduler" in body
        # Restore empty jobs
        mock_hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])

    async def test_dashboard_scheduler_partial_empty(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/dashboard-scheduler")
        assert response.status_code == 200
        assert "Active" in response.text
        assert "/ui/scheduler" in response.text

    async def test_dashboard_logs_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/dashboard-logs")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_dashboard_logs_partial_empty(self, client: "AsyncClient") -> None:
        from unittest.mock import patch

        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=None):
            response = await client.get("/ui/partials/dashboard-logs")
        assert response.status_code == 200
        assert "No recent logs" in response.text
        assert "/ui/logs" in response.text

    async def test_dashboard_logs_partial_with_entries(self, client: "AsyncClient") -> None:
        from unittest.mock import patch

        from hassette.logging_ import LogCaptureHandler

        handler = LogCaptureHandler(buffer_size=100)
        import logging

        record = logging.LogRecord(
            name="hassette.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test log message",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            response = await client.get("/ui/partials/dashboard-logs")
        assert response.status_code == 200
        assert "Test log message" in response.text
        assert "/ui/logs" in response.text

    async def test_bus_metrics_partial_has_view_all(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/bus-metrics")
        assert response.status_code == 200
        assert "/ui/bus" in response.text

    async def test_app_detail_listeners_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-detail-listeners/my_app")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_app_detail_jobs_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-detail-jobs/my_app")
        assert response.status_code == 200
        assert "<html" not in response.text


class TestInstanceDetail:
    """Instance detail page and smart routing tests."""

    async def test_single_instance_renders_instance_detail(self, client: "AsyncClient", mock_hassette) -> None:
        """Single-instance app at /apps/{app_key} should render instance detail template."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="my_app",
                    instance_count=1,
                    instances=[
                        AppInstanceInfo(
                            app_key="my_app",
                            index=0,
                            instance_name="MyApp[0]",
                            class_name="MyApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="MyApp.MyApp[0]",
                        )
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps/my_app")
        assert response.status_code == 200
        body = response.text
        # Instance detail template should show instance-specific info
        assert "Configuration" in body
        assert "Bus Listeners" in body
        assert "Scheduled Jobs" in body
        assert "instance-listeners" in body  # instance-scoped partial URL

    async def test_multi_instance_renders_manifest_overview(self, client: "AsyncClient", mock_hassette) -> None:
        """Multi-instance app at /apps/{app_key} should render manifest overview with instances table."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="multi_app",
                    display_name="Multi App",
                    instance_count=2,
                    instances=[
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=0,
                            instance_name="MultiApp[0]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="MultiApp.MultiApp[0]",
                        ),
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=1,
                            instance_name="MultiApp[1]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="MultiApp.MultiApp[1]",
                        ),
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps/multi_app")
        assert response.status_code == 200
        body = response.text
        # Should show manifest overview with instances table
        assert "Instances" in body
        assert "MultiApp[0]" in body
        assert "MultiApp[1]" in body
        assert "/ui/apps/multi_app/0" in body
        assert "/ui/apps/multi_app/1" in body

    async def test_instance_detail_route(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /apps/{app_key}/{index} should render instance detail."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="multi_app",
                    display_name="Multi App",
                    instance_count=2,
                    instances=[
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=0,
                            instance_name="MultiApp[0]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="MultiApp.MultiApp[0]",
                        ),
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=1,
                            instance_name="MultiApp[1]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="MultiApp.MultiApp[1]",
                        ),
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps/multi_app/1")
        assert response.status_code == 200
        body = response.text
        assert "Multi App" in body
        assert "MultiApp[1]" in body
        assert "instance-listeners/multi_app/1" in body

    async def test_instance_detail_404_bad_index(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /apps/{app_key}/{bad_index} should return 404."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="my_app",
                    instance_count=1,
                    instances=[
                        AppInstanceInfo(
                            app_key="my_app",
                            index=0,
                            instance_name="MyApp[0]",
                            class_name="MyApp",
                            status=ResourceStatus.RUNNING,
                        )
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps/my_app/99")
        assert response.status_code == 404

    async def test_instance_detail_404_bad_app(self, client: "AsyncClient") -> None:
        """GET /apps/{nonexistent}/{index} should return 404."""
        response = await client.get("/ui/apps/nonexistent/0")
        assert response.status_code == 404

    async def test_instance_listeners_partial(self, client: "AsyncClient") -> None:
        """Instance-scoped listeners partial returns HTML."""
        response = await client.get("/ui/partials/instance-listeners/my_app/0")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_instance_jobs_partial(self, client: "AsyncClient") -> None:
        """Instance-scoped jobs partial returns HTML."""
        response = await client.get("/ui/partials/instance-jobs/my_app/0")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_zero_instance_renders_manifest_overview(self, client: "AsyncClient", mock_hassette) -> None:
        """Zero-instance app at /apps/{app_key} should render manifest overview."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="stopped_app",
                    display_name="Stopped App",
                    status="stopped",
                    instance_count=0,
                    instances=[],
                ),
            ],
        )
        response = await client.get("/ui/apps/stopped_app")
        assert response.status_code == 200
        body = response.text
        # Should show manifest overview (not instance detail)
        assert "Stopped App" in body
        assert "Configuration" in body

    async def test_multi_instance_detail_shows_instance_column_in_listeners(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """Multi-instance manifest overview should show Instance column in bus listeners."""
        owner0 = "MultiApp.MultiApp[0]"
        owner1 = "MultiApp.MultiApp[1]"
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="multi_app",
                    display_name="Multi App",
                    instance_count=2,
                    instances=[
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=0,
                            instance_name="MultiApp[0]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id=owner0,
                        ),
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=1,
                            instance_name="MultiApp[1]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id=owner1,
                        ),
                    ],
                ),
            ],
        )
        # Set up registry._apps so get_instance_owner_map() and _resolve_owner_ids() work
        app_instances = {
            0: SimpleNamespace(unique_name=owner0),
            1: SimpleNamespace(unique_name=owner1),
        }
        mock_hassette._app_handler.registry.iter_all_instances.return_value = [
            ("multi_app", idx, inst) for idx, inst in app_instances.items()
        ]
        mock_hassette._app_handler.registry.get_apps_by_key.return_value = app_instances

        # Mock listener metrics with per-instance owner IDs
        def _make_listener_metric(owner: str) -> MagicMock:
            d = {
                "listener_id": 1,
                "owner": owner,
                "topic": "state_changed.light.kitchen",
                "handler_name": "on_light",
                "total_invocations": 5,
                "successful": 5,
                "failed": 0,
                "di_failures": 0,
                "cancelled": 0,
                "total_duration_ms": 10.0,
                "min_duration_ms": 1.0,
                "max_duration_ms": 3.0,
                "avg_duration_ms": 2.0,
                "last_invoked_at": None,
                "last_error_message": None,
                "last_error_type": None,
            }
            m = MagicMock()
            m.to_dict.return_value = d
            return m

        mock_hassette._bus_service.get_listener_metrics_by_owner.side_effect = lambda owner: [
            _make_listener_metric(owner)
        ]
        response = await client.get("/ui/apps/multi_app")
        assert response.status_code == 200
        body = response.text
        assert "<th>Instance</th>" in body
        assert "/ui/apps/multi_app/0" in body
        assert "/ui/apps/multi_app/1" in body

    async def test_multi_instance_detail_shows_instance_column_in_jobs(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """Multi-instance manifest overview should show Instance column in scheduled jobs."""
        owner0 = "MultiApp.MultiApp[0]"
        owner1 = "MultiApp.MultiApp[1]"
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="multi_app",
                    display_name="Multi App",
                    instance_count=2,
                    instances=[
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=0,
                            instance_name="MultiApp[0]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id=owner0,
                        ),
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=1,
                            instance_name="MultiApp[1]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                            owner_id=owner1,
                        ),
                    ],
                ),
            ],
        )
        app_instances = {
            0: SimpleNamespace(unique_name=owner0),
            1: SimpleNamespace(unique_name=owner1),
        }
        mock_hassette._app_handler.registry.iter_all_instances.return_value = [
            ("multi_app", idx, inst) for idx, inst in app_instances.items()
        ]
        mock_hassette._app_handler.registry.get_apps_by_key.return_value = app_instances
        mock_hassette._scheduler_service.get_all_jobs = AsyncMock(
            return_value=[
                SimpleNamespace(
                    job_id="job-1",
                    name="my_task",
                    owner=owner0,
                    next_run="2024-01-01T00:05:00",
                    repeat=True,
                    cancelled=False,
                    trigger=type("interval", (), {})(),
                ),
            ]
        )
        response = await client.get("/ui/apps/multi_app")
        assert response.status_code == 200
        body = response.text
        # Jobs section should also have Instance column
        assert "my_task" in body
        # The instance column header appears in both listeners and jobs sections
        assert body.count("<th>Instance</th>") >= 1

    async def test_single_instance_detail_no_instance_column(self, client: "AsyncClient", mock_hassette) -> None:
        """Single-instance app at /apps/{app_key} should NOT show Instance column."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="my_app",
                    instance_count=1,
                    instances=[
                        AppInstanceInfo(
                            app_key="my_app",
                            index=0,
                            instance_name="MyApp[0]",
                            class_name="MyApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="MyApp.MyApp[0]",
                        )
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps/my_app")
        assert response.status_code == 200
        body = response.text
        # Single-instance uses app_instance_detail.html which does NOT have Instance column
        assert "<th>Instance</th>" not in body

    async def test_instance_scoped_listeners_partial_no_instance_column(self, client: "AsyncClient") -> None:
        """Instance-scoped listeners partial should NOT show Instance column."""
        response = await client.get("/ui/partials/instance-listeners/my_app/0")
        assert response.status_code == 200
        assert "<th>Instance</th>" not in response.text

    async def test_instance_scoped_jobs_partial_no_instance_column(self, client: "AsyncClient") -> None:
        """Instance-scoped jobs partial should NOT show Instance column."""
        response = await client.get("/ui/partials/instance-jobs/my_app/0")
        assert response.status_code == 200
        assert "<th>Instance</th>" not in response.text

    async def test_multi_instance_listing_shows_group(self, client: "AsyncClient", mock_hassette) -> None:
        """Apps listing page should show grouped rows for multi-instance apps."""
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(
                    app_key="multi_app",
                    display_name="Multi App",
                    instance_count=2,
                    instances=[
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=0,
                            instance_name="MultiApp[0]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                        ),
                        AppInstanceInfo(
                            app_key="multi_app",
                            index=1,
                            instance_name="MultiApp[1]",
                            class_name="MultiApp",
                            status=ResourceStatus.RUNNING,
                        ),
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps")
        assert response.status_code == 200
        body = response.text
        assert "2 instances" in body
        assert "MultiApp[0]" in body
        assert "MultiApp[1]" in body


class TestManifestAPI:
    """REST API endpoint for manifests."""

    async def test_get_manifests(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/manifests")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["running"] == 1
        assert len(data["manifests"]) == 1
        assert data["manifests"][0]["app_key"] == "my_app"

    async def test_get_manifests_mixed_states(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(
            mock_hassette,
            [
                _make_manifest(app_key="running_app", status="running"),
                _make_manifest(app_key="stopped_app", status="stopped"),
                _make_manifest(app_key="failed_app", status="failed", error_message="boom"),
                _make_manifest(app_key="disabled_app", status="disabled", enabled=False),
            ],
        )
        response = await client.get("/api/apps/manifests")
        data = response.json()
        assert data["total"] == 4
        assert data["running"] == 1
        assert data["stopped"] == 1
        assert data["failed"] == 1
        assert data["disabled"] == 1

    async def test_get_manifests_empty(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(mock_hassette, [])
        response = await client.get("/api/apps/manifests")
        data = response.json()
        assert data["total"] == 0
        assert data["manifests"] == []


class TestEmptyStates:
    """Pages handle empty data gracefully."""

    async def test_dashboard_no_apps(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(mock_hassette, [])
        response = await client.get("/ui/")
        assert response.status_code == 200
        assert "No apps configured" in response.text

    async def test_apps_page_no_apps(self, client: "AsyncClient", mock_hassette) -> None:
        _setup_registry(mock_hassette, [])
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


# ──────────────────────────────────────────────────────────────────────
# Unit tests for AppRegistry.get_full_snapshot()
# ──────────────────────────────────────────────────────────────────────


class TestAppRegistryGetFullSnapshot:
    """Unit tests for get_full_snapshot() status derivation."""

    def _make_registry(self):
        from hassette.core.app_registry import AppRegistry

        return AppRegistry()

    def _make_manifest_obj(self, app_key: str, enabled: bool = True, auto_loaded: bool = False):
        """Build a minimal AppManifest-like object for the registry."""
        return SimpleNamespace(
            app_key=app_key,
            class_name=f"{app_key.title().replace('_', '')}",
            display_name=app_key.replace("_", " ").title(),
            filename=f"{app_key}.py",
            enabled=enabled,
            auto_loaded=auto_loaded,
        )

    def _make_app_instance(self, app_key: str, index: int = 0):
        """Build a minimal App-like object for the registry."""
        class_name = app_key.title().replace("_", "")
        instance_name = f"{app_key}.{index}"
        return SimpleNamespace(
            app_config=SimpleNamespace(instance_name=instance_name),
            class_name=class_name,
            status=ResourceStatus.RUNNING,
            unique_name=f"{class_name}.{instance_name}",
        )

    def test_empty_manifests(self):
        reg = self._make_registry()
        snap = reg.get_full_snapshot()
        assert snap.total == 0
        assert snap.manifests == []

    def test_running_app(self):
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        reg.register_app("my_app", 0, self._make_app_instance("my_app"))
        snap = reg.get_full_snapshot()
        assert snap.total == 1
        assert snap.running == 1
        assert snap.manifests[0].status == "running"
        assert snap.manifests[0].instance_count == 1

    def test_stopped_app(self):
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        # No instances registered — status is "stopped"
        snap = reg.get_full_snapshot()
        assert snap.stopped == 1
        assert snap.manifests[0].status == "stopped"

    def test_failed_app(self):
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        reg.record_failure("my_app", 0, RuntimeError("init error"))
        snap = reg.get_full_snapshot()
        assert snap.failed == 1
        assert snap.manifests[0].status == "failed"
        assert snap.manifests[0].error_message == "init error"

    def test_disabled_app(self):
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app", enabled=False)})
        snap = reg.get_full_snapshot()
        assert snap.disabled == 1
        assert snap.manifests[0].status == "disabled"

    def test_blocked_app(self):
        from hassette.types.enums import BlockReason

        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app")})
        reg.block_app("my_app", BlockReason.ONLY_APP)
        snap = reg.get_full_snapshot()
        assert snap.blocked == 1
        assert snap.manifests[0].status == "blocked"
        assert snap.manifests[0].block_reason == "only_app"

    def test_mixed_states(self):
        from hassette.types.enums import BlockReason

        reg = self._make_registry()
        reg.set_manifests(
            {
                "running_app": self._make_manifest_obj("running_app"),
                "stopped_app": self._make_manifest_obj("stopped_app"),
                "failed_app": self._make_manifest_obj("failed_app"),
                "disabled_app": self._make_manifest_obj("disabled_app", enabled=False),
                "blocked_app": self._make_manifest_obj("blocked_app"),
            }
        )
        reg.register_app("running_app", 0, self._make_app_instance("running_app"))
        reg.record_failure("failed_app", 0, ValueError("bad config"))
        reg.block_app("blocked_app", BlockReason.ONLY_APP)

        snap = reg.get_full_snapshot()
        assert snap.total == 5
        assert snap.running == 1
        assert snap.stopped == 1
        assert snap.failed == 1
        assert snap.disabled == 1
        assert snap.blocked == 1

        statuses = {m.app_key: m.status for m in snap.manifests}
        assert statuses["running_app"] == "running"
        assert statuses["stopped_app"] == "stopped"
        assert statuses["failed_app"] == "failed"
        assert statuses["disabled_app"] == "disabled"
        assert statuses["blocked_app"] == "blocked"

    def test_disabled_takes_priority_over_running(self):
        """Even if an app has running instances, disabled=False should win."""
        reg = self._make_registry()
        reg.set_manifests({"my_app": self._make_manifest_obj("my_app", enabled=False)})
        reg.register_app("my_app", 0, self._make_app_instance("my_app"))
        snap = reg.get_full_snapshot()
        # Disabled takes priority
        assert snap.manifests[0].status == "disabled"
