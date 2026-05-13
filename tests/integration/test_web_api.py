"""Integration tests for the FastAPI web API using httpx AsyncClient."""

import logging
import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry_models import (
    HandlerInvocation,
    JobExecution,
    ListenerSummary,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
from hassette.core.app_registry import AppInstanceInfo, AppStatusSnapshot
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
        """GET /api/health returns 503 with status 'degraded' when WebSocket is not ready."""
        mock_hassette._websocket_service.is_ready.return_value = False
        response = await client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["websocket_connected"] is False

    async def test_health_returns_503_when_starting(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 503 with status 'starting' during startup."""
        mock_hassette._websocket_service.is_ready.return_value = False
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
    async def test_scheduler_jobs_endpoint_exists(self, client: "AsyncClient") -> None:
        """GET /api/scheduler/jobs returns 200 — global jobs endpoint restored in spec 050 T03."""
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
        # timed_out field must be present (WP03)
        assert "timed_out" in entry
        assert entry["timed_out"] == 0
        # ListenerMetricsResponse-only fields absent (that class is deleted)
        # Verify key fields are correct
        assert entry["listener_id"] == 1
        assert entry["app_key"] == "test_app"
        assert entry["topic"] == "state_changed.light.kitchen"
        assert entry["total_invocations"] == 5


def _make_log_record(
    seq: int,
    level: str = "INFO",
    message: str = "test",
    app_key: str | None = None,
    execution_id: str | None = None,
    source_tier: str | None = "framework",
) -> dict:
    return {
        "seq": seq,
        "timestamp": float(seq),
        "level": level,
        "logger_name": "hassette.test",
        "func_name": "test_func",
        "lineno": 1,
        "message": message,
        "exc_info": None,
        "app_key": app_key,
        "execution_id": execution_id,
        "instance_name": None,
        "instance_index": None,
        "source_tier": source_tier,
    }


def _mock_submit(return_value: object = None, side_effect: object = None) -> AsyncMock:
    """Create an AsyncMock for database_service.submit that closes the passed coroutine."""
    values = list(side_effect) if side_effect is not None else None
    call_count = [0]

    async def _impl(coro: object) -> object:
        import asyncio

        if asyncio.iscoroutine(coro):
            coro.close()
        if values is not None:
            idx = min(call_count[0], len(values) - 1)
            call_count[0] += 1
            result = values[idx]
            if isinstance(result, BaseException):
                raise result
            return result
        return return_value

    mock = AsyncMock(side_effect=_impl)
    return mock


class TestLogsEndpoints:
    @pytest.fixture
    def sample_records(self) -> list[dict]:
        """Six log records matching the old buffer fixture, now as DB dicts."""
        return [
            _make_log_record(1, "INFO", "Core started", app_key=None),
            _make_log_record(2, "INFO", "MyApp initialized", app_key="my_app"),
            _make_log_record(3, "WARNING", "Light unresponsive", app_key="my_app"),
            _make_log_record(4, "DEBUG", "Heartbeat sent", app_key=None),
            _make_log_record(5, "ERROR", "Service call failed", app_key="my_app"),
            _make_log_record(6, "INFO", "OtherApp ready", app_key="other_app"),
        ]

    async def test_get_logs_recent_returns_list(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        mock_hassette._database_service.submit = _mock_submit(return_value=sample_records)
        response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6

    async def test_get_logs_recent_new_fields_present(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        """New fields (execution_id, instance_name, instance_index, source_tier) are in the response."""
        mock_hassette._database_service.submit = _mock_submit(return_value=sample_records[:1])
        response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        entry = response.json()[0]
        assert "execution_id" in entry
        assert "instance_name" in entry
        assert "instance_index" in entry
        assert "source_tier" in entry

    async def test_get_logs_recent_returns_empty_on_db_error(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette._database_service.submit = _mock_submit(side_effect=[sqlite3.Error("db error")])
        response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_logs_recent_accepts_execution_id_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette._database_service.submit = _mock_submit(return_value=[])
        response = await client.get("/api/logs/recent?execution_id=abc-123")
        assert response.status_code == 200

    async def test_get_logs_recent_accepts_source_tier_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette._database_service.submit = _mock_submit(return_value=[])
        response = await client.get("/api/logs/recent?source_tier=app")
        assert response.status_code == 200

    async def test_get_logs_by_execution_returns_records(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        records = [_make_log_record(1, "INFO", "started", execution_id="exec-abc")]
        mock_hassette._database_service.submit = _mock_submit(return_value=(records, False))
        response = await client.get("/api/logs/by-execution/exec-abc")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is False
        assert data["retention_expired"] is False
        assert len(data["records"]) == 1
        assert data["records"][0]["execution_id"] == "exec-abc"

    async def test_get_logs_by_execution_truncated(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        records = [_make_log_record(i, execution_id="exec-xyz") for i in range(500)]
        mock_hassette._database_service.submit = _mock_submit(return_value=(records, True))
        response = await client.get("/api/logs/by-execution/exec-xyz")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is True
        assert len(data["records"]) == 500

    async def test_get_logs_by_execution_retention_expired(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When records=[] and execution is old, retention_expired=True."""
        # First submit call: get_log_records_by_execution → empty + not truncated
        # Second submit call: _check_execution_predates_cutoff → True (expired)
        mock_hassette._database_service.submit = _mock_submit(side_effect=[([], False), True])
        mock_hassette.config.log_retention_days = 3
        response = await client.get("/api/logs/by-execution/old-exec")
        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is True
        assert data["records"] == []

    async def test_get_logs_by_execution_empty_no_retention(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When records=[] and execution is not old, retention_expired=False."""
        mock_hassette._database_service.submit = _mock_submit(side_effect=[([], False), False])
        mock_hassette.config.log_retention_days = 3
        response = await client.get("/api/logs/by-execution/new-exec")
        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is False

    async def test_put_log_level_valid(self, client: "AsyncClient") -> None:
        response = await client.put("/api/logs/level", json={"logger": "hassette.test", "level": "DEBUG"})
        assert response.status_code == 200
        data = response.json()
        assert data["logger"] == "hassette.test"
        assert data["effective_level"] == "DEBUG"

    async def test_put_log_level_invalid_level(self, client: "AsyncClient") -> None:
        response = await client.put("/api/logs/level", json={"logger": "hassette.test", "level": "VERBOSE"})
        assert response.status_code == 422

    async def test_put_log_level_changes_take_effect(self, client: "AsyncClient") -> None:
        """Setting DEBUG then INFO changes the effective level each time."""
        await client.put("/api/logs/level", json={"logger": "hassette.rqs.test.lvl", "level": "DEBUG"})
        assert logging.getLogger("hassette.rqs.test.lvl").level == logging.DEBUG

        r2 = await client.put("/api/logs/level", json={"logger": "hassette.rqs.test.lvl", "level": "INFO"})
        assert r2.status_code == 200
        assert logging.getLogger("hassette.rqs.test.lvl").level == logging.INFO


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
        """All returned keys must be in the allowlist plus the explicit dir fields."""
        mock_hassette.config.model_dump.return_value = {
            "dev_mode": True,
            "web_api_port": 8126,
            "log_level": "INFO",
        }
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        allowed = _CONFIG_SAFE_FIELDS | {"app_dir", "data_dir", "config_dir"}
        assert set(data.keys()) <= allowed

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

    async def test_dir_fields_present_as_strings(self, client: "AsyncClient", mock_hassette) -> None:
        """app_dir, data_dir, config_dir are present and are strings (WP03)."""
        mock_hassette.config.model_dump.return_value = {"dev_mode": False}
        mock_hassette.config.app_dir = "/srv/hassette/apps"
        mock_hassette.config.data_dir = "/srv/hassette/data"
        mock_hassette.config.config_dir = "/srv/hassette/config"
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["app_dir"] == "/srv/hassette/apps"
        assert data["data_dir"] == "/srv/hassette/data"
        assert data["config_dir"] == "/srv/hassette/config"


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
        assert data[0]["handler_summary"] == "light.kitchen"
        assert data[0]["listener_id"] == 1


class TestTelemetryDashboard:
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
        mock_hassette.telemetry_query_service.check_health = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True


class TestTelemetrySinceParam:
    """Verify since query parameter propagates to telemetry service methods."""

    async def test_app_health_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health?since=1700000000.0 forwards since to service."""
        response = await client.get("/api/telemetry/app/my_app/health?since=1700000000.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000000.0)

    async def test_app_health_omitted_since_is_none(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health without since passes None."""
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] is None

    async def test_app_listeners_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/listeners?since=1700000007.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000007.0)

    async def test_app_jobs_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/jobs?since=1700000003.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000003.0)

    async def test_handler_invocations_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/handler/1/invocations?since=1700000005.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_handler_invocations.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000005.0)

    async def test_handler_invocations_omitted_since_is_none(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get("/api/telemetry/handler/1/invocations")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_handler_invocations.call_args.kwargs
        assert call_kwargs["since"] is None

    async def test_job_executions_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/job/1/executions?since=1700000009.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_executions.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000009.0)

    async def test_app_activity_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/activity?since=1700000011.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_recent_activity.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000011.0)

    async def test_app_activity_passes_limit(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/activity?limit=10")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_recent_activity.call_args.kwargs
        assert call_kwargs["limit"] == 10

    async def test_dashboard_app_grid_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/dashboard/app-grid?since=1700000013.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_all_app_summaries.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000013.0)


class TestBusListenersSinceParam:
    """Verify since query parameter propagates through /bus/listeners."""

    async def test_bus_listeners_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/bus/listeners?app_key=my_app&since=1700000020.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000020.0)

    async def test_bus_listeners_omitted_since_is_none(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/bus/listeners?app_key=my_app")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] is None


# ---------------------------------------------------------------------------
# WP06: source_tier parameter, DB_ERRORS guards, status counters
# ---------------------------------------------------------------------------


class TestSourceTierParameter:
    """Verify source_tier query parameter is accepted and forwarded correctly."""

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

    async def test_app_activity_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/activity?source_tier=all passes through."""
        response = await client.get("/api/telemetry/app/my_app/activity?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_recent_activity.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_app_health_invalid_source_tier_returns_422(self, client: "AsyncClient") -> None:
        """Invalid source_tier on /health returns 422."""
        response = await client.get("/api/telemetry/app/my_app/health?source_tier=bad")
        assert response.status_code == 422


class TestDbErrorGuards:
    """Verify DB_ERRORS guards on previously-unguarded endpoints."""

    async def test_app_health_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on app_health returns 503 with zero-value response."""
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
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_app_jobs_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on app_jobs returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/jobs")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_app_activity_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on app_activity returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_app_recent_activity = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/activity")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_handler_invocations_db_error_returns_503(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """sqlite3.Error on handler_invocations returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_handler_invocations = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/handler/1/invocations")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_job_executions_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """sqlite3.Error on job_executions returns 503 with empty list."""
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
        mock_hassette.telemetry_query_service.check_health = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0


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
# Additional coverage for lines 87-88, 114-119, 124-128, 330-332, 347-349.
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

    async def test_nonexistent_app_key_start_returns_404(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key returns 404 when registry has no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        response = await client.post("/api/apps/unknown_app/start")
        assert response.status_code == 404

    async def test_nonexistent_app_key_stop_returns_404(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key returns 404 when registry has no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        response = await client.post("/api/apps/unknown_app/stop")
        assert response.status_code == 404

    async def test_nonexistent_app_key_reload_returns_404(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key returns 404 when registry has no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        response = await client.post("/api/apps/unknown_app/reload")
        assert response.status_code == 404

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
