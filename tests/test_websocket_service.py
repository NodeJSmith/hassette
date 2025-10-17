from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientWebSocketResponse, WSMsgType
from aiohttp.client_exceptions import ClientConnectionResetError

from hassette.core.services.websocket_service import _WebsocketService
from hassette.exceptions import (
    ConnectionClosedError,
    FailedMessageError,
    InvalidAuthError,
    ResourceNotReadyError,
    RetryableConnectionClosedError,
)

if TYPE_CHECKING:
    from hassette.core.core import Hassette


@pytest.fixture
def websocket_service(hassette_with_bus: "Hassette") -> _WebsocketService:
    """Create a fresh websocket service instance for each test."""
    return _WebsocketService.create(hassette_with_bus)


def _build_fake_ws(*, is_closed: bool = False) -> ClientWebSocketResponse:
    """Return a lightweight websocket stub with adjustable state."""
    fake_ws = SimpleNamespace()
    fake_ws._conn = SimpleNamespace(closed=is_closed)
    fake_ws.closed = is_closed
    fake_ws.send_json = AsyncMock()
    fake_ws.receive_json = AsyncMock()
    fake_ws.receive = AsyncMock()
    fake_ws.close = AsyncMock()
    return cast("ClientWebSocketResponse", fake_ws)


async def test_get_next_message_id_increments(websocket_service: _WebsocketService) -> None:
    """Ensure message identifiers increment sequentially."""
    first_id = websocket_service.get_next_message_id()
    second_id = websocket_service.get_next_message_id()

    assert first_id == 1, "Expected counter to start at 1"
    assert second_id == 2, "Expected counter to increment by one"


async def test_connected_reflects_websocket_state(websocket_service: _WebsocketService) -> None:
    """Verify the connected property mirrors the websocket connection state."""
    assert websocket_service.connected is False

    fake_ws = _build_fake_ws(is_closed=False)
    websocket_service._ws = fake_ws
    assert websocket_service.connected is True

    fake_ws._conn.closed = True  # pyright: ignore
    assert websocket_service.connected is False


async def test_send_json_injects_message_id(websocket_service: _WebsocketService) -> None:
    """Ensure send_json injects a message id and forwards the payload."""
    fake_ws = _build_fake_ws()
    websocket_service._ws = fake_ws
    websocket_service.mark_ready("test ready")

    await websocket_service.send_json(type="ping")
    payload = fake_ws.send_json.await_args.args[0]  # pyright: ignore
    assert payload["type"] == "ping", "Expected original payload to be forwarded"
    assert payload["id"] == 1, "Expected send_json to add a message id when absent"

    await websocket_service.send_json(type="pong", id=41)
    second_payload = fake_ws.send_json.await_args_list[1].args[0]  # pyright: ignore
    assert second_payload["id"] == 41, "Expected explicit message id to be preserved"


async def test_send_json_requires_readiness(websocket_service: _WebsocketService) -> None:
    """Raise when attempting to send before the service is ready."""
    websocket_service._ws = _build_fake_ws()

    with pytest.raises(ResourceNotReadyError):
        await websocket_service.send_json(type="ping")


async def test_send_json_checks_connection_state(websocket_service: _WebsocketService) -> None:
    """Raise when the underlying websocket reports a closed connection."""
    fake_ws = _build_fake_ws(is_closed=True)
    websocket_service._ws = fake_ws
    websocket_service.mark_ready("ready for connection check")

    with pytest.raises(ConnectionClosedError):
        await websocket_service.send_json(type="ping")


async def test_send_json_propagates_reset_error(websocket_service: _WebsocketService) -> None:
    """Surface ClientConnectionResetError when the websocket resets."""
    fake_ws = _build_fake_ws()
    fake_ws.send_json.side_effect = ClientConnectionResetError("boom")  # pyright: ignore

    websocket_service._ws = fake_ws
    websocket_service.mark_ready("ready for reset test")

    with pytest.raises(ClientConnectionResetError):
        await websocket_service.send_json(type="ping")


async def test_send_json_wraps_generic_exceptions(websocket_service: _WebsocketService) -> None:
    """Wrap unexpected errors in FailedMessageError."""
    fake_ws = _build_fake_ws()
    fake_ws.send_json.side_effect = RuntimeError("unexpected")  # pyright: ignore

    websocket_service._ws = fake_ws
    websocket_service.mark_ready("ready for error test")

    with pytest.raises(FailedMessageError):
        await websocket_service.send_json(type="ping")


async def test_send_and_wait_returns_response(websocket_service: _WebsocketService) -> None:
    """Resolve send_and_wait when the websocket replies with success."""
    websocket_service.mark_ready("ready for send_and_wait")

    async def send_side_effect(**data: object) -> None:
        message_id = data["id"]
        response_future = websocket_service._response_futures[message_id]  # pyright: ignore
        response_future.set_result({"ok": True})

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    result = await websocket_service.send_and_wait(type="example")

    assert result == {"ok": True}, "Expected response to bubble up from the future"
    assert websocket_service._response_futures == {}, "Expected future mapping to be cleaned up"


async def test_send_and_wait_times_out(websocket_service: _WebsocketService, hassette_with_bus: "Hassette") -> None:
    """Raise FailedMessageError when the response future times out."""
    hassette_with_bus.config.websocket_response_timeout_seconds = 0
    websocket_service.mark_ready("ready for timeout test")
    websocket_service.send_json = AsyncMock(return_value=None)

    with pytest.raises(FailedMessageError):
        await websocket_service.send_and_wait(type="no_response")

    assert websocket_service._response_futures == {}, "Expected future mapping to be cleared after timeout"


async def test_respond_if_necessary_sets_result(
    websocket_service: _WebsocketService, hassette_with_bus: "Hassette"
) -> None:
    """Fulfill waiting futures when result payloads indicate success."""
    pending_future = hassette_with_bus.loop.create_future()
    websocket_service._response_futures[5] = pending_future

    websocket_service._respond_if_necessary({"type": "result", "id": 5, "success": True, "result": {"value": 7}})

    assert pending_future.done()
    assert pending_future.result() == {"value": 7}


async def test_respond_if_necessary_sets_exception(
    websocket_service: _WebsocketService, hassette_with_bus: "Hassette"
) -> None:
    """Attach FailedMessageError when result payloads report failure."""
    pending_future = hassette_with_bus.loop.create_future()
    websocket_service._response_futures[9] = pending_future

    websocket_service._respond_if_necessary(
        {"type": "result", "id": 9, "success": False, "error": {"message": "failure"}}
    )

    assert pending_future.done()
    exception = pending_future.exception()
    assert isinstance(exception, FailedMessageError)


async def test_authenticate_happy_path(websocket_service: _WebsocketService, hassette_with_bus: "Hassette") -> None:
    """Authenticate when Home Assistant replies with auth_ok."""
    fake_ws = _build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_ok"}])
    websocket_service._ws = fake_ws

    await websocket_service.authenticate()

    sent_payload = fake_ws.send_json.await_args.args[0]  # pyright: ignore
    assert sent_payload == {
        "type": "auth",
        "access_token": hassette_with_bus.config.token.get_secret_value(),
    }, "Expected authentication payload to contain the configured token"


async def test_authenticate_invalid_token(websocket_service: _WebsocketService) -> None:
    """Raise InvalidAuthError when Home Assistant rejects the token."""
    fake_ws = _build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_invalid"}])
    websocket_service._ws = fake_ws

    with pytest.raises(InvalidAuthError):
        await websocket_service.authenticate()


async def test_dispatch_sends_events(monkeypatch: pytest.MonkeyPatch, websocket_service: _WebsocketService) -> None:
    """Forward Home Assistant events onto Hassette's event bus."""
    import hassette.core.services.websocket_service as websocket_module

    class DummyEvent:
        def __init__(self):
            self.topic = "dummy.topic"

    dummy_event = DummyEvent()
    mock_create = Mock(return_value=dummy_event)
    monkeypatch.setattr(websocket_module, "create_event_from_hass", mock_create)

    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock  # type: ignore[assignment]

    data = {
        "type": "event",
        "event": {"event_type": "dummy", "data": {}, "context": {}, "origin": "local", "time_fired": "now"},
    }
    await websocket_service._dispatch(data)

    mock_create.assert_called_once_with(data)
    send_event_mock.assert_awaited_once_with(dummy_event.topic, dummy_event)


async def test_dispatch_routes_result_messages(
    monkeypatch: pytest.MonkeyPatch, websocket_service: _WebsocketService
) -> None:
    """Ensure result messages are passed to the responder helper."""
    respond_mock = Mock()
    monkeypatch.setattr(websocket_service, "_respond_if_necessary", respond_mock)

    await websocket_service._dispatch({"type": "result", "id": 1})

    respond_mock.assert_called_once_with({"type": "result", "id": 1})


async def test_raw_recv_dispatches_text_payload(
    monkeypatch: pytest.MonkeyPatch, websocket_service: _WebsocketService
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


async def test_raw_recv_raises_when_socket_closed(websocket_service: _WebsocketService) -> None:
    """Raise when the websocket reports it has already closed."""
    websocket_service._ws = _build_fake_ws(is_closed=True)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service._raw_recv()


async def test_raw_recv_raises_on_closing_frame(websocket_service: _WebsocketService) -> None:
    """Raise when a closing frame is received."""
    fake_ws = _build_fake_ws()
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.CLOSING, data=None))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service._raw_recv()
