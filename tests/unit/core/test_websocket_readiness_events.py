"""Unit tests for WebsocketService readiness event emission.

Verifies that _emit_readiness_event() is called after mark_not_ready() and mark_ready()
in the serve() reconnect paths.
"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import RetryableConnectionClosedError
from hassette.resources.lifecycle import mark_ready
from hassette.test_utils import make_ws_hassette_stub
from hassette.types import Topic
from hassette.types.enums import ConnectionState


@pytest.fixture
async def websocket_service() -> WebsocketService:
    """Create a WebsocketService with a fully-mocked hassette stub."""
    hassette = make_ws_hassette_stub(sealed=False)
    return WebsocketService(hassette=hassette)


class TestWebsocketReadinessEvents:
    """Tests that _emit_readiness_event() fires at the correct serve() transition points."""

    async def test_mark_not_ready_early_drop_emits_event(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """Early-drop path emits a service_status event with ready=False after mark_not_ready()."""
        send_event_calls: list = []

        async def capture_send_event(event):
            send_event_calls.append(event)

        websocket_service.hassette.send_event = capture_send_event  # pyright: ignore[reportAttributeAccessIssue]

        # Arrange: service starts ready, _connected_at in stable window
        mark_ready(websocket_service, reason="test: pre-state")
        websocket_service._connected_at = time.monotonic()

        # Mock make_connection to return a task that fails with RetryableConnectionClosedError
        # on the first call, then succeeds on the second.
        call_count = 0

        async def fake_make_connection(_session):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate successful connection (mark_ready mirrors what start_recv_and_subscribe does)
                websocket_service._connected_at = time.monotonic()
                mark_ready(websocket_service, reason="test: connected")

                async def _fail():
                    raise RetryableConnectionClosedError("peer gone")

                return asyncio.create_task(_fail())

            # Second call: clean exit
            async def _clean():
                pass

            return asyncio.create_task(_clean())

        websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]  # boundary-exempt: collaborator of serve()
        websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]  # boundary-exempt: collaborator of serve()

        await websocket_service.serve()

        # Assert: a service_status event with ready=False was emitted during the early-drop path
        service_status_calls = [
            event for event in send_event_calls if event.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS
        ]
        assert len(service_status_calls) >= 1, (
            f"Expected at least one service_status event, got: {[e.topic for e in send_event_calls]}"
        )

        # Find the not-ready emission (early-drop path)
        not_ready_events = [event for event in service_status_calls if not event.payload.data.ready]
        assert len(not_ready_events) >= 1, "Expected at least one service_status event with ready=False"

        first_not_ready = not_ready_events[0]
        payload = first_not_ready.payload.data
        assert payload.ready is False
        assert payload.ready_phase is not None
        assert "Early drop" in payload.ready_phase

    async def test_mark_not_ready_recv_loop_failed_emits_event(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """Recv-loop-failure path emits a service_status event with ready=False."""
        send_event_calls: list = []

        async def capture_send_event(event):
            send_event_calls.append(event)

        websocket_service.hassette.send_event = capture_send_event  # pyright: ignore[reportAttributeAccessIssue]

        # Arrange: service starts ready, _connected_at set to 60s ago (outside stable window)
        mark_ready(websocket_service, reason="test: pre-state")

        async def fake_make_connection(_session):
            # Outside stable window → not an early drop → propagates as genuine failure
            websocket_service._connected_at = time.monotonic() - 60.0
            mark_ready(websocket_service, reason="test: connected")

            async def _fail():
                raise RetryableConnectionClosedError("stable drop")

            return asyncio.create_task(_fail())

        websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]  # boundary-exempt: collaborator of serve()

        with pytest.raises(RetryableConnectionClosedError):
            await websocket_service.serve()

        service_status_calls = [
            event for event in send_event_calls if event.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS
        ]
        assert len(service_status_calls) >= 1, "Expected at least one service_status event"

        not_ready_events = [event for event in service_status_calls if not event.payload.data.ready]
        assert len(not_ready_events) >= 1, "Expected at least one service_status event with ready=False"
        assert not_ready_events[0].payload.data.ready is False

    async def test_mark_ready_after_connect_emits_event(
        self,
        websocket_service: WebsocketService,
    ) -> None:
        """Successful connect path emits a service_status event with ready=True after mark_ready().

        Runs the real start_recv_and_subscribe() with sub-methods stubbed to isolate
        the mark_ready() → _emit_readiness_event() call that subtask 3 adds.

        Companion: test_websocket_service.py::test_start_recv_and_subscribe_marks_ready asserts
        the structural side (recv task spawned, _connected_at set) of the same method.
        """
        send_event_calls: list = []

        async def capture_send_event(event):
            send_event_calls.append(event)

        websocket_service.hassette.send_event = capture_send_event  # pyright: ignore[reportAttributeAccessIssue]

        # Stub out the sub-methods that start_recv_and_subscribe calls so we can run the
        # real method and observe whether it calls _emit_readiness_event() after mark_ready().
        spawned_coros: list = []

        def _spawn_side_effect(coro, *, name=None):  # noqa: ARG001
            spawned_coros.append(coro)

            async def _noop():
                pass

            return asyncio.create_task(_noop())

        websocket_service.task_bucket = Mock()  # pyright: ignore[reportAttributeAccessIssue]
        websocket_service.task_bucket.spawn = Mock(side_effect=_spawn_side_effect)
        websocket_service.send_connection_established_event = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]  # boundary-exempt: collaborator of start_recv_and_subscribe
        websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]  # boundary-exempt: collaborator of start_recv_and_subscribe

        result_task = await websocket_service.start_recv_and_subscribe()

        # Close spawned coroutines to suppress ResourceWarning
        for coro in spawned_coros:
            coro.close()
        result_task.cancel()

        # Assert: _emit_readiness_event() was called → a service_status event with ready=True was sent
        service_status_calls = [
            event for event in send_event_calls if event.topic == Topic.HASSETTE_EVENT_SERVICE_STATUS
        ]
        assert len(service_status_calls) >= 1, (
            f"Expected at least one service_status event, got topics: {[e.topic for e in send_event_calls]}"
        )

        ready_events = [event for event in service_status_calls if event.payload.data.ready]
        assert len(ready_events) >= 1, "Expected at least one service_status event with ready=True"

        first_ready = ready_events[0]
        payload = first_ready.payload.data
        assert payload.ready is True
        assert payload.ready_phase is not None
        assert "connected" in payload.ready_phase.lower()


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
