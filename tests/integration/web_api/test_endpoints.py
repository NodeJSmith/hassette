"""Integration tests for core web API endpoints."""

import logging
import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry_models import ListenerSummary

if TYPE_CHECKING:
    from httpx import AsyncClient

from .conftest import LOGS_REPO, make_log_record


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

    async def test_get_recent_events_returns_event_entry_schema(
        self, client: "AsyncClient", runtime_query_service: RuntimeQueryService
    ) -> None:
        """Response items conform to EventEntry schema: type, timestamp, data fields present."""
        runtime_query_service._event_buffer.append(
            {"type": "connectivity", "data": {"connected": True}, "timestamp": 9999999.0}
        )
        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        entry = data[0]
        # EventEntry required fields must be present
        assert entry["type"] == "connectivity"
        assert entry["timestamp"] == 9999999.0
        # data field must be present (dict, not absent)
        assert "data" in entry
        assert entry["data"] == {"connected": True}
        # entity_id is optional, defaults to None
        assert entry.get("entity_id") is None


class TestSchedulerEndpoints:
    async def test_scheduler_jobs_endpoint_exists(self, client: "AsyncClient") -> None:
        """GET /api/scheduler/jobs returns 200."""
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
        # timed_out is tracked separately from failed (not aggregated into it)
        assert "timed_out" in entry
        assert entry["timed_out"] == 0
        assert "listener_kind" in entry
        # Verify key fields are correct
        assert entry["listener_id"] == 1
        assert entry["app_key"] == "test_app"
        assert entry["topic"] == "state_changed.light.kitchen"
        assert entry["total_invocations"] == 5


class TestLogsEndpoints:
    @pytest.fixture
    def sample_records(self) -> list[dict]:
        """Six log records matching the old buffer fixture, now as DB dicts."""
        return [
            make_log_record(1, "INFO", "Core started", app_key=None),
            make_log_record(2, "INFO", "MyApp initialized", app_key="my_app"),
            make_log_record(3, "WARNING", "Light unresponsive", app_key="my_app"),
            make_log_record(4, "DEBUG", "Heartbeat sent", app_key=None),
            make_log_record(5, "ERROR", "Service call failed", app_key="my_app"),
            make_log_record(6, "INFO", "OtherApp ready", app_key="other_app"),
        ]

    @patch(f"{LOGS_REPO}.get_log_records", new_callable=AsyncMock)
    async def test_get_logs_recent_returns_list(
        self, mock_get: AsyncMock, client: "AsyncClient", sample_records: list[dict]
    ) -> None:
        mock_get.return_value = sample_records
        response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6

    @patch(f"{LOGS_REPO}.get_log_records", new_callable=AsyncMock)
    async def test_get_logs_recent_new_fields_present(
        self, mock_get: AsyncMock, client: "AsyncClient", sample_records: list[dict]
    ) -> None:
        """New fields (execution_id, instance_name, instance_index, source_tier) are in the response."""
        mock_get.return_value = sample_records[:1]
        response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        entry = response.json()[0]
        assert "execution_id" in entry
        assert "instance_name" in entry
        assert "instance_index" in entry
        assert "source_tier" in entry

    @patch(f"{LOGS_REPO}.get_log_records", new_callable=AsyncMock)
    async def test_get_logs_recent_returns_503_on_db_error(self, mock_get: AsyncMock, client: "AsyncClient") -> None:
        mock_get.side_effect = sqlite3.Error("db error")
        response = await client.get("/api/logs/recent")
        assert response.status_code == 503
        assert response.json() == []

    @patch(f"{LOGS_REPO}.get_log_records", new_callable=AsyncMock)
    async def test_get_logs_recent_accepts_execution_id_param(self, mock_get: AsyncMock, client: "AsyncClient") -> None:
        mock_get.return_value = []
        response = await client.get("/api/logs/recent?execution_id=abc-123")
        assert response.status_code == 200

    @patch(f"{LOGS_REPO}.get_log_records", new_callable=AsyncMock)
    async def test_get_logs_recent_accepts_source_tier_param(self, mock_get: AsyncMock, client: "AsyncClient") -> None:
        mock_get.return_value = []
        response = await client.get("/api/logs/recent?source_tier=app")
        assert response.status_code == 200

    @patch(f"{LOGS_REPO}.get_log_records_by_execution", new_callable=AsyncMock)
    async def test_get_logs_by_execution_returns_records(self, mock_get: AsyncMock, client: "AsyncClient") -> None:
        records = [make_log_record(1, "INFO", "started", execution_id="exec-abc")]
        mock_get.return_value = (records, False)
        response = await client.get("/api/logs/by-execution/exec-abc")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is False
        assert data["retention_expired"] is False
        assert len(data["records"]) == 1
        assert data["records"][0]["execution_id"] == "exec-abc"

    @patch(f"{LOGS_REPO}.get_log_records_by_execution", new_callable=AsyncMock)
    async def test_get_logs_by_execution_truncated(self, mock_get: AsyncMock, client: "AsyncClient") -> None:
        records = [make_log_record(i, execution_id="exec-xyz") for i in range(500)]
        mock_get.return_value = (records, True)
        response = await client.get("/api/logs/by-execution/exec-xyz")
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is True
        assert len(data["records"]) == 500

    @patch(f"{LOGS_REPO}.check_execution_predates_retention_cutoff", new_callable=AsyncMock)
    @patch(f"{LOGS_REPO}.get_log_records_by_execution", new_callable=AsyncMock)
    async def test_get_logs_by_execution_retention_expired(
        self, mock_get: AsyncMock, mock_cutoff: AsyncMock, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When records=[] and execution is old, retention_expired=True."""
        mock_get.return_value = ([], False)
        mock_cutoff.return_value = True
        mock_hassette.config.logging.log_retention_days = 3
        response = await client.get("/api/logs/by-execution/old-exec")
        assert response.status_code == 200
        data = response.json()
        assert data["retention_expired"] is True
        assert data["records"] == []

    @patch(f"{LOGS_REPO}.check_execution_predates_retention_cutoff", new_callable=AsyncMock)
    @patch(f"{LOGS_REPO}.get_log_records_by_execution", new_callable=AsyncMock)
    async def test_get_logs_by_execution_empty_no_retention(
        self, mock_get: AsyncMock, mock_cutoff: AsyncMock, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When records=[] and execution is not old, retention_expired=False."""
        mock_get.return_value = ([], False)
        mock_cutoff.return_value = False
        mock_hassette.config.logging.log_retention_days = 3
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
    async def test_response_has_nested_groups(self, client: "AsyncClient", mock_hassette) -> None:
        """Response is organized into nested config groups."""
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "web_api" in data
        assert "logging" in data
        assert "lifecycle" in data
        assert "apps" in data
        assert "scheduler" in data
        assert "file_watcher" in data

    async def test_token_not_in_response(self, client: "AsyncClient", mock_hassette) -> None:
        """Verify token is never returned in the config response."""
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "token" not in data

    async def test_dev_mode_present_at_root(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.config.dev_mode = True
        response = await client.get("/api/config")
        data = response.json()
        assert "dev_mode" in data
        assert data["dev_mode"] is True

    async def test_dir_fields_present_as_strings(self, client: "AsyncClient", mock_hassette) -> None:
        """data_dir and config_dir are present at root; apps.directory is under apps group."""
        mock_hassette.config.apps.directory = "/srv/hassette/apps"
        mock_hassette.config.data_dir = "/srv/hassette/data"
        mock_hassette.config.config_dir = "/srv/hassette/config"
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["apps"]["directory"] == "/srv/hassette/apps"
        assert data["data_dir"] == "/srv/hassette/data"
        assert data["config_dir"] == "/srv/hassette/config"

    async def test_web_api_fields_nested(self, client: "AsyncClient", mock_hassette) -> None:
        """web_api group contains host, port, and other API settings."""
        mock_hassette.config.web_api.host = "127.0.0.1"
        mock_hassette.config.web_api.port = 9000
        response = await client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["web_api"]["host"] == "127.0.0.1"
        assert data["web_api"]["port"] == 9000


class TestOpenApiDocs:
    async def test_openapi_json(self, client: "AsyncClient") -> None:
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Hassette Web API"

    async def test_events_recent_has_response_schema(self, client: "AsyncClient") -> None:
        """GET /api/events/recent has EventEntry declared as response_model in OpenAPI."""
        response = await client.get("/api/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})
        assert "/api/events/recent" in paths, f"events route missing; got: {list(paths)}"
        get_op = paths["/api/events/recent"].get("get", {})
        responses = get_op.get("responses", {})
        assert "200" in responses, "events/recent must have a 200 response schema"
        schema = responses["200"].get("content", {}).get("application/json", {}).get("schema", {})
        assert schema is not None, "events/recent 200 response must have a JSON schema"
        # When response_model=list[EventEntry] is set, FastAPI generates a $ref to EventEntry
        # The schema will be an array whose items reference EventEntry
        schema_str = str(schema)
        assert "EventEntry" in schema_str, f"events/recent schema must reference EventEntry model; got: {schema_str}"

    async def test_services_has_response_schema(self, client: "AsyncClient") -> None:
        """GET /api/services has a declared response schema in OpenAPI (response_model set)."""
        response = await client.get("/api/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})
        assert "/api/services" in paths
        get_op = paths["/api/services"].get("get", {})
        responses = get_op.get("responses", {})
        assert "200" in responses
        schema_ref = responses["200"].get("content", {}).get("application/json", {}).get("schema")
        assert schema_ref is not None, "services 200 response must have a JSON schema"

    async def test_instance_index_has_description_on_telemetry_health(self, client: "AsyncClient") -> None:
        """instance_index parameter on telemetry app health route has a description."""
        response = await client.get("/api/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})
        # Find the app health route
        health_path = "/api/telemetry/app/{app_key}/health"
        assert health_path in paths, f"health route missing; got {list(paths)}"
        params = paths[health_path]["get"].get("parameters", [])
        instance_params = [p for p in params if p.get("name") == "instance_index"]
        assert instance_params, "instance_index parameter must be present on health route"
        assert instance_params[0].get("description"), "instance_index must have a non-empty description"

    async def test_instance_index_has_description_on_bus_listeners(self, client: "AsyncClient") -> None:
        """instance_index parameter on bus listeners route has a description."""
        response = await client.get("/api/openapi.json")
        spec = response.json()
        paths = spec.get("paths", {})
        bus_path = "/api/bus/listeners"
        assert bus_path in paths
        params = paths[bus_path]["get"].get("parameters", [])
        instance_params = [p for p in params if p.get("name") == "instance_index"]
        assert instance_params, "instance_index parameter must be present on bus/listeners route"
        assert instance_params[0].get("description"), "instance_index must have a non-empty description"
