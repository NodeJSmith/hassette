"""Integration tests for the Hassette Web UI (pages, partials, static assets)."""

import logging
import re
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.core.app_registry import AppInstanceInfo
from hassette.logging_ import LogCaptureHandler
from hassette.test_utils.web_helpers import (
    make_listener_metric,
    make_manifest,
    make_old_snapshot,
    setup_registry,
)
from hassette.test_utils.web_mocks import create_mock_data_sync_service
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance with UI enabled."""
    from hassette.test_utils.web_mocks import create_hassette_stub

    hassette = create_hassette_stub(
        states={
            "light.kitchen": {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 255},
                "last_changed": "2024-01-01T00:00:00",
                "last_updated": "2024-01-01T00:00:00",
            },
        },
        manifests=[make_manifest()],
        old_snapshot=make_old_snapshot(),
    )
    return hassette


@pytest.fixture
def mock_hassette_no_ui():
    """Create a mock Hassette instance with UI disabled."""
    from hassette.test_utils.web_mocks import create_hassette_stub

    return create_hassette_stub(run_web_ui=False)


@pytest.fixture
def data_sync_service_no_ui(mock_hassette_no_ui):
    """Create a DataSyncService for the no-UI variant."""

    return create_mock_data_sync_service(mock_hassette_no_ui)


@pytest.fixture
def app_no_ui(mock_hassette_no_ui, data_sync_service_no_ui):  # noqa: ARG001
    return create_fastapi_app(mock_hassette_no_ui)


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

    async def test_live_updates_js_uses_morph_swap(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/static/js/live-updates.js")
        assert response.status_code == 200
        assert "morph:innerHTML" in response.text

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
        assert "Event Bus" in body

    @pytest.mark.parametrize(
        "expected_text",
        [
            pytest.param("htmx.org", id="contains_htmx"),
            pytest.param("Apps", id="contains_apps_panel"),
            pytest.param("Activity", id="contains_activity_panel"),
            pytest.param("idiomorph", id="includes_idiomorph_script"),
            pytest.param("live-updates.js", id="includes_live_updates_js"),
            pytest.param("Recent Logs", id="shows_recent_logs_panel"),
        ],
    )
    async def test_dashboard_contains(self, client: "AsyncClient", expected_text: str) -> None:
        response = await client.get("/ui/")
        assert expected_text in response.text

    async def test_dashboard_has_live_update_attributes(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        body = response.text
        assert "data-live-on-state" in body
        assert "data-live-on-app" in body

    async def test_dashboard_has_no_live_refresh_attribute(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        assert "data-live-refresh" not in response.text

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
        setup_registry(
            mock_hassette,
            [
                make_manifest(),
                make_manifest(
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
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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

    async def test_scheduler_page_has_live_on_app_attributes(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/scheduler")
        body = response.text
        assert "data-live-on-app" in body
        assert "data-live-refresh" not in body


class TestBusPage:
    async def test_bus_page_has_live_on_app_attributes(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/bus")
        assert response.status_code == 200
        body = response.text
        assert "data-live-on-app" in body
        assert "data-live-refresh" not in body


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
        assert "App Key" in body
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

    async def test_app_detail_has_live_on_app_attributes(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/my_app")
        body = response.text
        assert "data-live-on-app" in body
        assert "data-live-refresh" not in body


class TestPartials:
    """Partial endpoints return HTML fragments, not full pages."""

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
        setup_registry(
            mock_hassette,
            [
                make_manifest(app_key="running_app", status="running"),
                make_manifest(app_key="stopped_app", status="stopped"),
            ],
        )
        response = await client.get("/ui/partials/manifest-list?status=running")
        assert response.status_code == 200
        assert "running_app" in response.text
        assert "stopped_app" not in response.text

    async def test_scheduler_jobs_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/scheduler-jobs")
        assert response.status_code == 200
        assert "No scheduled jobs" in response.text

    async def test_scheduler_history_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/scheduler-history")
        assert response.status_code == 200
        assert "No execution history" in response.text

    async def test_dashboard_app_grid_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/dashboard-app-grid")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "my_app" in response.text

    async def test_dashboard_timeline_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/dashboard-timeline")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_dashboard_logs_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/dashboard-logs")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_dashboard_logs_partial_empty(self, client: "AsyncClient") -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=None):
            response = await client.get("/ui/partials/dashboard-logs")
        assert response.status_code == 200
        assert "No recent logs" in response.text
        assert "/ui/logs" in response.text

    async def test_dashboard_logs_partial_with_entries(self, client: "AsyncClient") -> None:
        handler = LogCaptureHandler(buffer_size=100)
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

    async def test_app_detail_listeners_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-detail-listeners/my_app")
        assert response.status_code == 200
        assert "<html" not in response.text

    async def test_app_detail_jobs_partial(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/partials/app-detail-jobs/my_app")
        assert response.status_code == 200
        assert "<html" not in response.text


def _make_log_handler_with_app_key() -> LogCaptureHandler:
    """Create a LogCaptureHandler with mixed app and core log entries."""
    handler = LogCaptureHandler(buffer_size=100)
    handler.register_app_logger("hassette.apps.my_app", "my_app")
    entries = [
        ("hassette.core", logging.INFO, "Core startup message"),
        ("hassette.apps.my_app", logging.INFO, "MyApp initialized"),
        ("hassette.apps.my_app", logging.WARNING, "Light unresponsive"),
        ("hassette.core", logging.DEBUG, "Heartbeat sent"),
        ("hassette.apps.my_app", logging.ERROR, "Service call failed"),
    ]
    for logger_name, level, msg in entries:
        record = logging.LogRecord(
            name=logger_name, level=level, pathname="test.py", lineno=1, msg=msg, args=(), exc_info=None
        )
        handler.emit(record)
    return handler


class TestLogFiltering:
    """Tests that log endpoints filter correctly by app_key."""

    async def test_log_entries_partial_filters_by_app_key(self, client: "AsyncClient") -> None:
        handler = _make_log_handler_with_app_key()
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            response = await client.get("/ui/partials/log-entries?app_key=my_app")
        assert response.status_code == 200
        assert "MyApp initialized" in response.text
        assert "Light unresponsive" in response.text
        assert "Service call failed" in response.text
        assert "Core startup message" not in response.text
        assert "Heartbeat sent" not in response.text

    async def test_log_entries_partial_without_filter_shows_all(self, client: "AsyncClient") -> None:
        handler = _make_log_handler_with_app_key()
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            response = await client.get("/ui/partials/log-entries")
        assert response.status_code == 200
        assert "MyApp initialized" in response.text
        assert "Core startup message" in response.text

    async def test_api_logs_recent_filters_by_app_key(self, client: "AsyncClient") -> None:
        handler = _make_log_handler_with_app_key()
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            response = await client.get("/api/logs/recent?app_key=my_app")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        messages = [e["message"] for e in data]
        assert "MyApp initialized" in messages
        assert "Light unresponsive" in messages
        assert "Service call failed" in messages
        # Core-only logs should not be present
        assert "Core startup message" not in messages
        assert "Heartbeat sent" not in messages

    async def test_api_logs_recent_without_filter_returns_all(self, client: "AsyncClient") -> None:
        handler = _make_log_handler_with_app_key()
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
        messages = [e["message"] for e in data]
        assert "Core startup message" in messages
        assert "MyApp initialized" in messages


class TestInstanceDetail:
    """Instance detail page and smart routing tests."""

    async def test_single_instance_renders_instance_detail(self, client: "AsyncClient", mock_hassette) -> None:
        """Single-instance app at /apps/{app_key} should render instance detail template."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        assert "App Key" in body
        assert "Bus Listeners" in body
        assert "Scheduled Jobs" in body
        assert "instance-listeners" in body  # instance-scoped partial URL

    async def test_multi_instance_renders_instance_detail_with_switcher(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """Multi-instance app at /apps/{app_key} should render instance detail with instance switcher."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        # Should show instance detail with switcher dropdown
        assert "App Key" in body
        assert "Bus Listeners" in body
        # Instance switcher contains links to both instances
        assert "/ui/apps/multi_app/0" in body
        assert "/ui/apps/multi_app/1" in body
        assert "MultiApp[0]" in body
        assert "MultiApp[1]" in body

    async def test_instance_detail_has_live_on_app_attributes(self, client: "AsyncClient", mock_hassette) -> None:
        """Instance detail page should use data-live-on-app, not data-live-refresh."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        response = await client.get("/ui/apps/multi_app/0")
        assert response.status_code == 200
        body = response.text
        assert "data-live-on-app" in body
        assert "data-live-refresh" not in body

    async def test_instance_detail_route(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /apps/{app_key}/{index} should render instance detail."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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

    async def test_default_page_uses_actual_instance_index(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /apps/{app_key} should use the actual instance index, not hardcoded 0."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
                    app_key="offset_app",
                    instance_count=1,
                    instances=[
                        AppInstanceInfo(
                            app_key="offset_app",
                            index=3,
                            instance_name="OffsetApp[3]",
                            class_name="OffsetApp",
                            status=ResourceStatus.RUNNING,
                            owner_id="OffsetApp.OffsetApp[3]",
                        )
                    ],
                ),
            ],
        )
        response = await client.get("/ui/apps/offset_app")
        assert response.status_code == 200
        body = response.text
        # Partial URLs must reference the real instance index (3), not hardcoded 0
        assert "instance-listeners/offset_app/3" in body
        assert "instance-jobs/offset_app/3" in body
        assert "instance-listeners/offset_app/0" not in body
        assert "instance-jobs/offset_app/0" not in body

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

    async def test_zero_instance_renders_instance_detail(self, client: "AsyncClient", mock_hassette) -> None:
        """Zero-instance app at /apps/{app_key} should render instance detail."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        assert "Stopped App" in body
        assert "App Key" in body

    async def test_multi_instance_detail_no_instance_column_in_listeners(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """Multi-instance at /apps/{app_key} renders instance detail (index 0), no Instance column."""
        owner0 = "MultiApp.MultiApp[0]"
        owner1 = "MultiApp.MultiApp[1]"
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        response = await client.get("/ui/apps/multi_app")
        assert response.status_code == 200
        body = response.text
        # Instance detail (index 0) should NOT have Instance column
        assert "<th>Instance</th>" not in body
        # Instance switcher should contain links to both instances
        assert "/ui/apps/multi_app/0" in body
        assert "/ui/apps/multi_app/1" in body

    async def test_multi_instance_detail_shows_switcher_and_jobs(self, client: "AsyncClient", mock_hassette) -> None:
        """Multi-instance at /apps/{app_key} renders instance detail with switcher and jobs."""
        owner0 = "MultiApp.MultiApp[0]"
        owner1 = "MultiApp.MultiApp[1]"
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        response = await client.get("/ui/apps/multi_app")
        assert response.status_code == 200
        body = response.text
        # Instance switcher should be present
        assert "MultiApp[0]" in body
        assert "MultiApp[1]" in body
        # Scheduled Jobs section visible (flat layout, no tabs)
        assert "Scheduled Jobs" in body

    async def test_single_instance_detail_no_instance_column(self, client: "AsyncClient", mock_hassette) -> None:
        """Single-instance app at /apps/{app_key} should NOT show Instance column."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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
        setup_registry(
            mock_hassette,
            [
                make_manifest(
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


class TestBusListenersPartial:
    """Tests for the /partials/bus-listeners HTMX endpoint."""

    async def test_bus_listeners_partial_empty(self, client: "AsyncClient") -> None:
        """Empty listener list renders the empty-state message."""
        response = await client.get("/ui/partials/bus-listeners")
        assert response.status_code == 200
        assert "<html" not in response.text
        assert "No bus listeners registered" in response.text

    async def test_bus_listeners_partial_with_data(self, client: "AsyncClient", mock_hassette) -> None:
        """Listeners owned by registered apps render in the table."""
        owner_id = "MyApp.MyApp[0]"
        mock_hassette._bus_service.get_all_listener_metrics.return_value = [
            make_listener_metric(1, owner_id, "state_changed.light.kitchen", "on_light_change"),
        ]
        mock_hassette._bus_service.get_listener_metrics_by_owner.side_effect = (
            lambda owner: mock_hassette._bus_service.get_all_listener_metrics.return_value if owner == owner_id else []
        )
        # Wire up owner map so the filter in partials.py includes this listener
        mock_hassette._app_handler.registry.iter_all_instances.return_value = iter(
            [("my_app", 0, MagicMock(unique_name=owner_id))]
        )
        response = await client.get("/ui/partials/bus-listeners")
        assert response.status_code == 200
        body = response.text
        assert "on_light_change" in body
        assert "light.kitchen" in body

    async def test_bus_listeners_partial_filters_internal_owners(self, client: "AsyncClient", mock_hassette) -> None:
        """Listeners owned by internal services (not user apps) are filtered out."""
        internal_owner = "hassette.core.BusService"
        mock_hassette._bus_service.get_all_listener_metrics.return_value = [
            make_listener_metric(1, internal_owner, "state_changed.*", "internal_handler"),
        ]
        mock_hassette._bus_service.get_listener_metrics_by_owner.side_effect = (
            lambda owner: mock_hassette._bus_service.get_all_listener_metrics.return_value
            if owner == internal_owner
            else []
        )
        mock_hassette._app_handler.registry.iter_all_instances.return_value = iter([])
        response = await client.get("/ui/partials/bus-listeners")
        assert response.status_code == 200
        assert "internal_handler" not in response.text
        assert "No bus listeners registered" in response.text

    async def test_bus_listeners_partial_shows_table_headers(self, client: "AsyncClient", mock_hassette) -> None:
        """When listeners exist, the table headers are present."""
        owner_id = "MyApp.MyApp[0]"
        mock_hassette._bus_service.get_all_listener_metrics.return_value = [
            make_listener_metric(1, owner_id, "state_changed.light.kitchen", "on_light_change"),
        ]
        mock_hassette._bus_service.get_listener_metrics_by_owner.side_effect = (
            lambda owner: mock_hassette._bus_service.get_all_listener_metrics.return_value if owner == owner_id else []
        )
        mock_hassette._app_handler.registry.iter_all_instances.return_value = iter(
            [("my_app", 0, MagicMock(unique_name=owner_id))]
        )
        response = await client.get("/ui/partials/bus-listeners")
        body = response.text
        for header in ("Handler", "App", "Topic", "Invocations", "Success", "Failed", "Avg Duration"):
            assert header in body


class TestAlertFailedAppsPartial:
    """Tests for the /partials/alert-failed-apps HTMX endpoint."""

    async def test_alert_no_failed_apps(self, client: "AsyncClient") -> None:
        """No failed apps means the partial renders empty (no alert)."""
        response = await client.get("/ui/partials/alert-failed-apps")
        assert response.status_code == 200
        assert response.text.strip() == ""

    async def test_alert_with_failed_app(self, client: "AsyncClient", mock_hassette) -> None:
        """A failed app renders the danger alert with app key and error message."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(app_key="broken_app", status="failed", error_message="Import error in module"),
            ],
        )
        response = await client.get("/ui/partials/alert-failed-apps")
        assert response.status_code == 200
        body = response.text
        assert "1 app(s) failed" in body
        assert "broken_app" in body
        assert "Import error in module" in body
        assert "ht-alert--danger" in body

    async def test_alert_with_failed_app_traceback(self, client: "AsyncClient", mock_hassette) -> None:
        """A failed app with a traceback includes the traceback toggle."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(
                    app_key="broken_app",
                    status="failed",
                    error_message="Import error",
                    error_traceback="Traceback (most recent call last):\n  File ...",
                ),
            ],
        )
        response = await client.get("/ui/partials/alert-failed-apps")
        body = response.text
        assert "ht-traceback" in body
        assert "Traceback (most recent call last)" in body

    async def test_alert_multiple_failed_apps(self, client: "AsyncClient", mock_hassette) -> None:
        """Multiple failed apps show the correct count."""
        setup_registry(
            mock_hassette,
            [
                make_manifest(app_key="broken_1", status="failed", error_message="Error 1"),
                make_manifest(app_key="broken_2", status="failed", error_message="Error 2"),
                make_manifest(app_key="running_ok", status="running"),
            ],
        )
        response = await client.get("/ui/partials/alert-failed-apps")
        body = response.text
        assert "2 app(s) failed" in body
        assert "broken_1" in body
        assert "broken_2" in body

    async def test_alert_is_html_fragment(self, client: "AsyncClient", mock_hassette) -> None:
        """Alert partial is an HTML fragment, not a full page."""
        setup_registry(
            mock_hassette,
            [make_manifest(app_key="broken", status="failed", error_message="boom")],
        )
        response = await client.get("/ui/partials/alert-failed-apps")
        assert "<html" not in response.text
        assert "<!DOCTYPE" not in response.text


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
        setup_registry(
            mock_hassette,
            [
                make_manifest(app_key="running_app", status="running"),
                make_manifest(app_key="stopped_app", status="stopped"),
                make_manifest(app_key="failed_app", status="failed", error_message="boom"),
                make_manifest(app_key="disabled_app", status="disabled", enabled=False),
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
        setup_registry(mock_hassette, [])
        response = await client.get("/api/apps/manifests")
        data = response.json()
        assert data["total"] == 0
        assert data["manifests"] == []


class TestEmptyStates:
    """Pages handle empty data gracefully."""

    async def test_dashboard_no_apps(self, client: "AsyncClient", mock_hassette) -> None:
        setup_registry(mock_hassette, [])
        response = await client.get("/ui/")
        assert response.status_code == 200
        assert "No apps configured" in response.text

    async def test_apps_page_no_apps(self, client: "AsyncClient", mock_hassette) -> None:
        setup_registry(mock_hassette, [])
        response = await client.get("/ui/apps")
        assert response.status_code == 200
        assert "No apps are configured" in response.text


class TestSidebarStructure:
    """Sidebar HTML structure tests — validate elements rendered correctly."""

    async def test_sidebar_brand_link(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        html = response.text
        assert 'class="ht-brand-link"' in html
        assert 'href="/ui/"' in html
        assert "<img" in html
        assert 'class="ht-brand-text"' in html

    async def test_sidebar_no_close_button(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        html = response.text
        assert not re.search(r"\bht-sidebar-close\b", html)
        assert "fa-xmark" not in html

    async def test_sidebar_toggle_button_exists(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        html = response.text
        assert "ht-sidebar-toggle" in html
        assert "fa-bars" in html

    async def test_nav_links_no_individual_click_handlers(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        html = response.text
        # Extract nav link <a> tags — they should not have @click attributes
        nav_links = re.findall(r'<a\s+href="/ui/[^"]*"[^>]*>', html)
        assert len(nav_links) >= 5, f"Expected at least 5 nav links, found {len(nav_links)}"
        for link in nav_links:
            assert "@click" not in link, f"Nav link should not have @click: {link}"

    async def test_status_bar_has_menu_toggle(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        html = response.text
        assert "ht-menu-toggle" in html
        assert "ht-status-bar" in html

    async def test_sidebar_resize_handler(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/")
        html = response.text
        assert "@resize.window" in html


class TestErrorPages:
    """Error responses render full HTML pages with #page-content for hx-boost."""

    async def test_ui_404_returns_html_with_page_content(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/nonexistent")
        assert response.status_code == 404
        body = response.text
        assert 'id="page-content"' in body
        assert "404" in body

    async def test_ui_404_extends_base_layout(self, client: "AsyncClient") -> None:
        response = await client.get("/ui/apps/nonexistent")
        body = response.text
        assert "ht-layout" in body
        assert "ht-sidebar" in body
        assert "Back to Dashboard" in body

    async def test_api_404_still_returns_json(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


class TestUIDisabled:
    async def test_ui_routes_not_available(self, client_no_ui: "AsyncClient") -> None:
        response = await client_no_ui.get("/ui/")
        assert response.status_code == 404

    async def test_api_still_works(self, client_no_ui: "AsyncClient") -> None:
        response = await client_no_ui.get("/api/healthz")
        assert response.status_code == 200
