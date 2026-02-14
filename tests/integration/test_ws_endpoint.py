"""Integration tests for the WebSocket endpoint (ws.py)."""

import asyncio
import json
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from hassette.core.data_sync_service import DataSyncService
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app

try:
    from starlette.testclient import TestClient

    HAS_STARLETTE_TC = True
except ImportError:
    HAS_STARLETTE_TC = False

pytestmark = pytest.mark.skipif(not HAS_STARLETTE_TC, reason="starlette testclient not available")


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette for WebSocket tests."""
    hassette = MagicMock()
    hassette.config.run_web_api = True
    hassette.config.run_web_ui = False
    hassette.config.web_api_cors_origins = ()
    hassette.config.web_api_event_buffer_size = 100
    hassette.config.web_api_log_level = "INFO"
    hassette.config.dev_mode = True
    hassette.config.allow_reload_in_prod = False

    hassette.state_proxy = hassette._state_proxy
    hassette._state_proxy.states = {"light.kitchen": {"entity_id": "light.kitchen", "state": "on"}}
    hassette._state_proxy.is_ready.return_value = True

    hassette.websocket_service = hassette._websocket_service
    hassette._websocket_service.status = ResourceStatus.RUNNING

    hassette.app_handler = hassette._app_handler
    snapshot = SimpleNamespace(
        running=[],
        failed=[],
        total_count=3,
        running_count=2,
        failed_count=1,
        only_app=None,
    )
    hassette._app_handler.get_status_snapshot.return_value = snapshot

    hassette.bus_service = hassette._bus_service
    hassette.scheduler_service = hassette._scheduler_service
    hassette.data_sync_service = hassette._data_sync_service

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
    return create_fastapi_app(mock_hassette)


@pytest.fixture
def client(app):
    return TestClient(app)


def _put_to_all_queues(data_sync: DataSyncService, message: dict) -> None:
    """Put a pre-serialized message into all registered WS client queues.

    The Starlette TestClient runs the ASGI app in a background thread
    with its own event loop, so we schedule the put via that loop.
    """
    safe = json.loads(json.dumps(message, default=str))
    for q in list(data_sync._ws_clients):
        # The queue lives in the async loop managed by the TestClient thread.
        # asyncio.Queue.put_nowait is thread-safe for adding items.
        q.put_nowait(safe)


class TestWebSocketConnection:
    def test_connect_receives_connected_message(self, client: "TestClient") -> None:
        with client.websocket_connect("/api/ws") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["data"]["entity_count"] == 1
            assert msg["data"]["app_count"] == 3

    def test_ping_pong(self, client: "TestClient") -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # consume connected message
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_subscribe_logs_enables_log_forwarding(
        self, client: "TestClient", data_sync_service: DataSyncService
    ) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True}})
            # Give the reader coroutine a moment to process the subscribe
            time.sleep(0.05)
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "INFO", "message": "test"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["message"] == "test"

    def test_log_messages_blocked_when_not_subscribed(
        self, client: "TestClient", data_sync_service: DataSyncService
    ) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            # Log should be filtered (subscribe_logs is False by default)
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "INFO", "message": "should not arrive"}},
            )
            # Non-log message to verify the connection is alive
            _put_to_all_queues(
                data_sync_service,
                {"type": "state_changed", "data": {"entity_id": "light.kitchen"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "state_changed"

    def test_non_log_messages_pass_through_without_subscription(
        self, client: "TestClient", data_sync_service: DataSyncService
    ) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            _put_to_all_queues(
                data_sync_service,
                {"type": "app_status_changed", "data": {"app_key": "my_app"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "app_status_changed"

    def test_subscribe_min_log_level_filters_below_threshold(
        self, client: "TestClient", data_sync_service: DataSyncService
    ) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "WARNING"}})
            time.sleep(0.05)
            # DEBUG and INFO should be filtered
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "DEBUG", "message": "debug"}},
            )
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "INFO", "message": "info"}},
            )
            # WARNING should pass
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "WARNING", "message": "warn"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "WARNING"

    def test_subscribe_error_level_passes(self, client: "TestClient", data_sync_service: DataSyncService) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "ERROR"}})
            time.sleep(0.05)
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "WARNING", "message": "warn"}},
            )
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "ERROR", "message": "err"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "ERROR"

    def test_subscribe_invalid_log_level_defaults_to_info(
        self, client: "TestClient", data_sync_service: DataSyncService
    ) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "INVALID"}})
            time.sleep(0.05)
            # DEBUG should be filtered (below INFO default)
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "DEBUG", "message": "debug"}},
            )
            # INFO should pass
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "INFO", "message": "info"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "INFO"

    def test_sentinel_causes_graceful_close(self, client: "TestClient", data_sync_service: DataSyncService) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            assert len(data_sync_service._ws_clients) == 1
            # Send None sentinel to trigger graceful queue shutdown
            for q in list(data_sync_service._ws_clients):
                q.put_nowait(None)
            # The send loop will break on None, causing the task group to end.
        # After close, client should be unregistered
        assert len(data_sync_service._ws_clients) == 0

    def test_disconnect_unregisters_client(self, client: "TestClient", data_sync_service: DataSyncService) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            assert len(data_sync_service._ws_clients) == 1
        # After disconnect, client should be unregistered
        assert len(data_sync_service._ws_clients) == 0

    def test_multiple_subscribe_updates_state(self, client: "TestClient", data_sync_service: DataSyncService) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            # First subscribe with ERROR level
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "ERROR"}})
            time.sleep(0.05)
            # Update to INFO level
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "INFO"}})
            time.sleep(0.05)
            # INFO should now pass through
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "INFO", "message": "visible"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "INFO"
