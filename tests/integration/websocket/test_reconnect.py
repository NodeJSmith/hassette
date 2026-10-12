"""partial_cleanup and connection-lost-event tests for WebsocketService.

Complements test_reconnect_loop.py (serve()'s reconnect loop against a scripted HA server),
test_connection.py (connection/auth), test_dispatch.py (send/dispatch), and
test_subscribe_events_retry.py.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import hassette.resources.lifecycle as lifecycle_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import RetryableConnectionClosedError
from hassette.testing import EventCapture
from hassette.testing._ws_mocks import build_fake_ws, mark_websocket_service_connected
from hassette.types import Topic
from hassette.types.enums import ConnectionState


async def test_partial_cleanup_cancels_recv_and_closes_ws(websocket_service: WebsocketService) -> None:
    """partial_cleanup cancels recv task, closes ws, clears futures and subscription ids."""
    fake_ws = build_fake_ws()
    fake_recv_task = asyncio.create_task(asyncio.sleep(100))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = fake_recv_task
    websocket_service._subscription_ids = {1, 2}

    # Seed a pending future
    fut = websocket_service.hassette.loop.create_future()
    websocket_service._pending.register(99, fut)

    await websocket_service.partial_cleanup()

    assert websocket_service._ws is None
    assert websocket_service._recv_task is None
    assert websocket_service._subscription_ids == set()
    assert websocket_service._pending.entries == {}
    assert fut.done()
    assert isinstance(fut.exception(), RetryableConnectionClosedError)


async def test_partial_cleanup_preserves_session(websocket_service: WebsocketService) -> None:
    """partial_cleanup must NOT clear self._session."""
    fake_session = MagicMock()
    websocket_service._session = fake_session
    websocket_service._ws = build_fake_ws()
    websocket_service._recv_task = asyncio.create_task(asyncio.sleep(0))

    await websocket_service.partial_cleanup()

    assert websocket_service._session is fake_session


async def test_partial_cleanup_suppresses_errors(websocket_service: WebsocketService) -> None:
    """partial_cleanup must not propagate any exceptions."""
    fake_ws = build_fake_ws()
    fake_ws.close = AsyncMock(side_effect=RuntimeError("close failed"))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = None

    # Should not raise
    await websocket_service.partial_cleanup()


async def test_partial_cleanup_timeout_on_gather(websocket_service: WebsocketService) -> None:
    """partial_cleanup completes within ~2s even when recv task is non-cancellable."""

    async def _never_ends():
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:  # noqa: ASYNC103 — intentionally simulates a task that ignores cancellation
            await asyncio.sleep(1000)

    stuck_task = asyncio.create_task(_never_ends())
    websocket_service._recv_task = stuck_task
    websocket_service._ws = build_fake_ws()

    started = time.monotonic()
    try:
        await websocket_service.partial_cleanup()
        elapsed = time.monotonic() - started
        assert elapsed < 4.0, f"partial_cleanup took too long: {elapsed:.2f}s"
    finally:
        stuck_task.cancel()
        await asyncio.gather(stuck_task, return_exceptions=True)


async def test_send_connection_lost_event_idempotent(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event is a no-op when the connection has never been established."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    # Fresh service has never connected; calling send_connection_lost_event should be a no-op
    assert not websocket_service.has_ever_connected
    await websocket_service.send_connection_lost_event()

    disconnected_count = len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED))
    assert disconnected_count == 0, "Expected no DISCONNECTED events when never connected"


async def test_send_connection_lost_event_skips_before_first_connection(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event does not fire when ready but never connected.

    With unconditional mark_ready() in on_initialize(), the service can be lifecycle-ready
    before HA is ever reachable — the guard must key off has_ever_connected, not is_ready(),
    to avoid a spurious DISCONNECTED event in that window.
    """
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    lifecycle_module.mark_ready(websocket_service, reason="test: service marked ready, no connection yet")
    assert websocket_service.is_ready()
    assert not websocket_service.has_ever_connected

    await websocket_service.send_connection_lost_event()

    disconnected_count = len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED))
    assert disconnected_count == 0, "Expected no DISCONNECTED event before the first successful connection"


async def test_send_connection_lost_event_self_suppressing(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event does not propagate bus exceptions."""
    websocket_service.hassette.send_event = AsyncMock(side_effect=RuntimeError("bus is down"))
    # The event fires only for an announced connection — simulate one so the send is attempted
    # and self-suppression is exercised.
    mark_websocket_service_connected(websocket_service, reason="test: make service ready so event fires")

    # Should not raise even though the bus raises
    await websocket_service.send_connection_lost_event()


async def test_recv_task_cancelled_from_outside_is_a_lost_connection(websocket_service: WebsocketService) -> None:
    """Cancelling the attached recv task by anything but our cleanup disconnects at once and fails pending replies."""
    websocket_service._ws = build_fake_ws()
    websocket_service._connection_state = ConnectionState.CONNECTED
    recv_task = asyncio.create_task(asyncio.sleep(100))
    websocket_service._recv_task = recv_task
    recv_task.add_done_callback(websocket_service._handle_recv_task_done)
    fut = websocket_service.hassette.loop.create_future()
    websocket_service._pending.register(7, fut)

    recv_task.cancel()
    await asyncio.gather(recv_task, return_exceptions=True)
    await asyncio.sleep(0)

    assert websocket_service.connection_state == ConnectionState.DISCONNECTED
    assert fut.done()
    assert isinstance(fut.exception(), RetryableConnectionClosedError)


async def test_cleanups_own_recv_task_cancel_does_not_take_the_lost_connection_path(
    websocket_service: WebsocketService,
) -> None:
    """partial_cleanup detaches the recv task before cancelling it, so the done-callback ignores that cancel."""
    websocket_service._ws = build_fake_ws()
    websocket_service._connection_state = ConnectionState.CONNECTED
    recv_task = asyncio.create_task(asyncio.sleep(100))
    websocket_service._recv_task = recv_task
    recv_task.add_done_callback(websocket_service._handle_recv_task_done)

    await websocket_service.partial_cleanup()
    await asyncio.sleep(0)

    assert recv_task.cancelled()
    assert websocket_service.connection_state == ConnectionState.CONNECTED
