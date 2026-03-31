"""Unit tests for RuntimeQueryService."""

import asyncio
import itertools
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.core.app_registry import AppInstanceInfo, AppStatusSnapshot
from hassette.core.domain_models import SystemStatus
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.logging_ import LogCaptureHandler, LogEntry
from hassette.types.enums import ResourceStatus

_test_seq = itertools.count(1)


def _next_seq() -> int:
    return next(_test_seq)


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

    # Wire public properties to private mocks
    hassette.state_proxy = hassette._state_proxy
    hassette.websocket_service = hassette._websocket_service
    hassette.app_handler = hassette._app_handler
    hassette.bus_service = hassette._bus_service
    hassette.scheduler_service = hassette._scheduler_service
    hassette.runtime_query_service = hassette._runtime_query_service

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
    hassette._state_proxy.is_ready.return_value = True

    # Mock websocket service
    hassette._websocket_service.status = "running"

    # Mock app handler
    _instance = AppInstanceInfo(
        app_key="my_app",
        index=0,
        instance_name="MyApp[0]",
        class_name="MyApp",
        status=ResourceStatus.RUNNING,
    )
    hassette._app_handler.get_status_snapshot.return_value = AppStatusSnapshot(
        running=[_instance],
        failed=[],
    )

    # Mock scheduler service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])

    # Mock children for service status
    hassette.children = []

    return hassette


@pytest.fixture
def runtime(mock_hassette):
    """Create a RuntimeQueryService instance with mocked Hassette."""
    svc = RuntimeQueryService.__new__(RuntimeQueryService)
    svc.hassette = mock_hassette
    svc._event_buffer = deque(maxlen=100)
    svc._ws_clients = set()
    svc._lock = asyncio.Lock()
    svc._ws_drops = 0
    svc._ws_drops_since_last_log = 0
    svc._ws_drops_last_logged = 0.0
    svc._start_time = 1704067200.0  # 2024-01-01 00:00:00
    svc._subscriptions = []
    svc.logger = MagicMock()
    return svc


class TestAppStatus:
    def test_get_app_status_snapshot(self, runtime: RuntimeQueryService) -> None:
        snapshot = runtime.get_app_status_snapshot()
        assert isinstance(snapshot, AppStatusSnapshot)
        assert snapshot.total_count == 1
        assert snapshot.running_count == 1
        assert snapshot.failed_count == 0
        assert len(snapshot.running) == 1
        assert snapshot.running[0].app_key == "my_app"


class TestEventBuffer:
    def test_get_recent_events_empty(self, runtime: RuntimeQueryService) -> None:
        events = runtime.get_recent_events()
        assert events == []

    def test_get_recent_events_with_data(self, runtime: RuntimeQueryService) -> None:
        for i in range(10):
            runtime._event_buffer.append({"type": "test", "index": i})

        events = runtime.get_recent_events(limit=5)
        assert len(events) == 5
        assert events[0]["index"] == 5
        assert events[-1]["index"] == 9

    def test_get_recent_events_limit_larger_than_buffer(self, runtime: RuntimeQueryService) -> None:
        runtime._event_buffer.append({"type": "test"})
        events = runtime.get_recent_events(limit=50)
        assert len(events) == 1


class TestLogAccess:
    def test_get_recent_logs_no_handler(self, runtime: RuntimeQueryService) -> None:
        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=None):
            logs = runtime.get_recent_logs()
        assert logs == []

    def test_get_recent_logs_with_entries(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        for i in range(5):
            entry = LogEntry(
                seq=_next_seq(),
                timestamp=float(i),
                level="INFO",
                logger_name="hassette.test",
                func_name="test_func",
                lineno=i,
                message=f"Message {i}",
            )
            handler._buffer.append(entry)

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs(limit=3)

        assert len(logs) == 3
        assert logs[0]["message"] == "Message 2"
        assert logs[-1]["message"] == "Message 4"

    def test_get_recent_logs_filtered_by_level(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            entry = LogEntry(
                seq=_next_seq(),
                timestamp=1.0,
                level=level,
                logger_name="hassette.test",
                func_name="test_func",
                lineno=1,
                message=f"{level} message",
            )
            handler._buffer.append(entry)

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs(level="WARNING")

        assert len(logs) == 2
        levels = {log["level"] for log in logs}
        assert levels == {"WARNING", "ERROR"}

    def test_get_recent_logs_filtered_by_app_key(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        entries = [
            LogEntry(
                seq=_next_seq(),
                timestamp=1.0,
                level="INFO",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="core msg",
            ),
            LogEntry(
                seq=_next_seq(),
                timestamp=2.0,
                level="INFO",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="app msg",
                app_key="my_app",
            ),
            LogEntry(
                seq=_next_seq(),
                timestamp=3.0,
                level="WARNING",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="other msg",
                app_key="other_app",
            ),
        ]
        handler._buffer.extend(entries)

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs(app_key="my_app")

        assert len(logs) == 1
        assert logs[0]["app_key"] == "my_app"
        assert logs[0]["message"] == "app msg"

    def test_get_recent_logs_no_filters_returns_all(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        for i in range(3):
            handler._buffer.append(
                LogEntry(
                    seq=_next_seq(),
                    timestamp=float(i),
                    level="INFO",
                    logger_name="t",
                    func_name="f",
                    lineno=1,
                    message=f"m{i}",
                )
            )

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs()

        assert len(logs) == 3

    def test_get_recent_logs_combined_filters(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        entries = [
            LogEntry(
                seq=_next_seq(),
                timestamp=1.0,
                level="INFO",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="a",
                app_key="my_app",
            ),
            LogEntry(
                seq=_next_seq(),
                timestamp=2.0,
                level="WARNING",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="b",
                app_key="my_app",
            ),
            LogEntry(
                seq=_next_seq(),
                timestamp=3.0,
                level="ERROR",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="c",
                app_key="my_app",
            ),
            LogEntry(
                seq=_next_seq(),
                timestamp=4.0,
                level="ERROR",
                logger_name="t",
                func_name="f",
                lineno=1,
                message="d",
                app_key="other_app",
            ),
            LogEntry(
                seq=_next_seq(), timestamp=5.0, level="DEBUG", logger_name="t", func_name="f", lineno=1, message="e"
            ),
        ]
        handler._buffer.extend(entries)

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs(app_key="my_app", level="WARNING")

        assert len(logs) == 2
        assert all(log["app_key"] == "my_app" for log in logs)
        levels = {log["level"] for log in logs}
        assert levels == {"WARNING", "ERROR"}

    def test_get_recent_logs_limit_applied_after_filters(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)
        for i in range(10):
            handler._buffer.append(
                LogEntry(
                    seq=_next_seq(),
                    timestamp=float(i),
                    level="ERROR",
                    logger_name="t",
                    func_name="f",
                    lineno=1,
                    message=f"err{i}",
                    app_key="my_app",
                )
            )

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs(app_key="my_app", level="ERROR", limit=3)

        assert len(logs) == 3
        # Should return the last 3 (most recent)
        assert logs[0]["message"] == "err7"
        assert logs[-1]["message"] == "err9"

    def test_get_recent_logs_empty_buffer_returns_empty(self, runtime: RuntimeQueryService) -> None:
        handler = LogCaptureHandler(buffer_size=100)

        with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=handler):
            logs = runtime.get_recent_logs()

        assert logs == []


class TestSystemStatus:
    def test_get_system_status(self, runtime: RuntimeQueryService) -> None:
        status = runtime.get_system_status()
        assert isinstance(status, SystemStatus)
        assert status.entity_count == 2
        assert status.app_count == 1
        assert isinstance(status.services_running, list)


class TestWebSocketClientManagement:
    async def test_register_and_unregister(self, runtime: RuntimeQueryService) -> None:
        queue = await runtime.register_ws_client()
        assert isinstance(queue, asyncio.Queue)
        assert len(runtime._ws_clients) == 1

        await runtime.unregister_ws_client(queue)
        assert len(runtime._ws_clients) == 0

    async def test_broadcast(self, runtime: RuntimeQueryService) -> None:
        queue = await runtime.register_ws_client()
        message = {"type": "test", "data": {"value": 42}}

        await runtime.broadcast(message)

        received = queue.get_nowait()
        assert received == message

        await runtime.unregister_ws_client(queue)

    async def test_broadcast_drops_for_full_queue(self, runtime: RuntimeQueryService) -> None:
        queue = await runtime.register_ws_client()
        # Fill the queue
        for i in range(256):
            await queue.put({"type": "filler", "index": i})

        # This should not raise, just drop
        await runtime.broadcast({"type": "dropped"})

        assert queue.qsize() == 256  # still full, message was dropped

        await runtime.unregister_ws_client(queue)
