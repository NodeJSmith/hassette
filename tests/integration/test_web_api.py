"""Integration tests for the FastAPI web API using httpx AsyncClient."""

import asyncio
import logging
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.data_sync_service import DataSyncService
from hassette.logging_ import LogCaptureHandler
from hassette.web.app import create_fastapi_app
from hassette.web.routes.config import _CONFIG_SAFE_FIELDS

try:
    from httpx import ASGITransport, AsyncClient

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


pytestmark = pytest.mark.skipif(not HAS_HTTPX, reason="httpx not installed")


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance for the FastAPI app."""
    hassette = MagicMock()
    hassette.config.run_web_api = True
    hassette.config.web_api_cors_origins = ("http://localhost:3000",)
    hassette.config.web_api_event_buffer_size = 100
    hassette.config.web_api_log_level = "INFO"
    hassette.config.dev_mode = True
    hassette.config.allow_reload_in_prod = False

    # Wire public properties to private mocks
    hassette.state_proxy = hassette._state_proxy
    hassette.websocket_service = hassette._websocket_service
    hassette.app_handler = hassette._app_handler
    hassette.bus_service = hassette._bus_service
    hassette.scheduler_service = hassette._scheduler_service
    hassette.data_sync_service = hassette._data_sync_service

    # Mock state proxy
    hassette._state_proxy.states = {
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
    }
    hassette._state_proxy.get_state.side_effect = lambda eid: hassette._state_proxy.states.get(eid)
    hassette._state_proxy.get_domain_states.return_value = {
        "light.kitchen": hassette._state_proxy.states["light.kitchen"]
    }
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
    hassette._app_handler.start_app = AsyncMock()
    hassette._app_handler.stop_app = AsyncMock()
    hassette._app_handler.reload_app = AsyncMock()

    # Mock scheduler
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])
    hassette._scheduler_service.get_execution_history.return_value = []

    # Mock bus service
    hassette._bus_service.get_all_listener_metrics.return_value = []
    hassette._bus_service.get_listener_metrics_by_owner.return_value = []

    # Mock config for /api/config endpoint
    hassette.config.model_dump.return_value = {"dev_mode": True, "web_api_port": 8126}

    # Mock children for system status
    hassette.children = []

    return hassette


@pytest.fixture
def data_sync_service(mock_hassette):
    """Create a real DataSyncService with mocked Hassette."""
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
def app(mock_hassette, data_sync_service):  # noqa: ARG001
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)


@pytest.fixture
async def client(app):
    """Create an httpx AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoints:
    async def test_healthz_ok(self, client: "AsyncClient") -> None:
        response = await client.get("/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["ws"] == "connected"

    async def test_healthz_degraded(self, client: "AsyncClient", mock_hassette) -> None:
        from hassette.types.enums import ResourceStatus

        mock_hassette._websocket_service.status = ResourceStatus.STOPPED
        response = await client.get("/api/healthz")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"

    async def test_health_status(self, client: "AsyncClient") -> None:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "entity_count" in data
        assert "app_count" in data


class TestEntityEndpoints:
    async def test_get_all_entities(self, client: "AsyncClient") -> None:
        response = await client.get("/api/entities")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["entities"]) == 2

    async def test_get_entity_found(self, client: "AsyncClient") -> None:
        response = await client.get("/api/entities/light.kitchen")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_id"] == "light.kitchen"
        assert data["state"] == "on"

    async def test_get_entity_not_found(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette._state_proxy.get_state.side_effect = lambda _eid: None
        response = await client.get("/api/entities/nonexistent.entity")
        # Restore for other tests
        mock_hassette._state_proxy.get_state.side_effect = lambda _eid: mock_hassette._state_proxy.states.get(_eid)
        assert response.status_code == 404

    async def test_get_domain_entities(self, client: "AsyncClient") -> None:
        response = await client.get("/api/entities/domain/light")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1


class TestAppEndpoints:
    async def test_get_apps(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["running"] == 1

    async def test_get_app_found(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/my_app")
        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"

    async def test_get_app_not_found(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/nonexistent")
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

    async def test_app_management_forbidden_in_prod(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_reload_in_prod = False
        response = await client.post("/api/apps/my_app/start")
        assert response.status_code == 403
        # Restore
        mock_hassette.config.dev_mode = True


class TestEventsEndpoint:
    async def test_get_recent_events_empty(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_recent_events_with_data(self, client: "AsyncClient", data_sync_service: DataSyncService) -> None:
        data_sync_service._event_buffer.append({"type": "test", "timestamp": 1234567890.0})
        response = await client.get("/api/events/recent")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestSchedulerEndpoints:
    async def test_get_scheduled_jobs(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_job_history(self, client: "AsyncClient") -> None:
        response = await client.get("/api/scheduler/history")
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
        response = await client.get("/api/bus/listeners")
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_bus_listeners_with_data(self, client: "AsyncClient", mock_hassette) -> None:
        from hassette.bus.metrics import ListenerMetrics

        m = ListenerMetrics(listener_id=1, owner="my_app", topic="hass.event.state_changed", handler_name="on_light")
        m.record_success(10.0)
        mock_hassette._bus_service.get_all_listener_metrics.return_value = [m]

        response = await client.get("/api/bus/listeners")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["listener_id"] == 1
        assert data[0]["owner"] == "my_app"
        assert data[0]["total_invocations"] == 1
        assert data[0]["successful"] == 1

        # Restore
        mock_hassette._bus_service.get_all_listener_metrics.return_value = []

    async def test_get_bus_listeners_filter_by_owner(self, client: "AsyncClient", mock_hassette) -> None:
        from hassette.bus.metrics import ListenerMetrics

        m = ListenerMetrics(listener_id=2, owner="other_app", topic="t", handler_name="h")
        mock_hassette._bus_service.get_listener_metrics_by_owner.return_value = [m]

        response = await client.get("/api/bus/listeners?owner=other_app")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["owner"] == "other_app"
        mock_hassette._bus_service.get_listener_metrics_by_owner.assert_called_with("other_app")

        # Restore
        mock_hassette._bus_service.get_listener_metrics_by_owner.return_value = []

    async def test_get_bus_metrics_summary_empty(self, client: "AsyncClient") -> None:
        response = await client.get("/api/bus/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_listeners"] == 0
        assert data["total_invocations"] == 0
        assert data["total_successful"] == 0
        assert data["total_failed"] == 0
        assert data["total_di_failures"] == 0
        assert data["total_cancelled"] == 0

    async def test_get_bus_metrics_summary_with_data(self, client: "AsyncClient", mock_hassette) -> None:
        from hassette.bus.metrics import ListenerMetrics

        m1 = ListenerMetrics(listener_id=1, owner="app1", topic="t1", handler_name="h1")
        m1.record_success(10.0)
        m1.record_error(5.0, "err", "ValueError")

        m2 = ListenerMetrics(listener_id=2, owner="app2", topic="t2", handler_name="h2")
        m2.record_success(20.0)
        m2.record_di_failure(3.0, "bad", "DependencyInjectionError")

        mock_hassette._bus_service.get_all_listener_metrics.return_value = [m1, m2]

        response = await client.get("/api/bus/metrics")
        assert response.status_code == 200
        data = response.json()
        assert data["total_listeners"] == 2
        assert data["total_invocations"] == 4
        assert data["total_successful"] == 2
        assert data["total_failed"] == 1
        assert data["total_di_failures"] == 1
        assert data["total_cancelled"] == 0

        # Restore
        mock_hassette._bus_service.get_all_listener_metrics.return_value = []


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
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 6

    async def test_get_logs_filter_by_level(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?level=ERROR")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["level"] == "ERROR"

    async def test_get_logs_filter_by_warning_includes_error(
        self, client: "AsyncClient", log_handler: LogCaptureHandler
    ) -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?level=WARNING")
        assert response.status_code == 200
        data = response.json()
        levels = {entry["level"] for entry in data}
        assert levels == {"WARNING", "ERROR"}

    async def test_get_logs_filter_by_app_key(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?app_key=my_app")
        assert response.status_code == 200
        data = response.json()
        assert all(entry["app_key"] == "my_app" for entry in data)
        assert len(data) == 3

    async def test_get_logs_limit(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_get_logs_combined_filters(self, client: "AsyncClient", log_handler: LogCaptureHandler) -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            response = await client.get("/api/logs/recent?app_key=my_app&level=WARNING")
        assert response.status_code == 200
        data = response.json()
        assert all(entry["app_key"] == "my_app" for entry in data)
        levels = {entry["level"] for entry in data}
        assert levels <= {"WARNING", "ERROR", "CRITICAL"}
        assert len(data) == 2

    async def test_get_logs_empty_when_no_handler(self, client: "AsyncClient") -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=None):
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
