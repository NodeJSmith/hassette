"""Integration tests for core web API endpoints."""

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.exceptions import AppBootstrapNotReleasedError, TelemetryUnavailableError
from hassette.schemas.listener_models import ListenerSummary
from hassette.test_utils.web_manifest_helpers import make_manifest_db_row
from hassette.web.config_view import MASK_SENTINEL

from .conftest import make_log_record, set_app_status_snapshot, set_websocket_state

if TYPE_CHECKING:
    from httpx2 import AsyncClient

# Route paths hit by multiple tests below — single source of truth so a route rename only
# needs to change here.
HEALTH_PATH = "/api/health"
HEALTH_READY_PATH = "/api/health/ready"
APP_START_PATH = "/api/apps/my_app/start"
APP_STOP_PATH = "/api/apps/my_app/stop"
APP_RELOAD_PATH = "/api/apps/my_app/reload"
APP_MANIFEST_PATH = "/api/apps/my_app/manifest"
APP_MANIFESTS_PATH = "/api/apps/manifests"
BUS_LISTENERS_PATH = "/api/bus/listeners"
LOGS_RECENT_PATH = "/api/logs/recent"
LOGS_LEVEL_PATH = "/api/logs/level"
CONFIG_PATH = "/api/config"
OPENAPI_PATH = "/api/openapi.json"


class TestHealthEndpoints:
    async def test_health_returns_200_when_ok(self, client: "AsyncClient") -> None:
        """GET /api/health returns 200 with status 'ok' when WebSocket is connected."""
        response = await client.get(HEALTH_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["websocket_connected"] is True
        assert "entity_count" in data
        assert "app_count" in data

    async def test_health_returns_200_when_degraded(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 200 with status 'degraded' when WebSocket is not connected."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=True)
        response = await client.get(HEALTH_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["websocket_connected"] is False

    async def test_health_returns_200_when_starting(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 200 (not 503) with status 'starting' during startup."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        response = await client.get(HEALTH_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "starting"

    async def test_health_live_returns_200_regardless_of_ws_state(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health/live returns 200 even when WS is disconnected and never connected."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        response = await client.get("/api/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "live"

    async def test_health_ready_returns_200_when_ok(self, client: "AsyncClient") -> None:
        """GET /api/health/ready returns 200 when status is 'ok'."""
        response = await client.get(HEALTH_READY_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["status"] == "ok"

    async def test_health_ready_returns_503_when_degraded(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health/ready returns 503 when status is 'degraded'."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=True)
        response = await client.get(HEALTH_READY_PATH)
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] is False
        assert data["status"] == "degraded"

    async def test_health_ready_returns_503_when_starting(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health/ready returns 503 when status is 'starting'."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        response = await client.get(HEALTH_READY_PATH)
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] is False
        assert data["status"] == "starting"

    async def test_healthz_returns_404(self, client: "AsyncClient") -> None:
        """GET /api/healthz returns 404 after endpoint removal."""
        response = await client.get("/api/healthz")
        assert response.status_code == 404

    async def test_health_reports_zero_apps_and_starting_before_bootstrap(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """The dashboard serves with app_count=0 while apps have not bootstrapped.

        RuntimeQueryService no longer depends on AppHandler, so this must not require any
        AppHandler readiness — only a cold WebSocket (never connected) and an empty live snapshot.
        """
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        set_app_status_snapshot(mock_hassette, running=[], failed=[])
        response = await client.get(HEALTH_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "starting"
        assert data["app_count"] == 0


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
        response = await client.post(APP_START_PATH)
        assert response.status_code == 202
        data = response.json()
        assert data["action"] == "start"

    async def test_start_app_returns_retryable_conflict_before_release(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.start_app = AsyncMock(side_effect=AppBootstrapNotReleasedError("not released"))

        response = await client.post(APP_START_PATH)

        assert response.status_code == 409

    async def test_stop_app(self, client: "AsyncClient") -> None:
        response = await client.post(APP_STOP_PATH)
        assert response.status_code == 202
        data = response.json()
        assert data["action"] == "stop"

    async def test_reload_app(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Reload returns 202 and forces a fresh re-import from disk.

        The force_reload=True assertion guards #1005: without it the endpoint reused the
        cached (failed) class, so a fix on disk never took effect.
        """
        response = await client.post(APP_RELOAD_PATH)
        assert response.status_code == 202
        data = response.json()
        assert data["action"] == "reload"
        mock_hassette.app_handler.reload_app.assert_awaited_once_with("my_app", force_reload=True)

    async def test_reload_app_returns_retryable_conflict_before_release(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.reload_app = AsyncMock(side_effect=AppBootstrapNotReleasedError("not released"))

        response = await client.post(APP_RELOAD_PATH)

        assert response.status_code == 409

    async def test_app_management_works_without_dev_mode(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_reload_in_prod = False
        assert (await client.post(APP_START_PATH)).status_code == 202
        assert (await client.post(APP_STOP_PATH)).status_code == 202
        assert (await client.post(APP_RELOAD_PATH)).status_code == 202


class TestAppManifestEndpoint:
    async def test_get_manifest_returns_single_manifest(self, client: "AsyncClient", mock_hassette) -> None:
        """A DB-only app (no matching in-memory manifest) returns 200, not 404."""
        mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(
            return_value=make_manifest_db_row(app_key="my_app", display_name="My App")
        )
        mock_hassette.telemetry_query_service.get_recent_invocations_1h_all_apps.return_value = {"my_app": 5}

        response = await client.get(APP_MANIFEST_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"
        assert data["display_name"] == "My App"
        # No matching in-memory manifest on the stub registry -> stopped, not in current config.
        assert data["status"] == "stopped"
        assert data["in_current_config"] is False
        assert data["recent_invocations_1h"] == 5

    async def test_get_manifest_returns_404_for_unknown_app(self, client: "AsyncClient", mock_hassette) -> None:
        """A genuinely unknown app_key (no DB row at all) still 404s."""
        mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(return_value=None)

        response = await client.get("/api/apps/unknown_app/manifest")
        assert response.status_code == 404

    async def test_get_manifest_returns_400_for_invalid_key(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/!!invalid/manifest")
        assert response.status_code == 400

    async def test_get_manifest_degrades_gracefully_on_telemetry_failure(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """A failed Category-C enrichment query (recent_invocations_1h) still returns 200."""
        mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(
            return_value=make_manifest_db_row(app_key="my_app")
        )
        mock_hassette.telemetry_query_service.get_recent_invocations_1h_all_apps = AsyncMock(
            side_effect=TelemetryUnavailableError("db down")
        )

        response = await client.get(APP_MANIFEST_PATH)
        assert response.status_code == 200
        assert response.json()["recent_invocations_1h"] == 0

    async def test_get_manifest_returns_503_when_db_unavailable(self, client: "AsyncClient", mock_hassette) -> None:
        """A DB failure on the spine query itself returns 503, not 404."""
        mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(
            side_effect=TelemetryUnavailableError("db down")
        )

        response = await client.get(APP_MANIFEST_PATH)
        assert response.status_code == 503


class TestAppManifestListEndpoint:
    async def test_get_manifests_includes_db_only_apps(self, client: "AsyncClient", mock_hassette) -> None:
        """A DB-only app (no matching in-memory manifest) appears in the manifests list."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[make_manifest_db_row(app_key="orphan_app", display_name="Orphan App")]
        )

        response = await client.get(APP_MANIFESTS_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["status_counts"]["stopped"] == 1
        app_keys = {m["app_key"] for m in data["manifests"]}
        assert "orphan_app" in app_keys
        orphan = next(m for m in data["manifests"] if m["app_key"] == "orphan_app")
        assert orphan["display_name"] == "Orphan App"
        assert orphan["status"] == "stopped"
        assert orphan["in_current_config"] is False

    async def test_get_manifests_returns_503_on_spine_failure(self, client: "AsyncClient", mock_hassette) -> None:
        """A storage error on the DB spine query yields 503."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            side_effect=TelemetryUnavailableError("db down")
        )

        response = await client.get(APP_MANIFESTS_PATH)
        assert response.status_code == 503
        assert response.json()["manifests"] == []


class TestSchedulerEndpoints:
    async def test_scheduler_jobs_endpoint_exists(self, client: "AsyncClient") -> None:
        """GET /api/scheduler/jobs returns 200."""
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        assert response.json() == []


class TestConfigEndpoint:
    async def test_get_config(self, client: "AsyncClient") -> None:
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        assert "config_schema" in data
        assert "config_values" in data


class TestBusEndpoints:
    async def test_get_bus_listeners_empty(self, client: "AsyncClient") -> None:
        # Returns empty when no app_key is provided (TelemetryDep stubs return [])
        response = await client.get(BUS_LISTENERS_PATH)
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_bus_listeners_with_app_key_returns_empty_stub(self, client: "AsyncClient") -> None:
        # TelemetryQueryService stubs return [] for all app_key queries
        response = await client.get(f"{BUS_LISTENERS_PATH}?app_key=my_app")
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

        response = await client.get(f"{BUS_LISTENERS_PATH}?app_key=test_app")
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

    async def test_get_logs_recent_returns_list(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=sample_records)
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6

    async def test_get_logs_recent_preserves_newest_first_order(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        records = [
            make_log_record(4, "INFO", "newest", app_key="my_app"),
            make_log_record(3, "INFO", "same-timestamp-higher-seq", app_key="my_app"),
            make_log_record(2, "INFO", "same-timestamp-lower-seq", app_key="my_app"),
            make_log_record(1, "INFO", "oldest", app_key="my_app"),
        ]
        records[1]["timestamp"] = 2.0
        records[2]["timestamp"] = 2.0
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=records)

        response = await client.get(LOGS_RECENT_PATH)

        assert response.status_code == 200
        assert [entry["message"] for entry in response.json()] == [
            "newest",
            "same-timestamp-higher-seq",
            "same-timestamp-lower-seq",
            "oldest",
        ]

    async def test_get_logs_recent_new_fields_present(
        self, client: "AsyncClient", mock_hassette: MagicMock, sample_records: list[dict]
    ) -> None:
        """New fields (execution_id, instance_name, instance_index, source_tier) are in the response."""
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=sample_records[:1])
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 200
        entry = response.json()[0]
        assert "execution_id" in entry
        assert "instance_name" in entry
        assert "instance_index" in entry
        assert "source_tier" in entry

    async def test_get_logs_recent_returns_503_on_db_error(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(
            side_effect=TelemetryUnavailableError("db error")
        )
        response = await client.get(LOGS_RECENT_PATH)
        assert response.status_code == 503
        assert response.json() == []

    async def test_get_logs_recent_accepts_execution_id_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=[])
        response = await client.get(f"{LOGS_RECENT_PATH}?execution_id=abc-123")
        assert response.status_code == 200

    async def test_get_logs_recent_accepts_source_tier_param(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(return_value=[])
        response = await client.get(f"{LOGS_RECENT_PATH}?source_tier=app")
        assert response.status_code == 200

    async def test_put_log_level_valid(self, client: "AsyncClient") -> None:
        response = await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.test", "level": "DEBUG"})
        assert response.status_code == 200
        data = response.json()
        assert data["logger"] == "hassette.test"
        assert data["effective_level"] == "DEBUG"

    async def test_put_log_level_invalid_level(self, client: "AsyncClient") -> None:
        response = await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.test", "level": "VERBOSE"})
        assert response.status_code == 422

    async def test_put_log_level_changes_take_effect(self, client: "AsyncClient") -> None:
        """Setting DEBUG then INFO changes the effective level each time."""
        await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.rqs.test.lvl", "level": "DEBUG"})
        assert logging.getLogger("hassette.rqs.test.lvl").level == logging.DEBUG

        r2 = await client.put(LOGS_LEVEL_PATH, json={"logger": "hassette.rqs.test.lvl", "level": "INFO"})
        assert r2.status_code == 200
        assert logging.getLogger("hassette.rqs.test.lvl").level == logging.INFO


class TestConfigEndpointExpanded:
    async def test_response_has_nested_groups(self, client: "AsyncClient", mock_hassette) -> None:
        """Response envelope contains standard config groups in config_values, including previously-omitted ones."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        config_values = data["config_values"]
        assert "web_api" in config_values
        assert "logging" in config_values
        assert "lifecycle" in config_values
        assert "apps" in config_values
        assert "scheduler" in config_values
        assert "file_watcher" in config_values
        # Groups that the old endpoint omitted are now present
        assert "database" in config_values
        assert "websocket" in config_values
        assert "blocking_io" in config_values

    async def test_token_not_in_response(self, client: "AsyncClient", mock_hassette) -> None:
        """Token is present in config_values as None or masked; plaintext is never returned."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        config_values = data["config_values"]
        # Token key is present in config_values (not omitted)
        assert "token" in config_values
        # Value is None (not set) or the mask sentinel — never a plaintext secret
        token_val = config_values["token"]
        assert token_val is None or token_val == MASK_SENTINEL
        # Plaintext token never appears anywhere in the response body
        assert "test-token" not in response.text

    async def test_set_token_is_masked_not_plaintext(self, client: "AsyncClient", mock_hassette) -> None:
        """A token with a value is returned as the mask sentinel — proves the full endpoint
        masking flow (the schema marks token secret, the view builder replaces the value).
        """
        secret = "super-secret-plaintext-xyz"
        mock_hassette.config.model_dump.return_value["token"] = secret
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["config_values"]["token"] == MASK_SENTINEL
        assert secret not in response.text

    async def test_dev_mode_present_at_root(self, client: "AsyncClient", mock_hassette) -> None:
        """dev_mode is present in config_values."""
        response = await client.get(CONFIG_PATH)
        data = response.json()
        assert "dev_mode" in data["config_values"]
        assert isinstance(data["config_values"]["dev_mode"], bool)

    async def test_dir_fields_present_as_strings(self, client: "AsyncClient", mock_hassette) -> None:
        """data_dir and config_dir are present in config_values; apps.directory is under the apps group."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        config_values = data["config_values"]
        assert isinstance(config_values["apps"]["directory"], str)
        assert isinstance(config_values["data_dir"], str)
        assert isinstance(config_values["config_dir"], str)

    async def test_web_api_fields_nested(self, client: "AsyncClient", mock_hassette) -> None:
        """web_api group in config_values contains host and port fields."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        web_api = data["config_values"]["web_api"]
        assert "host" in web_api
        assert "port" in web_api


class TestOpenApiDocs:
    async def test_openapi_json(self, client: "AsyncClient") -> None:
        response = await client.get(OPENAPI_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Hassette Web API"

    async def test_instance_index_has_description_on_telemetry_health(self, client: "AsyncClient") -> None:
        """instance_index parameter on telemetry app health route has a description."""
        response = await client.get(OPENAPI_PATH)
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
        response = await client.get(OPENAPI_PATH)
        spec = response.json()
        paths = spec.get("paths", {})
        assert BUS_LISTENERS_PATH in paths
        params = paths[BUS_LISTENERS_PATH]["get"].get("parameters", [])
        instance_params = [p for p in params if p.get("name") == "instance_index"]
        assert instance_params, "instance_index parameter must be present on bus/listeners route"
        assert instance_params[0].get("description"), "instance_index must have a non-empty description"
