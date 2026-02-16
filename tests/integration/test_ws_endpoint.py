"""Integration tests for the WebSocket endpoint (ws.py)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from hassette.core.data_sync_service import DataSyncService
from hassette.test_utils.mock_hassette import create_mock_data_sync_service, create_mock_hassette
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
    return create_mock_hassette(
        run_web_ui=False,
        cors_origins=(),
        states={"light.kitchen": {"entity_id": "light.kitchen", "state": "on"}},
        old_snapshot=SimpleNamespace(
            running=[], failed=[], total_count=3, running_count=2, failed_count=1, only_app=None
        ),
    )


@pytest.fixture
def data_sync_service(mock_hassette):
    """Create a real DataSyncService with mocked Hassette."""
    return create_mock_data_sync_service(mock_hassette)


@pytest.fixture
def app(mock_hassette, data_sync_service):
    fastapi_app = create_fastapi_app(mock_hassette)

    async def _capture_loop():
        data_sync_service._test_loop = asyncio.get_running_loop()

    fastapi_app.router.on_startup.append(_capture_loop)
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


def _put_to_all_queues(data_sync: DataSyncService, message: dict) -> None:
    """Put a pre-serialized message into all registered WS client queues.

    The Starlette TestClient runs the ASGI app in a background thread
    with its own event loop.  We use ``call_soon_threadsafe`` to schedule
    the ``put_nowait`` on the correct loop so that any waiting ``get()``
    futures are woken up safely.
    """
    safe = json.loads(json.dumps(message, default=str))
    loop = getattr(data_sync, "_test_loop", None)
    for q in list(data_sync._ws_clients):
        if loop is not None:
            loop.call_soon_threadsafe(q.put_nowait, safe)
        else:
            q.put_nowait(safe)


def _sync_via_ping(ws) -> None:
    """Send a ping and wait for the pong to ensure prior messages were processed.

    The server handles ``subscribe`` and ``ping`` sequentially in the same
    reader coroutine, so receiving the ``pong`` guarantees the preceding
    ``subscribe`` has already been applied.
    """
    ws.send_json({"type": "ping"})
    msg = ws.receive_json()
    assert msg["type"] == "pong"


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
            _sync_via_ping(ws)
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
            _sync_via_ping(ws)
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
            _sync_via_ping(ws)
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "WARNING", "message": "warn"}},
            )
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "ERROR", "message": "err"}},
            )
            # receive_json() blocks until a message arrives.  Since the
            # WARNING was enqueued *before* the ERROR, the fact that the next
            # (and only) message we receive is ERROR proves the WARNING was
            # filtered out by the min_log_level subscription.
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "ERROR"

    def test_subscribe_invalid_log_level_defaults_to_info(
        self, client: "TestClient", data_sync_service: DataSyncService
    ) -> None:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "INVALID"}})
            _sync_via_ping(ws)
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
            _sync_via_ping(ws)
            # Update to INFO level
            ws.send_json({"type": "subscribe", "data": {"logs": True, "min_log_level": "INFO"}})
            _sync_via_ping(ws)
            # INFO should now pass through
            _put_to_all_queues(
                data_sync_service,
                {"type": "log", "data": {"level": "INFO", "message": "visible"}},
            )
            msg = ws.receive_json()
            assert msg["type"] == "log"
            assert msg["data"]["level"] == "INFO"
