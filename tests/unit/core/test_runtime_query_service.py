"""Unit tests for RuntimeQueryService."""

import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppStatusSnapshot
from hassette.core.domain_models import SystemStatus
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.events.hassette import (
    HassetteExecutionCompletedEvent,
    HassetteInvocationCompletedEvent,
    HassetteServiceEvent,
)
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.types.enums import ResourceRole, ResourceStatus

EVENT_BUFFER_SIZE = 100
WS_QUEUE_MAX = 256


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance with required attributes."""
    hassette = make_mock_hassette(
        sealed=False,
        web_api={"run": True, "event_buffer_size": EVENT_BUFFER_SIZE},
        lifecycle={"startup_timeout_seconds": 5},
    )

    # Wire public properties to private mocks
    hassette.state_proxy = hassette._state_proxy
    hassette.websocket_service = hassette._websocket_service
    hassette.app_handler = hassette._app_handler
    hassette.bus_service = hassette._bus_service
    hassette.scheduler_service = hassette._scheduler_service
    hassette.runtime_query_service = hassette._runtime_query_service

    # get_log_records_dropped() is synchronous; replace AsyncMock with Mock
    hassette.get_log_records_dropped = Mock(return_value=0)

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
    hassette._state_proxy.is_ready = Mock(return_value=True)

    # Mock websocket service — is_ready() is synchronous; replace AsyncMock with Mock
    hassette._websocket_service.status = ResourceStatus.RUNNING
    hassette._websocket_service.is_ready = Mock(return_value=True)

    # Mock app handler — sync methods need explicit Mock (parent is AsyncMock)
    instance = AppInstanceInfo(
        app_key="my_app",
        index=0,
        instance_name="MyApp[0]",
        class_name="MyApp",
        status=ResourceStatus.RUNNING,
    )
    hassette._app_handler.get_status_snapshot = Mock(return_value=AppStatusSnapshot(running=[instance], failed=[]))
    hassette._app_handler.registry.get_full_snapshot = Mock(return_value=AppFullSnapshot(manifests=[]))

    # Mock scheduler service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=[])

    return hassette


@pytest.fixture
def runtime(mock_hassette):
    """Create a RuntimeQueryService instance with mocked Hassette."""
    svc = RuntimeQueryService.__new__(RuntimeQueryService)
    svc.hassette = mock_hassette
    svc._event_buffer = deque(maxlen=EVENT_BUFFER_SIZE)
    svc._ws_clients = set()
    svc._lock = asyncio.Lock()
    svc._ws_drops = 0
    svc._ws_drops_since_last_log = 0
    svc._ws_drops_last_logged = 0.0
    svc._start_time = 1704067200.0  # 2024-01-01 00:00:00
    svc._subscriptions = []
    svc.logger = MagicMock()
    svc._pending_invocations = []
    svc._pending_executions = []
    svc._flush_scheduled = False
    svc.task_bucket = MagicMock()
    svc.task_bucket.spawn = MagicMock(side_effect=lambda coro, **_kw: coro.close())
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


class TestCompletionPayloadEnrichment:
    """app_key and instance_index are read directly from event payload (no meta dict)."""

    async def test_invocation_payload_carries_app_identity(self, runtime: RuntimeQueryService) -> None:
        """app_key and instance_index from the payload are stored in the pending dict."""
        runtime.broadcast = AsyncMock()
        ev = HassetteInvocationCompletedEvent.from_record(
            listener_id=42, status="success", duration_ms=5.0, app_key="lights", instance_index=1
        )
        await runtime._on_invocation_completed(ev)
        assert runtime._pending_invocations[0]["app_key"] == "lights"
        assert runtime._pending_invocations[0]["instance_index"] == 1

    async def test_execution_payload_carries_app_identity(self, runtime: RuntimeQueryService) -> None:
        """app_key and instance_index from the payload are stored in the pending dict."""
        runtime.broadcast = AsyncMock()
        ev = HassetteExecutionCompletedEvent.from_record(
            job_id=99, status="success", duration_ms=8.0, app_key="climate", instance_index=2
        )
        await runtime._on_execution_completed(ev)
        assert runtime._pending_executions[0]["app_key"] == "climate"
        assert runtime._pending_executions[0]["instance_index"] == 2

    async def test_invocation_payload_defaults_to_empty_app_key(self, runtime: RuntimeQueryService) -> None:
        """Events without app_key default to empty string and zero index."""
        runtime.broadcast = AsyncMock()
        ev = HassetteInvocationCompletedEvent.from_record(listener_id=999, status="success", duration_ms=5.0)
        await runtime._on_invocation_completed(ev)
        assert runtime._pending_invocations[0]["app_key"] == ""
        assert runtime._pending_invocations[0]["instance_index"] == 0


class TestCompletionBatching:
    """Per-drain batching: all completions in one tick become one WS message per type."""

    async def test_invocation_completion_batched_into_one_message(self, runtime: RuntimeQueryService) -> None:
        """Multiple _on_invocation_completed calls in the same tick emit one broadcast."""
        broadcast_calls: list[dict] = []

        async def fake_broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        runtime.broadcast = fake_broadcast

        ev1 = HassetteInvocationCompletedEvent.from_record(
            listener_id=1, status="success", duration_ms=10.0, app_key="my_app", instance_index=0
        )
        ev2 = HassetteInvocationCompletedEvent.from_record(
            listener_id=2,
            status="failed",
            duration_ms=20.0,
            app_key="my_app",
            instance_index=0,
            error_type="ValueError",
        )

        await runtime._on_invocation_completed(ev1)
        await runtime._on_invocation_completed(ev2)

        # Flush should not have fired yet (still in the same tick)
        assert len(broadcast_calls) == 0

        # Manually flush (simulates asyncio.sleep(0) yielding)
        await runtime._flush_completions()

        assert len(broadcast_calls) == 1
        msg = broadcast_calls[0]
        assert msg["type"] == "invocation_completed"
        assert len(msg["data"]) == 2
        assert msg["data"][0]["listener_id"] == 1
        assert msg["data"][0]["app_key"] == "my_app"
        assert msg["data"][1]["listener_id"] == 2
        assert msg["data"][1]["status"] == "failed"
        assert msg["data"][1]["error_type"] == "ValueError"

    async def test_execution_completion_batched_into_one_message(self, runtime: RuntimeQueryService) -> None:
        """Multiple _on_execution_completed calls in the same tick emit one broadcast."""
        broadcast_calls: list[dict] = []

        async def fake_broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        runtime.broadcast = fake_broadcast

        ev1 = HassetteExecutionCompletedEvent.from_record(
            job_id=10, status="success", duration_ms=50.0, app_key="scheduler_app", instance_index=0
        )
        ev2 = HassetteExecutionCompletedEvent.from_record(
            job_id=11, status="success", duration_ms=30.0, app_key="scheduler_app", instance_index=0
        )

        await runtime._on_execution_completed(ev1)
        await runtime._on_execution_completed(ev2)

        assert len(broadcast_calls) == 0
        await runtime._flush_completions()

        assert len(broadcast_calls) == 1
        msg = broadcast_calls[0]
        assert msg["type"] == "execution_completed"
        assert len(msg["data"]) == 2

    async def test_flush_completions_written_to_event_buffer(self, runtime: RuntimeQueryService) -> None:
        """Batched completion messages are appended to _event_buffer for replay."""
        runtime.broadcast = AsyncMock()

        ev = HassetteInvocationCompletedEvent.from_record(
            listener_id=5, status="success", duration_ms=1.0, app_key="buf_app", instance_index=0
        )
        await runtime._on_invocation_completed(ev)
        await runtime._flush_completions()

        assert len(runtime._event_buffer) == 1
        buffered = runtime._event_buffer[0]
        assert buffered["type"] == "invocation_completed"
        assert buffered["data"][0]["listener_id"] == 5

    async def test_flush_resets_pending_lists(self, runtime: RuntimeQueryService) -> None:
        """After flush, pending lists are empty."""
        runtime.broadcast = AsyncMock()

        ev = HassetteInvocationCompletedEvent.from_record(
            listener_id=3, status="success", duration_ms=1.0, app_key="app", instance_index=0
        )
        await runtime._on_invocation_completed(ev)
        assert len(runtime._pending_invocations) == 1

        await runtime._flush_completions()
        assert len(runtime._pending_invocations) == 0
        assert len(runtime._pending_executions) == 0

    async def test_flush_noop_when_no_pending(self, runtime: RuntimeQueryService) -> None:
        """Flush with empty pending lists does not call broadcast."""
        runtime.broadcast = AsyncMock()
        await runtime._flush_completions()
        runtime.broadcast.assert_not_awaited()

    async def test_mixed_invocation_and_execution_emit_separate_messages(self, runtime: RuntimeQueryService) -> None:
        """Both types present → two separate broadcast messages (one per type)."""
        broadcast_calls: list[dict] = []

        async def fake_broadcast(msg: dict) -> None:
            broadcast_calls.append(msg)

        runtime.broadcast = fake_broadcast

        inv_ev = HassetteInvocationCompletedEvent.from_record(
            listener_id=1, status="success", duration_ms=5.0, app_key="my_app", instance_index=0
        )
        exec_ev = HassetteExecutionCompletedEvent.from_record(
            job_id=10, status="success", duration_ms=8.0, app_key="my_app", instance_index=0
        )

        await runtime._on_invocation_completed(inv_ev)
        await runtime._on_execution_completed(exec_ev)
        await runtime._flush_completions()

        assert len(broadcast_calls) == 2
        types = {m["type"] for m in broadcast_calls}
        assert types == {"invocation_completed", "execution_completed"}


class TestSystemStatus:
    def test_get_system_status(self, runtime: RuntimeQueryService) -> None:
        status = runtime.get_system_status()
        assert isinstance(status, SystemStatus)
        assert status.entity_count == 2
        assert status.app_count == 1
        assert isinstance(status.services_running, list)

    def test_system_status_ws_connected_reflects_readiness(self, runtime: RuntimeQueryService) -> None:
        """ws_connected is False when websocket_service.is_ready() returns False.

        This covers the early-drop retry case: status is RUNNING but the service
        is not ready (the WebSocket dropped post-auth and a retry is in progress).
        """
        runtime.hassette.websocket_service.is_ready.return_value = False
        status = runtime.get_system_status()
        assert status.websocket_connected is False

    def test_system_status_ws_connected_true_when_ready(self, runtime: RuntimeQueryService) -> None:
        """ws_connected is True when websocket_service.is_ready() returns True."""
        runtime.hassette.websocket_service.is_ready.return_value = True
        status = runtime.get_system_status()
        assert status.websocket_connected is True


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
        for i in range(WS_QUEUE_MAX):
            await queue.put({"type": "filler", "index": i})

        # This should not raise, just drop
        await runtime.broadcast({"type": "dropped"})

        assert queue.qsize() == WS_QUEUE_MAX  # still full, message was dropped

        await runtime.unregister_ws_client(queue)


class TestServiceStatusMapping:
    async def test_on_service_status_maps_ready_fields(self, runtime: RuntimeQueryService) -> None:
        broadcast_calls: list[dict] = []
        runtime.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))

        event = HassetteServiceEvent.from_data(
            resource_name="WebsocketService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.RUNNING,
            ready=True,
            ready_phase="Connected and authenticated",
        )
        await runtime._on_service_status(event)

        assert len(broadcast_calls) == 1
        data = broadcast_calls[0]["data"]
        assert data["ready"] is True
        assert data["ready_phase"] == "Connected and authenticated"

    async def test_on_service_status_defaults_ready_false(self, runtime: RuntimeQueryService) -> None:
        broadcast_calls: list[dict] = []
        runtime.broadcast = AsyncMock(side_effect=lambda msg: broadcast_calls.append(msg))

        event = HassetteServiceEvent.from_data(
            resource_name="SomeService",
            role=ResourceRole.SERVICE,
            status=ResourceStatus.STARTING,
        )
        await runtime._on_service_status(event)

        assert len(broadcast_calls) == 1
        data = broadcast_calls[0]["data"]
        assert data["ready"] is False
        assert data["ready_phase"] is None
