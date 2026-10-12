"""Unit tests for WebsocketService readiness event emission.

Verifies that _emit_readiness_event() is called after mark_not_ready() and mark_ready()
on serve()'s connection-state transitions, and only on those (D11).
"""

from unittest.mock import AsyncMock, Mock

import pytest

import hassette.core.websocket_reconnect as reconnect_module
from hassette.core.websocket_reconnect import NOT_CONNECTED_REASON
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import RetryableConnectionClosedError
from hassette.testing import EventCapture
from hassette.testing._ws_mocks import make_task_bucket_spawn_stub, run_connect_sequence
from hassette.types import Topic
from hassette.types.enums import ConnectionState


class TestWebsocketReadinessEvents:
    """Tests that _emit_readiness_event() fires at the correct serve() transition points."""

    async def test_drop_of_established_connection_emits_not_ready_event(
        self,
        websocket_service: WebsocketService,
        event_capture: EventCapture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Losing an established connection emits one service_status event with ready=False and a reason."""
        event_capture.install(websocket_service.hassette)
        monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_CAP_SECONDS", 0.0)
        attempts = 0

        async def fake_run_connection(_session) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                await run_connect_sequence_stubbed(websocket_service)
                raise RetryableConnectionClosedError("peer gone")

        websocket_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]

        await websocket_service.serve()

        not_ready_events = [
            event
            for event in event_capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS)
            if not event.payload.data.ready
        ]
        assert len(not_ready_events) == 1
        assert not_ready_events[0].payload.data.ready_phase == NOT_CONNECTED_REASON

    async def test_failed_attempt_before_any_connection_emits_no_readiness_event(
        self,
        websocket_service: WebsocketService,
        event_capture: EventCapture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Failed attempts with no established connection change no readiness (D11: transitions only)."""
        event_capture.install(websocket_service.hassette)
        monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_CAP_SECONDS", 0.0)
        attempts = 0

        async def fake_run_connection(_session) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 5:
                raise ConnectionRefusedError("refused")

        websocket_service.run_connection = fake_run_connection  # pyright: ignore[reportAttributeAccessIssue]

        await websocket_service.serve()

        assert event_capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS) == []

    async def test_mark_ready_after_connect_emits_event(
        self,
        websocket_service: WebsocketService,
        event_capture: EventCapture,
    ) -> None:
        """Successful connect path emits a service_status event with ready=True after mark_ready().

        Runs the real connect sequence with sub-methods stubbed to isolate mark_connected()'s
        mark_ready() → _emit_readiness_event() call.

        Companion: test_mark_connected_marks_ready_and_publishes_connected in
        tests/integration/websocket/test_connection.py asserts the structural side (generation,
        _connected_at set) of the same method.
        """
        event_capture.install(websocket_service.hassette)

        # Stub out the sub-methods the connect sequence calls so we can run the real
        # methods and observe whether they call _emit_readiness_event() after mark_ready().
        spawned_coros, spawn_stub = make_task_bucket_spawn_stub()

        websocket_service.task_bucket = Mock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.task_bucket.spawn = spawn_stub
        websocket_service.send_connection_established_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]

        await run_connect_sequence(websocket_service, spawned_coros)

        # Assert: _emit_readiness_event() was called → a service_status event with ready=True was sent
        service_status_calls = event_capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS)
        assert len(service_status_calls) >= 1, (
            f"Expected at least one service_status event, got topics: {event_capture.topics}"
        )

        ready_events = [event for event in service_status_calls if event.payload.data.ready]
        assert len(ready_events) >= 1, "Expected at least one service_status event with ready=True"

        first_ready = ready_events[0]
        payload = first_ready.payload.data
        assert payload.ready is True
        assert payload.ready_phase is not None
        assert "connected" in payload.ready_phase.lower()

    async def test_reentrant_disconnect_during_connected_dispatch_emits_disconnected_event(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """A disconnect triggered during connected handlers still emits the public disconnect signal."""
        topics: list[Topic] = []

        async def reentrant_send(event) -> None:
            topics.append(event.topic)
            if event.topic == Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED:
                await websocket_service.send_connection_lost_event()

        spawned_coros, spawn_stub = make_task_bucket_spawn_stub()

        websocket_service.hassette.send_event = reentrant_send
        websocket_service.task_bucket = Mock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.task_bucket.spawn = spawn_stub
        websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]

        websocket_service._connection_state = ConnectionState.CONNECTING

        await run_connect_sequence(websocket_service, spawned_coros)

        assert topics == [
            Topic.HASSETTE_EVENT_SERVICE_STATUS,
            Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED,
            Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED,
        ]

    async def test_connected_event_failure_does_not_revoke_external_readiness(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """Connected-event delivery is observational, not part of WebSocket capability."""
        spawned_coros, spawn_stub = make_task_bucket_spawn_stub()

        async def fail_connected_event(event) -> None:
            if event.topic == Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED:
                raise RuntimeError("event stream closed")

        websocket_service.hassette.send_event = fail_connected_event
        websocket_service.task_bucket = Mock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.task_bucket.spawn = spawn_stub
        websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service._connection_state = ConnectionState.CONNECTING

        await run_connect_sequence(websocket_service, spawned_coros)

        assert websocket_service.is_connected is True
        assert await websocket_service.wait_connected(timeout=0) is True
        assert websocket_service.get_connected_generation() == 1


class TestHasEverConnectedLatch:
    """has_ever_connected latch starts False, flips True on CONNECTED, stays True after disconnect."""

    def test_has_ever_connected_starts_false(self, websocket_service: WebsocketService) -> None:
        """has_ever_connected is False before any connection transition."""
        assert websocket_service.has_ever_connected is False

    def test_has_ever_connected_becomes_true_after_connected_transition(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """has_ever_connected flips True when set_connection_state transitions to CONNECTED."""
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        assert websocket_service.has_ever_connected is False  # not yet

        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        assert websocket_service.has_ever_connected is True

    def test_has_ever_connected_stays_true_after_disconnect(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """has_ever_connected remains True after a subsequent disconnect (one-way latch)."""
        websocket_service.set_connection_state(ConnectionState.CONNECTING)
        websocket_service.set_connection_state(ConnectionState.CONNECTED)
        assert websocket_service.has_ever_connected is True

        websocket_service.set_connection_state(ConnectionState.DISCONNECTED)
        assert websocket_service.has_ever_connected is True  # latch does not revert


async def run_connect_sequence_stubbed(websocket_service: WebsocketService) -> None:
    """Reach CONNECTED through the real connect sequence with the recv task and subscription stubbed."""
    spawned_coros, spawn_stub = make_task_bucket_spawn_stub()
    websocket_service.task_bucket = Mock()  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.task_bucket.spawn = spawn_stub
    websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]
    await run_connect_sequence(websocket_service, spawned_coros)
