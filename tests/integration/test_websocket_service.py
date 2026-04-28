import asyncio
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aiohttp import ClientWebSocketResponse, WSMsgType
from aiohttp.client_exceptions import ClientConnectionResetError, ClientConnectorError

from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import (
    ConnectionClosedError,
    CouldNotFindHomeAssistantError,
    FailedMessageError,
    InvalidAuthError,
    RetryableConnectionClosedError,
)
from hassette.types import Topic

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


@pytest.fixture
def websocket_service(hassette_with_bus: "HassetteHarness") -> WebsocketService:
    """Create a fresh websocket service instance for each test."""
    hassette = hassette_with_bus.hassette
    return WebsocketService(hassette, parent=hassette)


def _build_fake_ws(*, is_closed: bool = False) -> ClientWebSocketResponse:
    """Return a lightweight websocket stub with adjustable state."""
    fake_ws = SimpleNamespace()
    fake_ws.closed = is_closed
    fake_ws.send_json = AsyncMock()
    fake_ws.receive_json = AsyncMock()
    fake_ws.receive = AsyncMock()
    fake_ws.close = AsyncMock()
    return cast("ClientWebSocketResponse", fake_ws)


async def test_get_next_message_id_increments(websocket_service: WebsocketService) -> None:
    """Ensure message identifiers increment sequentially."""
    first_id = websocket_service.get_next_message_id()
    second_id = websocket_service.get_next_message_id()

    assert first_id == 1, "Expected counter to start at 1"
    assert second_id == 2, "Expected counter to increment by one"


async def test_connected_reflects_websocket_state(websocket_service: WebsocketService) -> None:
    """Verify the connected property mirrors the websocket connection state."""
    assert websocket_service.connected is False

    fake_ws = _build_fake_ws(is_closed=False)
    websocket_service._ws = fake_ws
    assert websocket_service.connected is True

    fake_ws.closed = True  # pyright: ignore
    assert websocket_service.connected is False


async def test_send_json_injects_message_id_when_absent(websocket_service: WebsocketService) -> None:
    """Ensure send_json injects a message id and forwards the payload."""
    fake_ws = _build_fake_ws()
    websocket_service._ws = fake_ws

    await websocket_service.send_json(type="ping")
    payload = fake_ws.send_json.await_args.args[0]  # pyright: ignore
    assert payload["type"] == "ping", "Expected original payload to be forwarded"
    assert payload["id"] == 1, "Expected send_json to add a message id when absent"


async def test_send_json_preserves_message_id_when_present(websocket_service: WebsocketService) -> None:
    """Ensure send_json preserves a message id when present."""
    fake_ws = _build_fake_ws()
    websocket_service._ws = fake_ws

    await websocket_service.send_json(type="pong", id=41)
    second_payload = fake_ws.send_json.await_args_list[0].args[0]  # pyright: ignore
    assert second_payload["id"] == 41, "Expected explicit message id to be preserved"


async def test_send_json_requires_connection(websocket_service: WebsocketService) -> None:
    """Raise when attempting to send without an established connection."""
    with pytest.raises(ConnectionClosedError):
        await websocket_service.send_json(type="ping")


async def test_send_json_checks_connection_state(websocket_service: WebsocketService) -> None:
    """Raise when the underlying websocket reports a closed connection."""
    fake_ws = _build_fake_ws(is_closed=True)
    websocket_service._ws = fake_ws

    with pytest.raises(ConnectionClosedError):
        await websocket_service.send_json(type="ping")


async def test_send_json_propagates_reset_error(websocket_service: WebsocketService) -> None:
    """Surface ClientConnectionResetError when the websocket resets."""
    fake_ws = _build_fake_ws()
    fake_ws.send_json.side_effect = ClientConnectionResetError("boom")  # pyright: ignore

    websocket_service._ws = fake_ws

    with pytest.raises(ClientConnectionResetError):
        await websocket_service.send_json(type="ping")


async def test_send_json_wraps_generic_exceptions(websocket_service: WebsocketService) -> None:
    """Wrap unexpected errors in FailedMessageError."""
    fake_ws = _build_fake_ws()
    fake_ws.send_json.side_effect = RuntimeError("unexpected")  # pyright: ignore

    websocket_service._ws = fake_ws

    with pytest.raises(FailedMessageError):
        await websocket_service.send_json(type="ping")


async def test_send_and_wait_returns_response(websocket_service: WebsocketService) -> None:
    """Resolve send_and_wait when the websocket replies with success."""

    async def send_side_effect(**data: object) -> None:
        message_id = data["id"]
        response_future = websocket_service._response_futures[message_id]  # pyright: ignore
        response_future.set_result({"ok": True})

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    result = await websocket_service.send_and_wait(type="example")

    assert result == {"ok": True}, "Expected response to bubble up from the future"
    assert websocket_service._response_futures == {}, "Expected future mapping to be cleaned up"


async def test_send_and_wait_times_out(websocket_service: WebsocketService) -> None:
    """Raise FailedMessageError when the response future times out."""
    websocket_service.hassette.config.websocket_response_timeout_seconds = 0

    websocket_service.send_json = AsyncMock(return_value=None)

    with pytest.raises(FailedMessageError):
        await websocket_service.send_and_wait(type="no_response")

    assert websocket_service._response_futures == {}, "Expected future mapping to be cleared after timeout"


async def test_respond_if_necessary_sets_result(websocket_service: WebsocketService) -> None:
    """Fulfill waiting futures when result payloads indicate success."""
    pending_future = websocket_service.hassette.loop.create_future()
    websocket_service._response_futures[5] = pending_future

    websocket_service._respond_if_necessary({"type": "result", "id": 5, "success": True, "result": {"value": 7}})

    assert pending_future.done()
    assert pending_future.result() == {"value": 7}


async def test_respond_if_necessary_sets_exception(websocket_service: WebsocketService) -> None:
    """Attach FailedMessageError when result payloads report failure.

    Verifies the end-to-end path _respond_if_necessary → from_error_response →
    FailedMessageError.code / .original_data is wired correctly: HA's error
    envelope `code` field must flow through to the exception's `code` attribute
    so callers can do `except FailedMessageError as e: if e.code == "...": ...`.
    """
    pending_future = websocket_service.hassette.loop.create_future()
    websocket_service._response_futures[9] = pending_future

    original_message = {
        "type": "result",
        "id": 9,
        "success": False,
        "error": {"code": "invalid_format", "message": "failure"},
    }
    websocket_service._respond_if_necessary(original_message)

    assert pending_future.done()
    exception = pending_future.exception()
    assert isinstance(exception, FailedMessageError)
    assert exception.code == "invalid_format"
    assert exception.original_data == original_message


async def test_authenticate_happy_path(websocket_service: WebsocketService) -> None:
    """Authenticate when Home Assistant replies with auth_ok."""
    fake_ws = _build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_ok"}])
    websocket_service._ws = fake_ws

    await websocket_service.authenticate()

    sent_payload = fake_ws.send_json.await_args.args[0]  # pyright: ignore
    assert sent_payload == {
        "type": "auth",
        "access_token": websocket_service.hassette.config.token,
    }, "Expected authentication payload to contain the configured token"


async def test_authenticate_invalid_token(websocket_service: WebsocketService) -> None:
    """Raise InvalidAuthError when Home Assistant rejects the token."""
    fake_ws = _build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_invalid"}])
    websocket_service._ws = fake_ws

    with pytest.raises(InvalidAuthError):
        await websocket_service.authenticate()


async def test_dispatch_sends_events(monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService) -> None:
    """Forward Home Assistant events onto Hassette's event bus."""
    import hassette.core.websocket_service as websocket_module

    class DummyEvent:
        def __init__(self):
            self.topic = "dummy.topic"

    dummy_event = DummyEvent()
    mock_create = Mock(return_value=dummy_event)
    monkeypatch.setattr(websocket_module, "create_event_from_hass", mock_create)

    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock

    data = {
        "type": "event",
        "event": {"event_type": "dummy", "data": {}, "context": {}, "origin": "local", "time_fired": "now"},
    }
    await websocket_service._dispatch(data)

    mock_create.assert_called_once_with(data)
    send_event_mock.assert_awaited_once_with(dummy_event.topic, dummy_event)


async def test_dispatch_routes_result_messages(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService
) -> None:
    """Ensure result messages are passed to the responder helper."""
    respond_mock = Mock()
    monkeypatch.setattr(websocket_service, "_respond_if_necessary", respond_mock)

    await websocket_service._dispatch({"type": "result", "id": 1})

    respond_mock.assert_called_once_with({"type": "result", "id": 1})


async def test_raw_recv_dispatches_text_payload(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService
) -> None:
    """Decode text websocket frames and forward them to the dispatcher."""
    fake_ws = _build_fake_ws()
    fake_message = SimpleNamespace(type=WSMsgType.TEXT, data='{"type": "result", "id": 1}')
    fake_ws.receive = AsyncMock(return_value=fake_message)
    websocket_service._ws = fake_ws

    dispatch_mock = AsyncMock()
    monkeypatch.setattr(websocket_service, "_dispatch", dispatch_mock)

    await websocket_service._raw_recv()

    dispatch_mock.assert_awaited_once_with({"type": "result", "id": 1})


async def test_raw_recv_raises_when_socket_closed(websocket_service: WebsocketService) -> None:
    """Raise when the websocket reports it has already closed."""
    websocket_service._ws = _build_fake_ws(is_closed=True)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service._raw_recv()


async def test_raw_recv_raises_on_closing_frame(websocket_service: WebsocketService) -> None:
    """Raise when a closing frame is received."""
    fake_ws = _build_fake_ws()
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.CLOSING, data=None))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service._raw_recv()


async def test_raw_recv_raises_on_error_frame(websocket_service: WebsocketService) -> None:
    """Raise RetryableConnectionClosedError when an ERROR frame is received."""
    fake_ws = _build_fake_ws()
    socket_error = RuntimeError("socket error")
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.ERROR, data=socket_error))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError) as exc_info:
        await websocket_service._raw_recv()

    assert exc_info.value.__cause__ is socket_error


# --- Disconnect handling on recv loop failure ---


def _make_failing_recv_task(error: Exception) -> asyncio.Task:
    """Create a task that raises the given error, simulating a failed recv loop."""

    async def _fail():
        raise error

    return asyncio.ensure_future(_fail())


async def test_disconnect_event_fires_on_recv_loop_failure(websocket_service: WebsocketService) -> None:
    """Fire WEBSOCKET_DISCONNECTED when the recv loop dies unexpectedly."""
    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock

    with (
        patch.object(
            websocket_service,
            "_make_connection",
            return_value=_make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()

    topics_sent = [call.args[0] for call in send_event_mock.await_args_list]
    assert Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED in topics_sent


async def test_marked_not_ready_on_recv_loop_failure(websocket_service: WebsocketService) -> None:
    """Mark the service not-ready immediately when the recv loop fails."""
    websocket_service.mark_ready(reason="test: verify ready→not-ready transition")
    websocket_service.hassette.send_event = AsyncMock()

    with (
        patch.object(
            websocket_service,
            "_make_connection",
            return_value=_make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()

    assert not websocket_service.is_ready()


async def test_disconnect_event_failure_does_not_mask_original_error(websocket_service: WebsocketService) -> None:
    """Ensure that a broken send_event doesn't swallow the recv loop error."""
    websocket_service.hassette.send_event = AsyncMock(side_effect=RuntimeError("bus is down"))

    with (
        patch.object(
            websocket_service,
            "_make_connection",
            return_value=_make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()


# --- Decomposed method tests ---


async def test_connect_ws_sets_ws_and_authenticates(websocket_service: WebsocketService) -> None:
    """_connect_ws sets self._ws and calls authenticate."""
    fake_ws = _build_fake_ws()
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=fake_ws)

    websocket_service.authenticate = AsyncMock()

    await websocket_service._connect_ws(fake_session)

    assert websocket_service._ws is fake_ws
    websocket_service.authenticate.assert_awaited_once()


async def test_connect_ws_wraps_connection_refused(websocket_service: WebsocketService) -> None:
    """_connect_ws converts ClientConnectorError with ConnectionRefusedError cause to CouldNotFindHomeAssistantError."""
    fake_session = MagicMock()
    cause = ConnectionRefusedError("refused")
    connector_error = ClientConnectorError.__new__(ClientConnectorError)
    connector_error.__cause__ = cause

    fake_session.ws_connect = AsyncMock(side_effect=connector_error)

    with pytest.raises(CouldNotFindHomeAssistantError):
        await websocket_service._connect_ws(fake_session)


async def test_start_recv_and_subscribe_marks_ready(websocket_service: WebsocketService) -> None:
    """_start_recv_and_subscribe spawns recv, calls mark_ready, sets _connected_at, returns recv task."""
    fake_task = asyncio.ensure_future(asyncio.sleep(0))
    websocket_service.task_bucket = MagicMock()

    # Capture and discard the coroutine argument to avoid "coroutine never awaited" warning
    spawned_coros = []

    def _spawn_side_effect(coro, *, name=None):  # noqa: ARG001
        spawned_coros.append(coro)
        return fake_task

    websocket_service.task_bucket.spawn = Mock(side_effect=_spawn_side_effect)
    websocket_service._send_connection_established_event = AsyncMock()
    websocket_service._subscribe_events = AsyncMock(return_value=42)
    websocket_service.mark_ready = Mock()

    result = await websocket_service._start_recv_and_subscribe()

    # Close any coroutines captured to suppress ResourceWarning
    for coro in spawned_coros:
        coro.close()

    assert result is fake_task
    websocket_service.mark_ready.assert_called_once()
    assert websocket_service._connected_at is not None
    assert websocket_service._subscription_ids == {42}
    # Clean up the task
    fake_task.cancel()


async def test_partial_cleanup_cancels_recv_and_closes_ws(websocket_service: WebsocketService) -> None:
    """_partial_cleanup cancels recv task, closes ws, clears futures and subscription ids."""
    fake_ws = _build_fake_ws()
    fake_recv_task = asyncio.ensure_future(asyncio.sleep(100))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = fake_recv_task
    websocket_service._subscription_ids = {1, 2}

    # Seed a pending future
    fut = websocket_service.hassette.loop.create_future()
    websocket_service._response_futures[99] = fut

    await websocket_service._partial_cleanup()

    assert websocket_service._ws is None
    assert websocket_service._recv_task is None
    assert websocket_service._subscription_ids == set()
    assert websocket_service._response_futures == {}
    assert fut.done()
    assert isinstance(fut.exception(), RetryableConnectionClosedError)


async def test_partial_cleanup_preserves_session(websocket_service: WebsocketService) -> None:
    """_partial_cleanup must NOT clear self._session."""
    fake_session = MagicMock()
    websocket_service._session = fake_session
    websocket_service._ws = _build_fake_ws()
    websocket_service._recv_task = asyncio.ensure_future(asyncio.sleep(0))

    await websocket_service._partial_cleanup()

    assert websocket_service._session is fake_session


async def test_partial_cleanup_suppresses_errors(websocket_service: WebsocketService) -> None:
    """_partial_cleanup must not propagate any exceptions."""
    fake_ws = _build_fake_ws()
    fake_ws.close = AsyncMock(side_effect=RuntimeError("close failed"))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = None

    # Should not raise
    await websocket_service._partial_cleanup()


async def test_partial_cleanup_timeout_on_gather(websocket_service: WebsocketService) -> None:
    """_partial_cleanup completes within ~2s even when recv task is non-cancellable."""

    async def _never_ends():
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:
            # simulate a task that ignores cancellation
            await asyncio.sleep(1000)

    stuck_task = asyncio.ensure_future(_never_ends())
    websocket_service._recv_task = stuck_task
    websocket_service._ws = _build_fake_ws()

    started = time.monotonic()
    try:
        await websocket_service._partial_cleanup()
        elapsed = time.monotonic() - started
        assert elapsed < 4.0, f"_partial_cleanup took too long: {elapsed:.2f}s"
    finally:
        stuck_task.cancel()
        await asyncio.gather(stuck_task, return_exceptions=True)
