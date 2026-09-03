"""Connection/auth tests for WebsocketService.

Covers message-id/connection-state helpers, authenticate(), raw_recv(), connect_ws(),
and start_recv_and_subscribe(). Complements test_dispatch.py (send/dispatch), test_reconnect.py
(disconnect/reconnect-retry), and test_subscribe_events_retry.py.
"""

import asyncio
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aiohttp import WSMsgType
from aiohttp.client_exceptions import ClientConnectorError

from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import (
    CouldNotFindHomeAssistantError,
    FailedMessageError,
    InvalidAuthError,
    RetryableConnectionClosedError,
)
from hassette.testing import EventCapture
from hassette.testing._ws_mocks import build_fake_ws, make_task_bucket_spawn_stub
from hassette.types import Topic
from hassette.types.enums import ConnectionState


async def test_get_next_message_id_increments(websocket_service: WebsocketService) -> None:
    """Ensure message identifiers increment sequentially."""
    first_id = websocket_service.get_next_message_id()
    second_id = websocket_service.get_next_message_id()

    assert first_id == 1, "Expected counter to start at 1"
    assert second_id == 2, "Expected counter to increment by one"


async def test_is_connected_reflects_websocket_state(websocket_service: WebsocketService) -> None:
    """Verify the is_connected property mirrors the connection state machine."""
    assert websocket_service.is_connected is False

    # CONNECTED state → connected
    websocket_service._connection_state = ConnectionState.CONNECTED
    assert websocket_service.is_connected is True

    # CONNECTING state → not connected
    websocket_service._connection_state = ConnectionState.CONNECTING
    assert websocket_service.is_connected is False

    # DISCONNECTED state → not connected
    websocket_service._connection_state = ConnectionState.DISCONNECTED
    assert websocket_service.is_connected is False


async def test_authenticate_happy_path(websocket_service: WebsocketService) -> None:
    """Authenticate when Home Assistant replies with auth_ok."""
    fake_ws = build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_ok"}])
    websocket_service._ws = fake_ws

    await websocket_service.authenticate()

    sent_payload = fake_ws.send_json.await_args.args[0]
    assert sent_payload == {
        "type": "auth",
        "access_token": websocket_service.hassette.config.token.get_secret_value(),
    }, "Expected authentication payload to contain the configured token"


async def test_authenticate_invalid_token(websocket_service: WebsocketService) -> None:
    """Raise InvalidAuthError when Home Assistant rejects the token."""
    fake_ws = build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_invalid"}])
    websocket_service._ws = fake_ws

    with pytest.raises(InvalidAuthError):
        await websocket_service.authenticate()


async def test_raw_recv_dispatches_text_payload(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService
) -> None:
    """Decode text websocket frames and forward them to the dispatcher."""
    fake_ws = build_fake_ws()
    fake_message = SimpleNamespace(type=WSMsgType.TEXT, data='{"type": "result", "id": 1}')
    fake_ws.receive = AsyncMock(return_value=fake_message)
    websocket_service._ws = fake_ws

    dispatch_mock = AsyncMock()
    monkeypatch.setattr(websocket_service, "dispatch", dispatch_mock)

    await websocket_service.raw_recv()

    dispatch_mock.assert_awaited_once_with({"type": "result", "id": 1})


async def test_raw_recv_raises_when_socket_closed(websocket_service: WebsocketService) -> None:
    """Raise when the websocket reports it has already closed."""
    websocket_service._ws = build_fake_ws(is_closed=True)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.raw_recv()


async def test_raw_recv_raises_on_closing_frame(websocket_service: WebsocketService) -> None:
    """Raise when a closing frame is received."""
    fake_ws = build_fake_ws()
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.CLOSING, data=None))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.raw_recv()


async def test_raw_recv_raises_on_error_frame(websocket_service: WebsocketService) -> None:
    """Raise RetryableConnectionClosedError when an ERROR frame is received."""
    fake_ws = build_fake_ws()
    socket_error = RuntimeError("socket error")
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.ERROR, data=socket_error))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError) as exc_info:
        await websocket_service.raw_recv()

    assert exc_info.value.__cause__ is socket_error


async def test_connect_ws_sets_ws_and_authenticates(websocket_service: WebsocketService) -> None:
    """connect_ws sets self._ws and calls authenticate."""
    fake_ws = build_fake_ws()
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=fake_ws)

    websocket_service.authenticate = AsyncMock()

    await websocket_service.connect_ws(fake_session)

    assert websocket_service._ws is fake_ws
    websocket_service.authenticate.assert_awaited_once()


async def test_connect_ws_wraps_connection_refused(websocket_service: WebsocketService) -> None:
    """connect_ws converts ClientConnectorError with ConnectionRefusedError cause to CouldNotFindHomeAssistantError."""
    fake_session = MagicMock()
    cause = ConnectionRefusedError("refused")
    connector_error = ClientConnectorError.__new__(ClientConnectorError)
    connector_error.__cause__ = cause

    fake_session.ws_connect = AsyncMock(side_effect=connector_error)

    with pytest.raises(CouldNotFindHomeAssistantError):
        await websocket_service.connect_ws(fake_session)


async def test_start_recv_and_subscribe_marks_ready(websocket_service: WebsocketService) -> None:
    """start_recv_and_subscribe spawns recv, calls mark_ready, sets _connected_at, returns recv task.

    Companion: test_websocket_readiness_events.py::test_mark_ready_after_connect_emits_event asserts
    the bus-event side (ready=True emitted) of the same method.
    """
    fake_task = asyncio.create_task(asyncio.sleep(0))
    websocket_service.task_bucket = MagicMock()

    # Capture and discard the coroutine argument to avoid "coroutine never awaited" warning
    spawned_coros: list[Coroutine[Any, Any, Any]] = []

    def _spawn_side_effect(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task[None]:  # noqa: ARG001
        spawned_coros.append(coro)
        return fake_task

    websocket_service.task_bucket.spawn = Mock(side_effect=_spawn_side_effect)
    websocket_service.send_connection_established_event = AsyncMock()
    websocket_service.subscribe_events = AsyncMock(return_value=42)
    # Stub _emit_readiness_event: this test focuses on mark_ready/subscription behavior;
    # readiness event emission is covered by test_websocket_readiness_events.py.
    websocket_service._emit_readiness_event = AsyncMock()

    # start_recv_and_subscribe calls set_connection_state(CONNECTED).
    # DISCONNECTED → CONNECTED is invalid; the real flow goes through CONNECTING first
    # (set by serve() before calling make_connection). Set CONNECTING as the pre-condition.
    websocket_service._connection_state = ConnectionState.CONNECTING

    with patch("hassette.core.websocket_service.mark_ready") as mock_mark_ready:
        result = await websocket_service.start_recv_and_subscribe()

    # Close any coroutines captured to suppress ResourceWarning
    for coro in spawned_coros:
        coro.close()

    assert result is fake_task
    mock_mark_ready.assert_called_once_with(
        websocket_service, reason="WebSocket connected, authenticated, and subscribed"
    )
    assert websocket_service._connected_at is not None
    assert websocket_service._subscription_ids == {42}
    assert websocket_service.connection_state == ConnectionState.CONNECTED
    assert websocket_service.get_connected_generation() == 1
    # Clean up the task
    fake_task.cancel()


async def test_start_recv_and_subscribe_emits_connected_only_after_subscription_succeeds(
    websocket_service: WebsocketService,
) -> None:
    """External readiness and the public connected signal happen after subscription confirmation."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    spawned_coros, spawn_stub = make_task_bucket_spawn_stub()
    websocket_service.task_bucket = MagicMock()
    websocket_service.task_bucket.spawn = spawn_stub
    websocket_service._emit_readiness_event = AsyncMock()
    websocket_service._connection_state = ConnectionState.CONNECTING

    async def fake_subscribe_events() -> int:
        assert websocket_service.is_connected is False
        assert websocket_service.has_ever_connected is False
        assert websocket_service._connected_event.is_set() is False
        return 99

    websocket_service.subscribe_events = AsyncMock(side_effect=fake_subscribe_events)

    result_task = await websocket_service.start_recv_and_subscribe()

    assert websocket_service.is_connected is True
    assert websocket_service.has_ever_connected is True
    assert websocket_service._connected_event.is_set() is True
    assert websocket_service.get_connected_generation() == 1
    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)
    for coro in spawned_coros:
        coro.close()
    result_task.cancel()


async def test_subscription_failure_before_external_readiness_leaves_history_false_and_emits_no_public_signal(
    websocket_service: WebsocketService,
) -> None:
    """A failed pre-readiness subscription attempt does not publish connected/disconnected signals."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    spawned_coros, spawn_stub = make_task_bucket_spawn_stub()
    websocket_service.task_bucket = MagicMock()
    websocket_service.task_bucket.spawn = spawn_stub
    websocket_service._connection_state = ConnectionState.CONNECTING
    websocket_service.subscribe_events = AsyncMock(side_effect=FailedMessageError("subscribe failed"))

    with pytest.raises(FailedMessageError, match="subscribe failed"):
        await websocket_service.start_recv_and_subscribe()

    assert websocket_service.has_ever_connected is False
    assert websocket_service.is_connected is False
    assert websocket_service._connected_event.is_set() is False
    assert websocket_service.get_connected_generation() is None
    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED) == []
    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED) == []
    for coro in spawned_coros:
        coro.close()
    websocket_service._recv_task.cancel()


async def test_on_initialize_marks_ready_unconditionally(websocket_service: WebsocketService) -> None:
    """on_initialize() marks the service lifecycle-ready regardless of HA reachability.

    Every other test in this file simulates readiness via a direct mark_ready() call;
    this test exercises the actual method the task introduced so a regression that drops
    or conditions the mark_ready() call inside on_initialize() is caught here.
    """
    assert not websocket_service.is_ready()

    await websocket_service.on_initialize()

    assert websocket_service.is_ready()


async def test_raw_recv_passes_close_code(websocket_service: WebsocketService) -> None:
    """raw_recv passes close_code from _ws.close_code when raising RetryableConnectionClosedError."""
    fake_ws = build_fake_ws()
    fake_ws.close_code = 1001  # pyright: ignore[reportAttributeAccessIssue]
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.CLOSE, data=None))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError) as exc_info:
        await websocket_service.raw_recv()

    assert exc_info.value.close_code == 1001, f"Expected close_code=1001, got {exc_info.value.close_code}"
