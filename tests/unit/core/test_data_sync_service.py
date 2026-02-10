"""Unit tests for DataSyncService."""

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.data_sync_service import DataSyncService
from hassette.logging_ import LogCaptureHandler, LogEntry
from hassette.web.models import AppStatusResponse, SystemStatusResponse


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance with required attributes."""
    hassette = MagicMock()
    hassette.config.run_web_api = True
    hassette.config.web_api_event_buffer_size = 100
    hassette.config.web_api_log_level = "INFO"
    hassette.config.startup_timeout_seconds = 5
    hassette.wait_for_ready = AsyncMock(return_value=True)
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()

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
    hassette._websocket_service.status = "running"

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

    # Mock scheduler service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])
    hassette._scheduler_service.get_execution_history.return_value = []

    # Mock children for service status
    hassette.children = []

    return hassette


@pytest.fixture
def data_sync(mock_hassette):
    """Create a DataSyncService instance with mocked Hassette."""
    ds = DataSyncService.__new__(DataSyncService)
    ds.hassette = mock_hassette
    ds._event_buffer = deque(maxlen=100)
    ds._ws_clients = set()
    ds._lock = asyncio.Lock()
    ds._start_time = 1704067200.0  # 2024-01-01 00:00:00
    ds._subscriptions = []
    ds.logger = MagicMock()
    return ds


class TestEntityStateAccess:
    def test_get_entity_state_found(self, data_sync: DataSyncService) -> None:
        state = data_sync.get_entity_state("light.kitchen")
        assert state is not None
        assert state["state"] == "on"

    def test_get_entity_state_not_found(self, data_sync: DataSyncService) -> None:
        data_sync.hassette._state_proxy.get_state.side_effect = lambda _: None
        state = data_sync.get_entity_state("nonexistent.entity")
        assert state is None

    def test_get_all_entity_states(self, data_sync: DataSyncService) -> None:
        states = data_sync.get_all_entity_states()
        assert len(states) == 2
        assert "light.kitchen" in states
        assert "sensor.temp" in states

    def test_get_domain_states(self, data_sync: DataSyncService) -> None:
        states = data_sync.get_domain_states("light")
        assert len(states) == 1
        assert "light.kitchen" in states


class TestAppStatus:
    def test_get_app_status_snapshot(self, data_sync: DataSyncService) -> None:
        snapshot = data_sync.get_app_status_snapshot()
        assert isinstance(snapshot, AppStatusResponse)
        assert snapshot.total == 1
        assert snapshot.running == 1
        assert snapshot.failed == 0
        assert len(snapshot.apps) == 1
        assert snapshot.apps[0].app_key == "my_app"


class TestEventBuffer:
    def test_get_recent_events_empty(self, data_sync: DataSyncService) -> None:
        events = data_sync.get_recent_events()
        assert events == []

    def test_get_recent_events_with_data(self, data_sync: DataSyncService) -> None:
        for i in range(10):
            data_sync._event_buffer.append({"type": "test", "index": i})

        events = data_sync.get_recent_events(limit=5)
        assert len(events) == 5
        assert events[0]["index"] == 5
        assert events[-1]["index"] == 9

    def test_get_recent_events_limit_larger_than_buffer(self, data_sync: DataSyncService) -> None:
        data_sync._event_buffer.append({"type": "test"})
        events = data_sync.get_recent_events(limit=50)
        assert len(events) == 1


class TestLogAccess:
    def test_get_recent_logs_no_handler(self, data_sync: DataSyncService) -> None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=None):
            logs = data_sync.get_recent_logs()
        assert logs == []

    def test_get_recent_logs_with_entries(self, data_sync: DataSyncService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        for i in range(5):
            entry = LogEntry(
                timestamp=float(i),
                level="INFO",
                logger_name="hassette.test",
                func_name="test_func",
                lineno=i,
                message=f"Message {i}",
            )
            handler._buffer.append(entry)

        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            logs = data_sync.get_recent_logs(limit=3)

        assert len(logs) == 3
        assert logs[0]["message"] == "Message 2"
        assert logs[-1]["message"] == "Message 4"

    def test_get_recent_logs_filtered_by_level(self, data_sync: DataSyncService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            entry = LogEntry(
                timestamp=1.0,
                level=level,
                logger_name="hassette.test",
                func_name="test_func",
                lineno=1,
                message=f"{level} message",
            )
            handler._buffer.append(entry)

        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=handler):
            logs = data_sync.get_recent_logs(level="WARNING")

        assert len(logs) == 2
        levels = {log["level"] for log in logs}
        assert levels == {"WARNING", "ERROR"}


class TestSchedulerAccess:
    async def test_get_scheduled_jobs_empty(self, data_sync: DataSyncService) -> None:
        jobs = await data_sync.get_scheduled_jobs()
        assert jobs == []

    def test_get_job_execution_history_empty(self, data_sync: DataSyncService) -> None:
        history = data_sync.get_job_execution_history()
        assert history == []


class TestSystemStatus:
    def test_get_system_status(self, data_sync: DataSyncService) -> None:
        status = data_sync.get_system_status()
        assert isinstance(status, SystemStatusResponse)
        assert status.entity_count == 2
        assert status.app_count == 1


class TestWebSocketClientManagement:
    async def test_register_and_unregister(self, data_sync: DataSyncService) -> None:
        queue = await data_sync.register_ws_client()
        assert isinstance(queue, asyncio.Queue)
        assert len(data_sync._ws_clients) == 1

        data_sync.unregister_ws_client(queue)
        assert len(data_sync._ws_clients) == 0

    async def test_broadcast(self, data_sync: DataSyncService) -> None:
        queue = await data_sync.register_ws_client()
        message = {"type": "test", "data": {"value": 42}}

        await data_sync.broadcast(message)

        received = queue.get_nowait()
        assert received == message

        data_sync.unregister_ws_client(queue)

    async def test_broadcast_drops_for_full_queue(self, data_sync: DataSyncService) -> None:
        queue = await data_sync.register_ws_client()
        # Fill the queue
        for i in range(256):
            await queue.put({"type": "filler", "index": i})

        # This should not raise, just drop
        await data_sync.broadcast({"type": "dropped"})

        assert queue.qsize() == 256  # still full, message was dropped

        data_sync.unregister_ws_client(queue)
