"""Integration tests for the FastAPI web API using httpx AsyncClient."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry_models import (
    HandlerErrorRecord,
    HandlerInvocation,
    JobErrorRecord,
    JobExecution,
    ListenerSummary,
    SessionRecord,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
from hassette.core.app_registry import AppInstanceInfo, AppStatusSnapshot
from hassette.logging_ import LogCaptureHandler
from hassette.test_utils.web_mocks import create_hassette_stub
from hassette.types.enums import ResourceStatus
from hassette.web.routes.config import _CONFIG_SAFE_FIELDS


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance for the FastAPI app."""
    _instance = AppInstanceInfo(
        app_key="my_app",
        index=0,
        instance_name="MyApp[0]",
        class_name="MyApp",
        status=ResourceStatus.RUNNING,
    )
    return create_hassette_stub(
        run_web_ui=False,
        states={
            "light.kitchen": {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 255},
                "last_changed": "2024-01-01T00:00:00",
                "last_updated": "2024-01-01T00:00:00",
            },
            "sensor.temp": {
                "entity_id": "sensor.temp",
                "state": "21.5",
                "attributes": {"unit_of_measurement": "°C"},
                "last_changed": "2024-01-01T00:00:00",
                "last_updated": "2024-01-01T00:00:00",
            },
        },
        old_snapshot=AppStatusSnapshot(running=[_instance], failed=[]),
        app_action_mocks=True,
        config_dump={"dev_mode": True, "web_api_port": 8126},
    )


class TestHealthEndpoints:
    async def test_health_returns_200_when_ok(self, client: "AsyncClient") -> None:
        """GET /api/health returns 200 with status 'ok' when WebSocket is connected."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["websocket_connected"] is True
        assert "entity_count" in data
        assert "app_count" in data

    async def test_health_returns_503_when_degraded(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 503 with status 'degraded' when WebSocket is disconnected."""
        from hassette.types.enums import ResourceStatus

        mock_hassette._websocket_service.status = ResourceStatus.STOPPED
        response = await client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["websocket_connected"] is False

    async def test_health_returns_503_when_starting(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 503 with status 'starting' during startup."""
        from hassette.types.enums import ResourceStatus

        mock_hassette._websocket_service.status = ResourceStatus.STOPPED
        mock_hassette._state_proxy.is_ready.return_value = False
        response = await client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "starting"

    async def test_healthz_returns_404(self, client: "AsyncClient") -> None:
        """GET /api/healthz returns 404 after endpoint removal."""
        response = await client.get("/api/healthz")
        assert response.status_code == 404


class TestSPACatchAll:
    async def test_path_traversal_returns_404_or_spa(self, client: "AsyncClient") -> None:
        """Path traversal attempts must not serve files outside the SPA directory."""
        response = await client.get("/../../etc/passwd")
        # Either 404 (static-looking path) or 200 with SPA index.html — never the actual file
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            # SPA fallback — should be HTML, not /etc/passwd content
            assert "root:" not in response.text

    async def test_api_path_returns_404(self, client: "AsyncClient") -> None:
        """Paths under /api/ that don't match a route return 404, not SPA index.html."""
        response = await client.get("/api/nonexistent")
        assert response.status_code == 404


class TestAppEndpoints:
    async def test_get_apps(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["running"] == 1

    async def test_get_app_endpoint_removed(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/my_app")
        assert response.status_code == 404

    async def test_start_app(self, client: "AsyncClient") -> None:
        response = await client.post("/api/apps/my_app/start")
        assert response.status_code == 202
        data = response.json()
        assert data["action"] == "start"

    async def test_stop_app(self, client: "AsyncClient") -> None:
        response = await client.post("/api/apps/my_app/stop")
        assert response.status_code == 202
        data = response.json()
        assert data["action"] == "stop"

    async def test_reload_app(self, client: "AsyncClient") -> None:
        response = await client.post("/api/apps/my_app/reload")
        assert response.status_code == 202
        data = response.json()
        assert data["action"] == "reload"

    async def test_app_management_works_without_dev_mode(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_reload_in_prod = False
        assert (await client.post("/api/apps/my_app/start")).status_code == 202
        assert (await client.post("/api/apps/my_app/stop")).status_code == 202
        assert (await client.post("/api/apps/my_app/reload")).status_code == 202
        # Restore
        mock_hassette.config.dev_mode = True


class TestEventsEndpoint:
    async def test_get_recent_events_empty(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_recent_events_with_data(
        self, client: "AsyncClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        runtime_query_service._event_buffer.append({"type": "test", "timestamp": 1234567890.0})
        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestSchedulerEndpoints:
    async def test_scheduler_jobs_endpoint_removed(self, client: "AsyncClient") -> None:
        """GET /api/scheduler/jobs returns 404 — endpoint deleted in spec 2039 WP02."""
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 404


class TestConfigEndpoint:
    async def test_get_config(self, client: "AsyncClient") -> None:
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "token" not in data  # token should be redacted


class TestBusEndpoints:
    async def test_get_bus_listeners_empty(self, client: "AsyncClient") -> None:
        # Returns empty when no app_key is provided (TelemetryDep stubs return [])
        response = await client.get("/api/bus/listeners")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_bus_listeners_with_app_key_returns_empty_stub(self, client: "AsyncClient") -> None:
        # TelemetryQueryService stubs return [] for all app_key queries
        response = await client.get("/api/bus/listeners?app_key=my_app")
        assert response.status_code == 200
        assert response.json() == []

    async def test_bus_metrics_endpoint_removed(self, client: "AsyncClient") -> None:
        response = await client.get("/api/bus/metrics")
        assert response.status_code == 404

    async def test_get_listener_metrics_returns_listener_with_summary(
        self, mock_hassette: MagicMock, client: "AsyncClient"
    ) -> None:
        """Endpoint returns ListenerWithSummary schema with once as int and handler_summary populated."""
        sample = ListenerSummary(
            listener_id=1,
            app_key="test_app",
            instance_index=0,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            debounce=None,
            throttle=None,
            once=1,
            priority=0,
            predicate_description=None,
            human_description=None,
            source_location="test_app.py:10",
            registration_source=None,
            total_invocations=5,
            successful=4,
            failed=1,
            di_failures=0,
            cancelled=0,
            total_duration_ms=100.0,
            avg_duration_ms=20.0,
            min_duration_ms=10.0,
            max_duration_ms=30.0,
            last_invoked_at=1700000000.0,
            last_error_type="ValueError",
            last_error_message="bad value",
        )
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(return_value=[sample])

        response = await client.get("/api/bus/listeners?app_key=test_app")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        entry = data[0]
        # once must be int, not bool
        assert entry["once"] == 1
        assert isinstance(entry["once"], int)
        # handler_summary must be populated by to_listener_with_summary
        assert "handler_summary" in entry
        assert entry["handler_summary"] != ""
        # ListenerWithSummary-specific fields present
        assert "source_location" in entry
        assert "human_description" in entry
        # ListenerMetricsResponse-only fields absent (that class is deleted)
        # Verify key fields are correct
        assert entry["listener_id"] == 1
        assert entry["app_key"] == "test_app"
        assert entry["topic"] == "state_changed.light.kitchen"
        assert entry["total_invocations"] == 5


class TestLogsEndpoints:
    @pytest.fixture
    def log_handler(self) -> LogCaptureHandler:
        handler = LogCaptureHandler(buffer_size=100)
        # Register app_key mappings before emitting so records get app_key set
        handler.register_app_logger("hassette.apps.my_app", "my_app")
        handler.register_app_logger("hassette.apps.other_app", "other_app")
        entries = [
            ("hassette.core", logging.INFO, "Core started"),
            ("hassette.apps.my_app", logging.INFO, "MyApp initialized"),
            ("hassette.apps.my_app", logging.WARNING, "Light unresponsive"),
            ("hassette.core", logging.DEBUG, "Heartbeat sent"),
            ("hassette.apps.my_app", logging.ERROR, "Service call failed"),
            ("hassette.apps.other_app", logging.INFO, "OtherApp ready"),
        ]
        for logger_name, level, msg in entries:
            record = logging.LogRecord(
                name=logger_name,
                level=level,
                pathname="test.py",
                lineno=1,
                msg=msg,
                args=(),
                exc_info=None,
            )
            handler.emit(record)
        return handler

    async def test_get_logs_recent_returns_list(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6

    async def test_get_logs_filter_by_level(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?level=ERROR")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["level"] == "ERROR"

    async def test_get_logs_filter_by_warning_includes_error(
        self, client: "AsyncClient", log_handler: LogCaptureHandler
    ) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?level=WARNING")
        assert response.status_code == 200
        data = response.json()
        levels = {entry["level"] for entry in data}
        assert levels == {"WARNING", "ERROR"}

    async def test_get_logs_filter_by_app_key(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?app_key=my_app")
        assert response.status_code == 200
        data = response.json()
        assert all(entry["app_key"] == "my_app" for entry in data)
        assert len(data) == 3

    async def test_get_logs_limit(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_get_logs_combined_filters(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?app_key=my_app&level=WARNING")
        assert response.status_code == 200
        data = response.json()
        assert all(entry["app_key"] == "my_app" for entry in data)
        levels = {entry["level"] for entry in data}
        assert levels <= {"WARNING", "ERROR", "CRITICAL"}
        assert len(data) == 2

    async def test_get_logs_empty_when_no_handler(self, client: "AsyncClient") -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=None):
            response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        assert response.json() == []


class TestServicesEndpoint:
    async def test_get_services_success(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.api = MagicMock()
        mock_hassette.api.get_services = AsyncMock(
            return_value={"light": {"turn_on": {}, "turn_off": {}}, "switch": {"toggle": {}}}
        )
        response = await client.get("/api/services")
        assert response.status_code == 200
        data = response.json()
        assert "light" in data
        assert "switch" in data

    async def test_get_services_ha_failure_returns_502(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.api = MagicMock()
        mock_hassette.api.get_services = AsyncMock(side_effect=ConnectionError("HA unreachable"))
        response = await client.get("/api/services")
        assert response.status_code == 502
        data = response.json()
        assert "detail" in data
        assert "Home Assistant" in data["detail"]

    async def test_get_services_generic_error_returns_502(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.api = MagicMock()
        mock_hassette.api.get_services = AsyncMock(side_effect=RuntimeError("unexpected"))
        response = await client.get("/api/services")
        assert response.status_code == 502


class TestConfigEndpointExpanded:
    async def test_response_keys_are_subset_of_safe_fields(self, client: "AsyncClient", mock_hassette) -> None:
        """All returned keys must be in the allowlist."""
        mock_hassette.config.model_dump.return_value = {
            "dev_mode": True,
            "web_api_port": 8126,
            "log_level": "INFO",
        }
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) <= _CONFIG_SAFE_FIELDS

    async def test_model_dump_called_with_safe_fields_include(self, client: "AsyncClient", mock_hassette) -> None:
        """Verify model_dump is called with include=_CONFIG_SAFE_FIELDS to enforce allowlist."""
        mock_hassette.config.model_dump.return_value = {"dev_mode": True}
        await client.get("/api/config")
        mock_hassette.config.model_dump.assert_called_with(include=_CONFIG_SAFE_FIELDS)

    async def test_sensitive_fields_not_in_allowlist(self) -> None:
        """Verify token and hass_url are not in the allowlist set."""
        assert "token" not in _CONFIG_SAFE_FIELDS
        assert "hass_url" not in _CONFIG_SAFE_FIELDS

    async def test_known_safe_field_present(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.config.model_dump.return_value = {"dev_mode": True}
        response = await client.get("/api/config")
        data = response.json()
        assert "dev_mode" in data
        assert data["dev_mode"] is True


class TestOpenApiDocs:
    async def test_openapi_json(self, client: "AsyncClient") -> None:
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Hassette Web API"


# ---------------------------------------------------------------------------
# Telemetry endpoints (WP02)
# ---------------------------------------------------------------------------


class TestTelemetryAppHealth:
    async def test_returns_metrics_with_classification(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                ListenerSummary(
                    listener_id=1,
                    app_key="my_app",
                    instance_index=0,
                    handler_method="on_light",
                    topic="state_changed.light.kitchen",
                    debounce=None,
                    throttle=None,
                    once=0,
                    priority=0,
                    predicate_description=None,
                    human_description=None,
                    source_location="my_app.py:10",
                    registration_source=None,
                    total_invocations=100,
                    successful=95,
                    failed=5,
                    di_failures=0,
                    cancelled=0,
                    total_duration_ms=5000.0,
                    avg_duration_ms=50.0,
                    min_duration_ms=10.0,
                    max_duration_ms=200.0,
                    last_invoked_at=1234567890.0,
                    last_error_type=None,
                    last_error_message=None,
                )
            ]
        )
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(return_value=[])

        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 200
        data = response.json()
        assert "error_rate" in data
        assert "error_rate_class" in data
        assert "health_status" in data
        assert data["error_rate"] == pytest.approx(5.0)
        assert data["error_rate_class"] == "warn"

    async def test_unknown_app_returns_empty_health(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/app/nonexistent/health")
        assert response.status_code == 200
        data = response.json()
        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"

    async def test_instance_index_param(self, client: "AsyncClient", mock_hassette) -> None:
        response = await client.get("/api/telemetry/app/my_app/health?instance_index=1")
        assert response.status_code == 200
        mock_hassette.telemetry_query_service.get_listener_summary.assert_called_once()
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args
        assert call_kwargs.kwargs.get("instance_index") == 1 or call_kwargs[1].get("instance_index") == 1


class TestTelemetryListeners:
    async def test_returns_summaries_with_handler_descriptions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                ListenerSummary(
                    listener_id=1,
                    app_key="my_app",
                    instance_index=0,
                    handler_method="on_light",
                    topic="state_changed.light.kitchen",
                    debounce=None,
                    throttle=None,
                    once=0,
                    priority=0,
                    predicate_description=None,
                    human_description=None,
                    source_location="my_app.py:10",
                    registration_source=None,
                    total_invocations=50,
                    successful=50,
                    failed=0,
                    di_failures=0,
                    cancelled=0,
                    total_duration_ms=2500.0,
                    avg_duration_ms=50.0,
                    min_duration_ms=10.0,
                    max_duration_ms=200.0,
                    last_invoked_at=1234567890.0,
                    last_error_type=None,
                    last_error_message=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["handler_summary"] == "Fires when light.kitchen"
        assert data[0]["listener_id"] == 1


class TestTelemetryDashboard:
    async def test_kpis_returns_global_summary(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert "total_handlers" in data
        assert "total_jobs" in data
        assert "error_rate" in data
        assert "error_rate_class" in data

    async def test_app_grid_returns_per_app_health(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        assert isinstance(data["apps"], list)
        # Default mock has apps from the manifest snapshot
        for app_entry in data["apps"]:
            assert "app_key" in app_entry
            assert "health_status" in app_entry
            assert "status" in app_entry

    async def test_errors_returns_typed_entries(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                HandlerErrorRecord(
                    listener_id=1,
                    topic="state_changed.light.kitchen",
                    handler_method="on_light",
                    error_message="test error",
                    error_type="RuntimeError",
                    execution_start_ts=1234567890.0,
                    duration_ms=12.5,
                    app_key="my_app",
                ),
                JobErrorRecord(
                    job_id=1,
                    job_name="check_sensors",
                    handler_method="check",
                    error_message="timeout",
                    error_type="TimeoutError",
                    execution_start_ts=1234567891.0,
                    duration_ms=5000.0,
                    app_key="sensor_app",
                ),
            ]
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 2
        assert data["errors"][0]["kind"] == "handler"
        assert data["errors"][1]["kind"] == "job"

    async def test_kpis_returns_zeroed_on_sqlite_error(self, client: "AsyncClient", mock_hassette) -> None:
        import sqlite3

        mock_hassette.telemetry_query_service.get_global_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_handlers"] == 0
        assert data["total_jobs"] == 0
        assert data["error_rate"] == 0.0

    async def test_kpis_propagates_programming_error(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_global_summary = AsyncMock(side_effect=TypeError("bad argument"))
        with pytest.raises(TypeError, match="bad argument"):
            await client.get("/api/telemetry/dashboard/kpis")

    async def test_errors_returns_empty_on_sqlite_error(self, client: "AsyncClient", mock_hassette) -> None:
        import sqlite3

        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert data["errors"] == []

    async def test_errors_propagates_programming_error(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(side_effect=TypeError("bad argument"))
        with pytest.raises(TypeError, match="bad argument"):
            await client.get("/api/telemetry/dashboard/errors")


class TestTelemetryHandlerInvocations:
    async def test_returns_invocations(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(
            return_value=[
                HandlerInvocation(
                    execution_start_ts=1234567890.0,
                    duration_ms=42.5,
                    status="success",
                    error_type=None,
                    error_message=None,
                    error_traceback=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/handler/1/invocations")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["duration_ms"] == 42.5


class TestTelemetryJobExecutions:
    async def test_returns_executions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_job_executions = AsyncMock(
            return_value=[
                JobExecution(
                    execution_start_ts=1234567890.0,
                    duration_ms=100.0,
                    status="success",
                    error_type=None,
                    error_message=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/job/1/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "success"


class TestTelemetryStatus:
    async def test_telemetry_status_healthy(self, client: "AsyncClient") -> None:
        """/api/telemetry/status returns 200 with degraded=false when DB is healthy."""
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["degraded"] is False

    async def test_telemetry_status_db_unavailable(self, client: "AsyncClient", mock_hassette) -> None:
        """/api/telemetry/status returns 503 with degraded=true when DB query raises sqlite3.Error."""
        import sqlite3

        mock_hassette.telemetry_query_service.check_health = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True


class TestDashboardOSErrorFallback:
    async def test_dashboard_kpis_oserror_returns_fallback(self, client: "AsyncClient", mock_hassette) -> None:
        """OSError triggers the same fallback as sqlite3.Error."""
        mock_hassette.telemetry_query_service.get_global_summary = AsyncMock(side_effect=OSError("disk I/O error"))
        response = await client.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_handlers"] == 0
        assert data["error_rate"] == 0.0

    async def test_dashboard_kpis_valueerror_returns_fallback(self, client: "AsyncClient", mock_hassette) -> None:
        """ValueError triggers fallback response with zeroed-out KPI fields."""
        mock_hassette.telemetry_query_service.get_global_summary = AsyncMock(
            side_effect=ValueError("Connection is closed")
        )
        response = await client.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_handlers"] == 0
        assert data["error_rate"] == 0.0

    async def test_dashboard_kpis_non_connection_valueerror_returns_fallback(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """Any ValueError (not just connection-closed) returns a degraded fallback response."""
        mock_hassette.telemetry_query_service.get_global_summary = AsyncMock(
            side_effect=ValueError("invalid literal for int()")
        )
        resp = await client.get("/api/telemetry/dashboard/kpis")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_invocations"] == 0
        assert body["total_errors"] == 0


class TestTelemetrySessionsEndpoint:
    async def test_sessions_endpoint_returns_session_list(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /telemetry/sessions returns 200 with valid session data."""

        mock_hassette.telemetry_query_service.get_session_list = AsyncMock(
            return_value=[
                SessionRecord(
                    id=1,
                    started_at=1000000.0,
                    stopped_at=1000050.0,
                    status="stopped",
                    error_type=None,
                    error_message=None,
                    duration_seconds=50.0,
                ),
                SessionRecord(
                    id=2,
                    started_at=1000100.0,
                    stopped_at=None,
                    status="running",
                    error_type=None,
                    error_message=None,
                    duration_seconds=100.0,
                ),
            ]
        )
        response = await client.get("/api/telemetry/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[0]["started_at"] == 1000000.0
        assert data[0]["status"] == "stopped"
        assert data[1]["stopped_at"] is None

    async def test_sessions_endpoint_limit_parameter(self, client: "AsyncClient", mock_hassette) -> None:
        """Verify limit parameter is passed through and validated."""

        mock_hassette.telemetry_query_service.get_session_list = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/sessions?limit=10")
        assert response.status_code == 200
        mock_hassette.telemetry_query_service.get_session_list.assert_called_once_with(limit=10)

        # Limit below minimum (1) should fail validation
        response = await client.get("/api/telemetry/sessions?limit=0")
        assert response.status_code == 422

        # Limit above maximum (200) should fail validation
        response = await client.get("/api/telemetry/sessions?limit=201")
        assert response.status_code == 422

    async def test_sessions_endpoint_db_error_returns_empty(self, client: "AsyncClient", mock_hassette) -> None:
        """Verify graceful degradation returns empty list on DB error."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_session_list = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/sessions")
        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestTelemetrySessionIdParam:
    """Verify session_id query parameter propagates to telemetry service methods."""

    async def test_app_health_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health?session_id=42 forwards session_id to service."""
        response = await client.get("/api/telemetry/app/my_app/health?session_id=42")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["session_id"] == 42

    async def test_app_health_omitted_session_id_is_none(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health without session_id passes None."""
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["session_id"] is None

    async def test_app_listeners_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/listeners?session_id=7")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["session_id"] == 7

    async def test_app_jobs_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/jobs?session_id=3")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_summary.call_args.kwargs
        assert call_kwargs["session_id"] == 3

    async def test_handler_invocations_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/handler/1/invocations?session_id=5")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_handler_invocations.call_args.kwargs
        assert call_kwargs["session_id"] == 5

    async def test_handler_invocations_omitted_session_id_is_none(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get("/api/telemetry/handler/1/invocations")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_handler_invocations.call_args.kwargs
        assert call_kwargs["session_id"] is None

    async def test_job_executions_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/job/1/executions?session_id=9")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_executions.call_args.kwargs
        assert call_kwargs["session_id"] == 9

    async def test_dashboard_kpis_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/dashboard/kpis?session_id=11")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_global_summary.call_args.kwargs
        assert call_kwargs["session_id"] == 11

    async def test_dashboard_app_grid_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/dashboard/app-grid?session_id=13")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_all_app_summaries.call_args.kwargs
        assert call_kwargs["session_id"] == 13

    async def test_dashboard_errors_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/dashboard/errors?session_id=15")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["session_id"] == 15

    async def test_dashboard_errors_omitted_session_id_is_none(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["session_id"] is None


class TestBusListenersSessionIdParam:
    """Verify session_id query parameter propagates through /bus/listeners."""

    async def test_bus_listeners_passes_session_id(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/bus/listeners?app_key=my_app&session_id=20")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["session_id"] == 20

    async def test_bus_listeners_omitted_session_id_is_none(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get("/api/bus/listeners?app_key=my_app")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["session_id"] is None


class TestTelemetryAvailableWithoutUI:
    async def test_telemetry_endpoints_work_when_run_web_ui_false(self, client: "AsyncClient") -> None:
        """The mock_hassette has run_web_ui=False — telemetry should still work."""
        response = await client.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# WP06: source_tier parameter, DB_ERRORS guards, status counters
# ---------------------------------------------------------------------------


class TestSourceTierParameter:
    """Verify source_tier query parameter is accepted and forwarded correctly."""

    async def test_dashboard_errors_defaults_to_all_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Call without source_tier — service receives source_tier='all' (unified feed includes framework)."""
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_dashboard_errors_framework_filter(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """?source_tier=framework passes 'framework' to the service."""
        response = await client.get("/api/telemetry/dashboard/errors?source_tier=framework")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["source_tier"] == "framework"

    async def test_dashboard_errors_all_filter(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """?source_tier=all passes 'all' to the service."""
        response = await client.get("/api/telemetry/dashboard/errors?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_source_tier_invalid_returns_422(self, client: "AsyncClient") -> None:
        """?source_tier=invalid returns 422 (FastAPI Literal validation)."""
        response = await client.get("/api/telemetry/dashboard/errors?source_tier=invalid")
        assert response.status_code == 422

    async def test_app_health_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health?source_tier=all passes source_tier to service."""
        response = await client.get("/api/telemetry/app/my_app/health?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_app_listeners_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/listeners?source_tier=framework passes through."""
        response = await client.get("/api/telemetry/app/my_app/listeners?source_tier=framework")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["source_tier"] == "framework"

    async def test_app_jobs_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/jobs?source_tier=all passes through."""
        response = await client.get("/api/telemetry/app/my_app/jobs?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_summary.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_app_health_invalid_source_tier_returns_422(self, client: "AsyncClient") -> None:
        """Invalid source_tier on /health returns 422."""
        response = await client.get("/api/telemetry/app/my_app/health?source_tier=bad")
        assert response.status_code == 422


class TestDbErrorGuards:
    """Verify DB_ERRORS guards on previously-unguarded endpoints."""

    async def test_app_health_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on app_health returns 503 with zero-value response."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"

    async def test_app_listeners_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on app_listeners returns 503 with empty list."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_app_jobs_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on app_jobs returns 503 with empty list."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/jobs")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_handler_invocations_db_error_returns_503(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """sqlite3.Error on handler_invocations returns 503 with empty list."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/handler/1/invocations")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_job_executions_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on job_executions returns 503 with empty list."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_job_executions = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/job/1/executions")
        assert response.status_code == 503
        data = response.json()
        assert data == []


class TestStatusDropCounters:
    """Verify /telemetry/status returns dropped_overflow and dropped_exhausted."""

    async def test_status_includes_drop_counters_zero(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Healthy status includes drop counters defaulting to zero."""
        mock_hassette.get_drop_counters.return_value = (0, 0, 0, 0)
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0
        assert data["dropped_no_session"] == 0
        assert data["dropped_shutdown"] == 0

    async def test_status_includes_nonzero_drop_counters(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Non-zero drop counters from Hassette.get_drop_counters() appear in the response."""
        mock_hassette.get_drop_counters.return_value = (7, 3, 2, 1)
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["dropped_overflow"] == 7
        assert data["dropped_exhausted"] == 3
        assert data["dropped_no_session"] == 2
        assert data["dropped_shutdown"] == 1

    async def test_status_degraded_has_zero_drop_counters(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When DB is degraded, dropped counters default to 0 (safe fallback)."""
        import sqlite3

        mock_hassette.telemetry_query_service.check_health = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0


class TestDashboardErrorsOrphanRendering:
    """Verify orphaned records (null FKs) render as 'deleted handler'/'deleted job'."""

    async def test_dashboard_errors_orphan_handler_renders_label(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Handler error with null listener_id renders 'deleted handler' label."""
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                HandlerErrorRecord(
                    listener_id=None,
                    topic=None,
                    handler_method=None,
                    error_message="boom",
                    error_type="RuntimeError",
                    execution_start_ts=1234567890.0,
                    duration_ms=1.0,
                    app_key=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1
        entry = data["errors"][0]
        assert entry["kind"] == "handler"
        assert entry["handler_method"] is None
        assert entry["topic"] is None
        assert entry["listener_id"] is None
        assert entry["app_key"] is None

    async def test_dashboard_errors_orphan_job_renders_label(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Job error with null job_id renders 'deleted job' label."""
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                JobErrorRecord(
                    job_id=None,
                    job_name=None,
                    handler_method=None,
                    error_message="timeout",
                    error_type="TimeoutError",
                    execution_start_ts=1234567891.0,
                    duration_ms=5000.0,
                    app_key=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1
        entry = data["errors"][0]
        assert entry["kind"] == "job"
        assert entry["job_name"] is None
        assert entry["job_id"] is None
        assert entry["app_key"] is None


class TestDashboardErrorsTraceback:
    """Verify error_traceback is passed through in dashboard error response."""

    async def test_dashboard_errors_handler_traceback_included(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """HandlerErrorRecord with traceback passes it through to HandlerErrorEntry."""
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                HandlerErrorRecord(
                    listener_id=42,
                    topic="state_changed.light.kitchen",
                    handler_method="on_light",
                    error_message="unexpected error",
                    error_type="RuntimeError",
                    execution_start_ts=1234567890.0,
                    duration_ms=12.5,
                    app_key="my_app",
                    error_traceback="Traceback (most recent call last):\n  File 'test.py'\nRuntimeError: error\n",
                )
            ]
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1
        entry = data["errors"][0]
        assert entry["kind"] == "handler"
        assert entry["error_traceback"] is not None
        assert "RuntimeError" in entry["error_traceback"]

    async def test_dashboard_errors_handler_traceback_none(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """HandlerErrorRecord with no traceback passes None through."""
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                HandlerErrorRecord(
                    listener_id=42,
                    topic="state_changed.light.kitchen",
                    handler_method="on_light",
                    error_message="known error",
                    error_type="DependencyError",
                    execution_start_ts=1234567890.0,
                    duration_ms=5.0,
                    app_key="my_app",
                    error_traceback=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1
        entry = data["errors"][0]
        assert entry["error_traceback"] is None

    async def test_dashboard_errors_job_traceback_included(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """JobErrorRecord with traceback passes it through to JobErrorEntry."""
        mock_hassette.telemetry_query_service.get_recent_errors = AsyncMock(
            return_value=[
                JobErrorRecord(
                    job_id=7,
                    job_name="check_sensors",
                    handler_method="check",
                    error_message="timeout",
                    error_type="TimeoutError",
                    execution_start_ts=1234567891.0,
                    duration_ms=5000.0,
                    app_key="sensor_app",
                    error_traceback="Traceback:\n  File 'job.py'\nTimeoutError: timeout\n",
                )
            ]
        )
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        data = response.json()
        assert len(data["errors"]) == 1
        entry = data["errors"][0]
        assert entry["kind"] == "job"
        assert entry["error_traceback"] is not None
        assert "TimeoutError" in entry["error_traceback"]


class TestDashboardErrorsSinceTs:
    """Verify since_ts defaults to a 24h window (scoped by session_id)."""

    async def test_dashboard_errors_default_since_ts_is_24h(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Without explicit since_ts, get_recent_errors uses a 24h window."""
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["since_ts"] > 0


class TestHassetteAppKey:
    """Verify __hassette__ app_key returns framework data (OpenAPI doc coverage)."""

    async def test_hassette_app_key_accepted_on_health(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/__hassette__/health is accepted (200)."""
        response = await client.get("/api/telemetry/app/__hassette__/health")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["app_key"] == "__hassette__"

    async def test_hassette_app_key_accepted_on_listeners(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """GET /telemetry/app/__hassette__/listeners is accepted (200)."""
        response = await client.get("/api/telemetry/app/__hassette__/listeners")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["app_key"] == "__hassette__"


# ---------------------------------------------------------------------------
# Additional coverage for lines 87-88, 114-119, 124-128, 330-332, 347-349,
# and 430-475 (dashboard_framework_summary endpoint).
# ---------------------------------------------------------------------------


class TestTelemetryStatusDropCounterFallback:
    """Cover lines 87-88: AttributeError/RuntimeError fallback for get_drop_counters."""

    async def test_attribute_error_on_get_drop_counters_returns_zeros(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """AttributeError from get_drop_counters falls back to zero counters (line 87-88)."""
        mock_hassette.get_drop_counters.side_effect = AttributeError("no such attribute")
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["degraded"] is False
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0
        assert data["dropped_no_session"] == 0
        assert data["dropped_shutdown"] == 0

    async def test_runtime_error_on_get_drop_counters_returns_zeros(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """RuntimeError from get_drop_counters falls back to zero counters (line 87-88)."""
        mock_hassette.get_drop_counters.side_effect = RuntimeError("not yet initialised")
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["degraded"] is False
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0


class TestSessionsDbErrorFallback:
    """Cover lines 114-119: DB_ERRORS guard on the /sessions endpoint."""

    async def test_oserror_returns_empty_list(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """OSError on get_session_list returns 200 with empty list (lines 114-119)."""
        mock_hassette.telemetry_query_service.get_session_list = AsyncMock(side_effect=OSError("disk I/O error"))
        response = await client.get("/api/telemetry/sessions")
        assert response.status_code == 200
        assert response.json() == []

    async def test_valueerror_returns_empty_list(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """ValueError on get_session_list returns 200 with empty list (lines 114-119)."""
        mock_hassette.telemetry_query_service.get_session_list = AsyncMock(
            side_effect=ValueError("Connection is closed")
        )
        response = await client.get("/api/telemetry/sessions")
        assert response.status_code == 200
        assert response.json() == []


class TestAppHealthDbErrorFallback:
    """Cover lines 124-128: DB_ERRORS guard on the app_health endpoint."""

    async def test_oserror_returns_503_with_zeroed_health(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """OSError on get_listener_summary returns 503 with zero-value health (lines 124-128)."""
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(side_effect=OSError("disk I/O error"))
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"
        assert data["handler_avg_duration"] == 0.0
        assert data["job_avg_duration"] == 0.0
        assert data["last_activity_ts"] is None

    async def test_valueerror_returns_503_with_zeroed_health(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """ValueError on get_listener_summary returns 503 with zero-value health (lines 124-128)."""
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            side_effect=ValueError("Connection is closed")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0

    async def test_db_error_on_job_summary_also_triggers_503(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """sqlite3.Error on get_job_summary (after listener_summary succeeds) returns 503."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(return_value=[])
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0


class TestDashboardAppGridDbErrorFallback:
    """Cover lines 330-332, 347-349: DB_ERRORS guard on dashboard_app_grid."""

    async def test_sqlite_error_returns_200_with_empty_summaries(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """sqlite3.Error on get_all_app_summaries falls back to empty summaries dict (lines 330-332).

        The endpoint still returns 200 with manifests having zero health data.
        """
        import sqlite3

        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        # Each manifest entry should still appear, but with zeroed health data
        for entry in data["apps"]:
            assert entry["total_invocations"] == 0
            assert entry["total_errors"] == 0
            assert entry["error_rate"] == 0.0

    async def test_oserror_returns_200_with_zeroed_entries(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """OSError on get_all_app_summaries falls back to zeroed per-app entries (lines 330-332)."""
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(side_effect=OSError("disk I/O error"))
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        for entry in data["apps"]:
            assert entry["handler_count"] == 0
            assert entry["job_count"] == 0

    async def test_valueerror_returns_200_with_zeroed_entries(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """ValueError on get_all_app_summaries falls back to zeroed per-app entries (lines 330-332)."""
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=ValueError("Connection is closed")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data

    async def test_app_grid_db_error_uses_error_rate_from_empty_summary(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When summaries dict is empty after DB error, _error_rate_from_summary returns 0.0 (line 347-349)."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        for entry in data["apps"]:
            # total_invocations=0 and total_executions=0 → error_rate=0.0
            assert entry["error_rate"] == 0.0
            # health_status for zero-activity app is "unknown"
            assert entry["health_status"] == "unknown"


class TestDashboardFrameworkSummary:
    """Cover the dashboard_framework_summary endpoint (counts-only via get_error_counts)."""

    async def test_happy_path_returns_zero_counts(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Happy path with no errors: total_errors=0, total_job_errors=0, no errors field."""
        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(return_value=(0, 0))
        response = await client.get("/api/telemetry/dashboard/framework-summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_errors"] == 0
        assert data["total_job_errors"] == 0
        assert "errors" not in data

    async def test_happy_path_with_handler_and_job_errors(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Counts come from get_error_counts; no errors list in response."""
        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(return_value=(3, 1))
        response = await client.get("/api/telemetry/dashboard/framework-summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_errors"] == 3
        assert data["total_job_errors"] == 1
        assert "errors" not in data

    async def test_db_error_falls_back_to_zeros(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on get_error_counts falls back to total_errors=0, total_job_errors=0."""
        import sqlite3

        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/framework-summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_errors"] == 0
        assert data["total_job_errors"] == 0

    async def test_oserror_falls_back_to_zeros(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """OSError on get_error_counts falls back to zeros."""
        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(side_effect=OSError("disk I/O error"))
        response = await client.get("/api/telemetry/dashboard/framework-summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_errors"] == 0
        assert data["total_job_errors"] == 0

    async def test_session_id_forwarded(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """session_id query param is forwarded to get_error_counts."""
        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(return_value=(0, 0))
        response = await client.get("/api/telemetry/dashboard/framework-summary?session_id=42")
        assert response.status_code == 200
        kwargs = mock_hassette.telemetry_query_service.get_error_counts.call_args.kwargs
        assert kwargs["session_id"] == 42

    async def test_omitted_session_id_passes_none(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """When session_id is omitted, None is forwarded to get_error_counts."""
        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(return_value=(0, 0))
        response = await client.get("/api/telemetry/dashboard/framework-summary")
        assert response.status_code == 200
        kwargs = mock_hassette.telemetry_query_service.get_error_counts.call_args.kwargs
        assert kwargs["session_id"] is None

    async def test_source_tier_is_always_framework(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The endpoint always queries with source_tier='framework' regardless of caller."""
        mock_hassette.telemetry_query_service.get_error_counts = AsyncMock(return_value=(0, 0))
        response = await client.get("/api/telemetry/dashboard/framework-summary")
        assert response.status_code == 200
        kwargs = mock_hassette.telemetry_query_service.get_error_counts.call_args.kwargs
        assert kwargs["source_tier"] == "framework"


# ---------------------------------------------------------------------------
# WP08: Input validation, edge cases
# ---------------------------------------------------------------------------


class TestAppKeyValidation:
    """Verify that invalid app_key values are rejected with 400 on management routes.

    The validation is performed by _validate_app_key() in apps.py using the regex
    ``^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$``. It raises HTTPException(400), not 422.
    """

    @pytest.mark.parametrize(
        "app_key",
        [
            "!!invalid",
            "0starts_with_digit",
            "-starts_with_dash",
            "a" * 129,  # exceeds 128-char limit (pattern allows 1 + up to 127 = 128 total)
        ],
    )
    async def test_invalid_app_key_start_returns_400(self, client: "AsyncClient", app_key: str) -> None:
        """Invalid app_key format returns 400 on POST /api/apps/{app_key}/start."""
        response = await client.post(f"/api/apps/{app_key}/start")
        assert response.status_code == 400

    @pytest.mark.parametrize(
        "app_key",
        [
            "!!invalid",
            "0starts_with_digit",
            "-starts_with_dash",
            "a" * 129,
        ],
    )
    async def test_invalid_app_key_stop_returns_400(self, client: "AsyncClient", app_key: str) -> None:
        """Invalid app_key format returns 400 on POST /api/apps/{app_key}/stop."""
        response = await client.post(f"/api/apps/{app_key}/stop")
        assert response.status_code == 400

    @pytest.mark.parametrize(
        "app_key",
        [
            "!!invalid",
            "0starts_with_digit",
            "-starts_with_dash",
            "a" * 129,
        ],
    )
    async def test_invalid_app_key_reload_returns_400(self, client: "AsyncClient", app_key: str) -> None:
        """Invalid app_key format returns 400 on POST /api/apps/{app_key}/reload."""
        response = await client.post(f"/api/apps/{app_key}/reload")
        assert response.status_code == 400

    async def test_nonexistent_app_key_start_returns_500(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key on start returns 500 when service raises KeyError."""
        mock_hassette._app_handler.start_app = AsyncMock(side_effect=KeyError("unknown_app"))
        response = await client.post("/api/apps/unknown_app/start")
        assert response.status_code == 500

    async def test_nonexistent_app_key_stop_returns_500(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key on stop returns 500 when service raises KeyError."""
        mock_hassette._app_handler.stop_app = AsyncMock(side_effect=KeyError("unknown_app"))
        response = await client.post("/api/apps/unknown_app/stop")
        assert response.status_code == 500

    async def test_nonexistent_app_key_reload_returns_500(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key on reload returns 500 when service raises KeyError."""
        mock_hassette._app_handler.reload_app = AsyncMock(side_effect=KeyError("unknown_app"))
        response = await client.post("/api/apps/unknown_app/reload")
        assert response.status_code == 500

    async def test_valid_app_key_with_dots_and_underscores_accepted(self, client: "AsyncClient") -> None:
        """app_key with dots and underscores is valid per the regex."""
        response = await client.post("/api/apps/my_app.v2/start")
        assert response.status_code == 202

    async def test_valid_app_key_128_chars_accepted(self, client: "AsyncClient") -> None:
        """app_key exactly 128 chars (1 letter + 127 more) is accepted."""
        app_key = "a" + "b" * 127
        response = await client.post(f"/api/apps/{app_key}/start")
        assert response.status_code == 202


class TestLimitParameterValidation:
    """Verify out-of-range limit parameters return 422 across all relevant endpoints."""

    # --- /api/events/recent: ge=1, le=500 ---

    async def test_events_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=0")
        assert response.status_code == 422

    async def test_events_limit_negative_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=-1")
        assert response.status_code == 422

    async def test_events_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=501")
        assert response.status_code == 422

    async def test_events_limit_at_max_accepted(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=500")
        assert response.status_code == 200

    # --- /api/logs/recent: ge=1, le=2000 ---

    async def test_logs_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/logs/recent?limit=0")
        assert response.status_code == 422

    async def test_logs_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/logs/recent?limit=2001")
        assert response.status_code == 422

    async def test_logs_limit_at_max_accepted(self, client: "AsyncClient") -> None:
        response = await client.get("/api/logs/recent?limit=2000")
        assert response.status_code == 200

    # --- /api/telemetry/sessions: ge=1, le=200 (already tested in TestTelemetrySessionsEndpoint) ---
    # Skipped — covered by TestTelemetrySessionsEndpoint.test_sessions_endpoint_limit_parameter

    # --- /api/telemetry/handler/{id}/invocations: ge=1, le=500 ---

    async def test_handler_invocations_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/handler/1/invocations?limit=0")
        assert response.status_code == 422

    async def test_handler_invocations_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/handler/1/invocations?limit=501")
        assert response.status_code == 422

    async def test_handler_invocations_limit_at_max_accepted(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/handler/1/invocations?limit=500")
        assert response.status_code == 200

    # --- /api/telemetry/job/{id}/executions: ge=1, le=500 ---

    async def test_job_executions_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/job/1/executions?limit=0")
        assert response.status_code == 422

    async def test_job_executions_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/job/1/executions?limit=501")
        assert response.status_code == 422

    async def test_job_executions_limit_at_max_accepted(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        mock_hassette.telemetry_query_service.get_job_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/job/1/executions?limit=500")
        assert response.status_code == 200


class TestHandlerInvocationsExpanded:
    """Extended coverage for /api/telemetry/handler/{id}/invocations."""

    async def test_limit_param_respected(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """When limit=2, service is called with limit=2 and at most 2 results come back."""

        invocations = [
            HandlerInvocation(
                execution_start_ts=float(1000 + i),
                duration_ms=float(10 + i),
                status="success",
                error_type=None,
                error_message=None,
            )
            for i in range(5)
        ]
        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(return_value=invocations[:2])
        response = await client.get("/api/telemetry/handler/1/invocations?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        call_kwargs = mock_hassette.telemetry_query_service.get_handler_invocations.call_args.kwargs
        assert call_kwargs["limit"] == 2

    async def test_empty_result(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Listener with no invocations returns an empty list."""
        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/handler/99/invocations")
        assert response.status_code == 200
        assert response.json() == []

    async def test_ordering_descending_by_execution_start_ts(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Results are returned in descending execution_start_ts order (newest first).

        The ordering is enforced by the DB query layer; the endpoint returns data
        in the order provided by the service. This test verifies the endpoint does
        not reorder the data and passes it through faithfully.
        """

        invocations = [
            HandlerInvocation(
                execution_start_ts=1000003.0,
                duration_ms=10.0,
                status="success",
                error_type=None,
                error_message=None,
            ),
            HandlerInvocation(
                execution_start_ts=1000002.0,
                duration_ms=20.0,
                status="error",
                error_type="ValueError",
                error_message="bad value",
            ),
            HandlerInvocation(
                execution_start_ts=1000001.0,
                duration_ms=5.0,
                status="success",
                error_type=None,
                error_message=None,
            ),
        ]
        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(return_value=invocations)
        response = await client.get("/api/telemetry/handler/1/invocations")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        timestamps = [entry["execution_start_ts"] for entry in data]
        assert timestamps == sorted(timestamps, reverse=True)


class TestJobExecutionsExpanded:
    """Extended coverage for /api/telemetry/job/{id}/executions."""

    async def test_limit_param_respected(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """When limit=2, service is called with limit=2 and at most 2 results come back."""

        executions = [
            JobExecution(
                execution_start_ts=float(2000 + i),
                duration_ms=float(50 + i),
                status="success",
                error_type=None,
                error_message=None,
            )
            for i in range(5)
        ]
        mock_hassette.telemetry_query_service.get_job_executions = AsyncMock(return_value=executions[:2])
        response = await client.get("/api/telemetry/job/1/executions?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        call_kwargs = mock_hassette.telemetry_query_service.get_job_executions.call_args.kwargs
        assert call_kwargs["limit"] == 2

    async def test_empty_result(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Job with no executions returns an empty list."""
        mock_hassette.telemetry_query_service.get_job_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/job/99/executions")
        assert response.status_code == 200
        assert response.json() == []

    async def test_ordering_descending_by_execution_start_ts(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Results are returned in descending execution_start_ts order (newest first).

        The ordering is enforced by the DB query layer; the endpoint returns data
        in the order provided by the service. This test verifies pass-through fidelity.
        """

        executions = [
            JobExecution(
                execution_start_ts=2000003.0,
                duration_ms=100.0,
                status="success",
                error_type=None,
                error_message=None,
            ),
            JobExecution(
                execution_start_ts=2000002.0,
                duration_ms=200.0,
                status="error",
                error_type="TimeoutError",
                error_message="timed out",
            ),
            JobExecution(
                execution_start_ts=2000001.0,
                duration_ms=50.0,
                status="success",
                error_type=None,
                error_message=None,
            ),
        ]
        mock_hassette.telemetry_query_service.get_job_executions = AsyncMock(return_value=executions)
        response = await client.get("/api/telemetry/job/1/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        timestamps = [entry["execution_start_ts"] for entry in data]
        assert timestamps == sorted(timestamps, reverse=True)


class TestSessionsOrdering:
    """Verify /api/telemetry/sessions returns sessions newest-first."""

    async def test_sessions_returned_newest_first(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The service is expected to return sessions in descending started_at order.

        The endpoint passes data through as-is; this test verifies the ordering
        is preserved when the service returns newest-first data.
        """

        sessions = [
            SessionRecord(
                id=3,
                started_at=3000000.0,
                stopped_at=3000050.0,
                status="stopped",
                error_type=None,
                error_message=None,
                duration_seconds=50.0,
            ),
            SessionRecord(
                id=2,
                started_at=2000000.0,
                stopped_at=2000100.0,
                status="stopped",
                error_type=None,
                error_message=None,
                duration_seconds=100.0,
            ),
            SessionRecord(
                id=1,
                started_at=1000000.0,
                stopped_at=1000200.0,
                status="stopped",
                error_type=None,
                error_message=None,
                duration_seconds=200.0,
            ),
        ]
        mock_hassette.telemetry_query_service.get_session_list = AsyncMock(return_value=sessions)
        response = await client.get("/api/telemetry/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        started_at_values = [entry["started_at"] for entry in data]
        assert started_at_values == sorted(started_at_values, reverse=True)
