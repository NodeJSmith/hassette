"""Integration tests for the FastAPI web API using httpx AsyncClient."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry_models import HandlerErrorRecord, JobErrorRecord, ListenerSummary

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
    async def test_get_scheduled_jobs(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        assert response.json() == []


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
        from hassette.core.telemetry_models import HandlerInvocation

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
        from hassette.core.telemetry_models import JobExecution

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

    async def test_dashboard_kpis_valueerror_returns_fallback(
        self, client: "AsyncClient", mock_hassette, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ValueError triggers fallback and logs at WARNING."""
        mock_hassette.telemetry_query_service.get_global_summary = AsyncMock(
            side_effect=ValueError("Connection is closed")
        )
        with caplog.at_level(logging.WARNING, logger="hassette.web.routes.telemetry"):
            response = await client.get("/api/telemetry/dashboard/kpis")
        assert response.status_code == 200
        data = response.json()
        assert data["total_handlers"] == 0
        assert data["error_rate"] == 0.0
        # ValueError must be logged at WARNING, not silently swallowed
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        # exc_info captures the ValueError
        assert any(r.exc_info is not None and r.exc_info[0] is ValueError for r in warning_records)

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
        from hassette.core.telemetry_models import SessionRecord

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

    async def test_dashboard_errors_defaults_to_app_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Call without source_tier — service receives source_tier='app'."""
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        assert call_kwargs["source_tier"] == "app"

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


class TestDashboardErrorsSinceTs:
    """Verify since_ts defaults to last 24h instead of 0."""

    async def test_dashboard_errors_default_since_ts_is_recent(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Without explicit since_ts, get_recent_errors called with ts > now-86401."""
        import time

        before = time.time()
        response = await client.get("/api/telemetry/dashboard/errors")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_recent_errors.call_args.kwargs
        since = call_kwargs["since_ts"]
        after = time.time()
        # since_ts must be approximately now - 86400
        assert since >= before - 86401
        assert since <= after - 86399


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
