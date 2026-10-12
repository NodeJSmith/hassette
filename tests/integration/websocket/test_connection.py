"""Connection/auth tests for WebsocketService.

Covers message-id/connection-state helpers, authenticate(), raw_recv(), connect_ws(),
start_recv_and_subscribe(), and mark_connected(). Complements test_dispatch.py (send/dispatch),
test_reconnect.py (partial_cleanup), test_reconnect_loop.py (serve()'s reconnect loop), and
test_subscribe_events_retry.py.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import WSMsgType
from aiohttp.client_exceptions import ClientConnectorError

from hassette.core.websocket_reconnect import CONNECTED_REASON, WS_MAX_MSG_SIZE
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import FailedMessageError, InvalidAuthError, RetryableConnectionClosedError
from hassette.testing import EventCapture
from hassette.testing._ws_mocks import build_fake_ws, make_task_bucket_spawn_stub, run_connect_sequence
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


async def test_connect_ws_raises_refusal_unchanged_and_sets_size_limit(websocket_service: WebsocketService) -> None:
    """connect_ws lets a refusal reach serve()'s loop as-is and caps incoming messages at WS_MAX_MSG_SIZE."""
    fake_session = MagicMock()
    connector_error = ClientConnectorError.__new__(ClientConnectorError)
    connector_error.__cause__ = ConnectionRefusedError("refused")
    fake_session.ws_connect = AsyncMock(side_effect=connector_error)

    with pytest.raises(ClientConnectorError):
        await websocket_service.connect_ws(fake_session)

    assert fake_session.ws_connect.await_args.kwargs["max_msg_size"] == WS_MAX_MSG_SIZE


async def test_start_recv_and_subscribe_subscribes_without_advertising_connected(
    websocket_service: WebsocketService,
) -> None:
    """start_recv_and_subscribe opens the send gate and subscribes; CONNECTED waits for the RUNNING gate."""
    spawned_coros, spawn_stub = make_task_bucket_spawn_stub()
    websocket_service.task_bucket = MagicMock()
    websocket_service.task_bucket.spawn = spawn_stub
    websocket_service.subscribe_events = AsyncMock(return_value=42)
    websocket_service._connection_state = ConnectionState.CONNECTING

    result = await websocket_service.start_recv_and_subscribe()

    for coro in spawned_coros:
        coro.close()
    assert result is websocket_service._recv_task
    assert websocket_service._subscription_ids == {42}
    assert websocket_service._send_ready_event.is_set()
    assert websocket_service.connection_state == ConnectionState.CONNECTING
    assert websocket_service.get_connected_generation() is None


async def test_mark_connected_reports_connected_and_publishes_connected(websocket_service: WebsocketService) -> None:
    """mark_connected advertises external readiness: CONNECTED, generation 1, the connected reason, the public event.

    Lifecycle readiness is untouched (it is set once at startup). Companion:
    test_websocket_readiness_events.py::test_connect_emits_one_status_event_with_the_connected_reason
    asserts the bus-event side of the same method.
    """
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    websocket_service._emit_readiness_event = AsyncMock()
    websocket_service._connection_state = ConnectionState.CONNECTING
    recv_task = asyncio.create_task(asyncio.sleep(10))

    await websocket_service.mark_connected(recv_task)

    recv_task.cancel()
    assert websocket_service._ready_reason == CONNECTED_REASON
    assert not websocket_service.ready_event.is_set()
    assert websocket_service._connected_at is not None
    assert websocket_service.is_connected is True
    assert websocket_service.has_ever_connected is True
    assert websocket_service._connected_event.is_set() is True
    assert websocket_service.get_connected_generation() == 1
    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)


async def test_recv_task_dying_during_the_status_report_announces_nothing(
    websocket_service: WebsocketService,
) -> None:
    """If the recv task dies while mark_connected awaits the readiness emit, no observer or app hears CONNECTED."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    websocket_service._connection_state = ConnectionState.CONNECTING
    observed: list[int] = []

    async def observer(generation: int) -> None:
        observed.append(generation)

    websocket_service.connected_observers.add(observer)
    recv_task = asyncio.create_task(asyncio.sleep(10))

    async def kill_recv_task() -> None:
        recv_task.cancel()
        await asyncio.gather(recv_task, return_exceptions=True)

    websocket_service._emit_readiness_event = kill_recv_task  # pyright: ignore[reportAttributeAccessIssue]

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.mark_connected(recv_task)

    assert observed == []
    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED) == []
    assert websocket_service._connected_signal_active is False


def started_envelope() -> dict:
    return {"id": 1, "type": "event", "event": {"event_type": "homeassistant_started", "data": {}, "origin": "LOCAL"}}


async def test_started_event_held_by_a_failed_attempt_is_not_dispatched_on_the_next_connection(
    websocket_service: WebsocketService,
) -> None:
    """A homeassistant_started held before CONNECTED belongs to its attempt; a fresh attempt starts without it."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    spawned_coros, spawn_stub = make_task_bucket_spawn_stub()
    websocket_service.task_bucket = MagicMock()
    websocket_service.task_bucket.spawn = spawn_stub
    websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service._connection_state = ConnectionState.CONNECTING

    await websocket_service.dispatch_hass_event(started_envelope())  # pyright: ignore[reportArgumentType]
    assert websocket_service._core_started_event.is_set()

    await run_connect_sequence(websocket_service, spawned_coros)

    assert not [topic for topic in capture.topics if str(topic).endswith("homeassistant_started")]


async def test_mark_connected_refuses_a_connection_whose_recv_task_already_died(
    websocket_service: WebsocketService,
) -> None:
    """A drop between the RUNNING gate and mark_connected surfaces as that drop, never as CONNECTED."""
    websocket_service._connection_state = ConnectionState.CONNECTING

    async def dropped() -> None:
        raise RetryableConnectionClosedError("peer gone", close_code=1001)

    recv_task = asyncio.create_task(dropped())
    await asyncio.gather(recv_task, return_exceptions=True)

    with pytest.raises(RetryableConnectionClosedError, match="peer gone"):
        await websocket_service.mark_connected(recv_task)

    assert websocket_service.has_ever_connected is False
    assert websocket_service.connection_state == ConnectionState.CONNECTING


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
    this test calls on_initialize() itself, so a regression that drops
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
