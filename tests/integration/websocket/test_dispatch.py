"""send_json/send_and_wait/dispatch tests for WebsocketService.

Complements test_connection.py (connection/auth), test_reconnect.py (partial_cleanup and the
connection-lost event), test_reconnect_loop.py (serve()'s reconnect loop), and test_subscribe_events_retry.py.
"""

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from aiohttp import ClientWebSocketResponse
from aiohttp.client_exceptions import ClientConnectionResetError

import hassette.core.websocket_io as websocket_io_module
from hassette.api.api import Api
from hassette.core.websocket_service import WebsocketService
from hassette.events import RawStateChangeEvent
from hassette.events.metadata import get_websocket_generation
from hassette.exceptions import ConnectionClosedError, FailedMessageError
from hassette.testing._ws_mocks import build_fake_ws, mark_websocket_service_connected
from hassette.types.enums import ConnectionState

if TYPE_CHECKING:
    from hassette.core.api_resource import ApiResource


def last_sent_payload(fake_ws: ClientWebSocketResponse) -> dict[str, Any]:
    """Return the payload of the fake socket's most recent ``send_json`` call."""
    send_call = cast("AsyncMock", fake_ws.send_json).await_args
    assert send_call is not None
    return send_call.args[0]


async def test_send_json_injects_message_id_when_absent(websocket_service: WebsocketService) -> None:
    """Ensure send_json injects a message id and forwards the payload."""
    fake_ws = build_fake_ws()
    websocket_service._ws = fake_ws
    mark_websocket_service_connected(websocket_service, reason="test connected")

    await websocket_service.send_json(type="ping")
    payload = last_sent_payload(fake_ws)
    assert payload["type"] == "ping", "Expected original payload to be forwarded"
    assert payload["id"] == 1, "Expected send_json to add a message id when absent"


async def test_send_json_preserves_message_id_when_present(websocket_service: WebsocketService) -> None:
    """Ensure send_json preserves a message id when present."""
    fake_ws = build_fake_ws()
    websocket_service._ws = fake_ws
    mark_websocket_service_connected(websocket_service, reason="test connected")

    await websocket_service.send_json(type="pong", id=41)
    second_payload = cast("AsyncMock", fake_ws.send_json).await_args_list[0].args[0]
    assert second_payload["id"] == 41, "Expected explicit message id to be preserved"


async def test_send_json_allows_setup_send_before_external_readiness(
    websocket_service: WebsocketService,
) -> None:
    """send_json is gated on the send gate only, so setup traffic flows before CONNECTED is advertised."""
    fake_ws = build_fake_ws()
    websocket_service._ws = fake_ws
    websocket_service._connection_state = ConnectionState.CONNECTING
    websocket_service._send_ready_event.set()

    await websocket_service.send_json(type="subscribe_events")

    payload = last_sent_payload(fake_ws)
    assert payload["type"] == "subscribe_events"
    assert payload["id"] == 1


async def test_send_json_requires_connection(websocket_service: WebsocketService) -> None:
    """Raise when attempting to send without an established connection (DISCONNECTED state)."""
    with pytest.raises(ConnectionClosedError):
        await websocket_service.send_json(type="ping")


async def test_send_json_checks_connection_state(websocket_service: WebsocketService) -> None:
    """Service-level send_json passes the send gate during setup, even when the socket reports closed."""
    fake_ws = build_fake_ws(is_closed=True)
    websocket_service._ws = fake_ws
    websocket_service._connection_state = ConnectionState.CONNECTING
    websocket_service._send_ready_event.set()

    await websocket_service.send_json(type="ping")

    assert cast("AsyncMock", fake_ws.send_json).await_count == 1


async def test_api_ws_send_json_checks_external_readiness() -> None:
    """App-facing fire-and-forget sends remain gated on external readiness."""
    api = Api.__new__(Api)
    ws_conn = MagicMock()
    ws_conn.is_connected = False
    ws_conn.send_json = AsyncMock()
    api._api_service = cast("ApiResource", SimpleNamespace(ws_conn=ws_conn))

    with pytest.raises(ConnectionClosedError):
        await api.ws_send_json(type="ping")

    ws_conn.send_json.assert_not_awaited()


async def test_api_ws_send_and_wait_checks_external_readiness() -> None:
    """App-facing request/reply sends remain gated on external readiness."""
    api = Api.__new__(Api)
    ws_conn = MagicMock()
    ws_conn.is_connected = False
    ws_conn.send_and_wait = AsyncMock()
    api._api_service = cast("ApiResource", SimpleNamespace(ws_conn=ws_conn))

    with pytest.raises(ConnectionClosedError):
        await api.ws_send_and_wait(type="ping")

    ws_conn.send_and_wait.assert_not_awaited()


async def test_send_json_propagates_reset_error(websocket_service: WebsocketService) -> None:
    """Surface ClientConnectionResetError when the websocket resets."""
    fake_ws = build_fake_ws()
    cast("AsyncMock", fake_ws.send_json).side_effect = ClientConnectionResetError("boom")

    websocket_service._ws = fake_ws
    mark_websocket_service_connected(websocket_service, reason="test connected")

    with pytest.raises(ClientConnectionResetError):
        await websocket_service.send_json(type="ping")


async def test_send_json_wraps_generic_exceptions(websocket_service: WebsocketService) -> None:
    """Wrap unexpected errors in FailedMessageError."""
    fake_ws = build_fake_ws()
    cast("AsyncMock", fake_ws.send_json).side_effect = RuntimeError("unexpected")

    websocket_service._ws = fake_ws
    mark_websocket_service_connected(websocket_service, reason="test connected")

    with pytest.raises(FailedMessageError):
        await websocket_service.send_json(type="ping")


async def test_send_and_wait_returns_response(websocket_service: WebsocketService) -> None:
    """Resolve send_and_wait when the websocket replies with success."""

    async def send_side_effect(**data: Any) -> None:
        msg_id = data["id"]
        response_future = websocket_service._pending.entries[msg_id].future
        response_future.set_result({"ok": True})

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    result = await websocket_service.send_and_wait(type="example")

    assert result == {"ok": True}, "Expected response to bubble up from the future"
    assert websocket_service._pending.entries == {}, "Expected future mapping to be cleaned up"


async def test_send_and_wait_times_out(websocket_service: WebsocketService, monkeypatch) -> None:
    """Raise FailedMessageError after exhausting retries on timeout."""
    monkeypatch.setattr(websocket_io_module, "MAX_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(websocket_io_module, "RESPONSE_TIMEOUT_SECONDS", 0)

    websocket_service.send_json = AsyncMock(return_value=None)

    with pytest.raises(FailedMessageError):
        await websocket_service.send_and_wait(type="no_response")

    assert websocket_service._pending.entries == {}, "Expected future mapping to be cleared after timeout"


async def test_send_and_wait_retries_on_timeout(
    websocket_service: WebsocketService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """send_and_wait retries transient timeouts and succeeds when HA responds."""
    monkeypatch.setattr(websocket_io_module, "RESPONSE_TIMEOUT_SECONDS", 0)
    call_count = 0

    async def send_side_effect(**data: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            monkeypatch.setattr(websocket_io_module, "RESPONSE_TIMEOUT_SECONDS", 5)
            msg_id = data["id"]
            fut = websocket_service._pending.entries[msg_id].future
            fut.set_result({"ok": True})

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    result = await websocket_service.send_and_wait(type="get_states")

    assert result == {"ok": True}
    assert call_count == 2


async def test_send_and_wait_no_retry_on_ha_error(websocket_service: WebsocketService) -> None:
    """send_and_wait does not retry HA application errors (non-None code)."""

    async def send_side_effect(**data: Any) -> None:
        msg_id = data["id"]
        fut = websocket_service._pending.entries[msg_id].future
        fut.set_exception(FailedMessageError("not found", code="not_found"))

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    with pytest.raises(FailedMessageError, match="not found"):
        await websocket_service.send_and_wait(type="get_entity_source")

    assert websocket_service.send_json.call_count == 1


async def test_respond_if_necessary_sets_result(websocket_service: WebsocketService) -> None:
    """Fulfill waiting futures when result payloads indicate success."""
    pending_future = websocket_service.hassette.loop.create_future()
    websocket_service._pending.register(5, pending_future)

    websocket_service.respond_if_necessary({"type": "result", "id": 5, "success": True, "result": {"value": 7}})

    assert pending_future.done()
    assert pending_future.result() == {"value": 7}


async def test_respond_if_necessary_sets_exception(websocket_service: WebsocketService) -> None:
    """Attach FailedMessageError when result payloads report failure.

    Verifies the end-to-end path respond_if_necessary → from_error_response →
    FailedMessageError.code / .original_data is wired correctly: HA's error
    envelope `code` field must flow through to the exception's `code` attribute
    so callers can do `except FailedMessageError as e: if e.code == "...": ...`.
    """
    pending_future = websocket_service.hassette.loop.create_future()
    websocket_service._pending.register(9, pending_future)

    original_message = {
        "type": "result",
        "id": 9,
        "success": False,
        "error": {"code": "invalid_format", "message": "failure"},
    }
    websocket_service.respond_if_necessary(original_message)

    assert pending_future.done()
    exception = pending_future.exception()
    assert isinstance(exception, FailedMessageError)
    assert exception.code == "invalid_format"
    assert exception.original_data == original_message


async def test_dispatch_sends_events(monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService) -> None:
    """Forward Home Assistant events onto Hassette's event bus."""

    class DummyEvent:
        def __init__(self):
            self.topic = "dummy.topic"

    dummy_event = DummyEvent()
    mock_create = Mock(return_value=dummy_event)
    monkeypatch.setattr(websocket_io_module, "create_event_from_hass", mock_create)

    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock
    mark_websocket_service_connected(websocket_service, reason="test connected")

    data = {
        "type": "event",
        "event": {"event_type": "dummy", "data": {}, "context": {}, "origin": "local", "time_fired": "now"},
    }
    await websocket_service.dispatch(data)

    mock_create.assert_called_once_with(data)
    send_event_mock.assert_awaited_once_with(dummy_event)


@pytest.mark.parametrize("state", [ConnectionState.CONNECTING, ConnectionState.DISCONNECTED])
async def test_dispatch_drops_events_before_connected(
    websocket_service: WebsocketService, state: ConnectionState
) -> None:
    """Events that arrive while HA is still booting (before CONNECTED) never reach the bus (D12)."""
    websocket_service.hassette.send_event = AsyncMock()
    websocket_service._connection_state = state

    await websocket_service.dispatch(
        {"type": "event", "event": {"event_type": "state_changed", "data": {}, "origin": "LOCAL"}}
    )

    websocket_service.hassette.send_event.assert_not_awaited()


async def test_homeassistant_started_before_connected_releases_the_running_gate(
    websocket_service: WebsocketService,
) -> None:
    """homeassistant_started during the RUNNING wait is consumed by the gate, not dispatched."""
    websocket_service.hassette.send_event = AsyncMock()
    websocket_service._connection_state = ConnectionState.CONNECTING

    await websocket_service.dispatch(
        {"type": "event", "event": {"event_type": "homeassistant_started", "data": {}, "origin": "LOCAL"}}
    )

    assert websocket_service._core_started_event.is_set()
    websocket_service.hassette.send_event.assert_not_awaited()


async def test_dispatch_stamps_state_change_event_with_connected_generation(
    websocket_service: WebsocketService,
) -> None:
    mark_websocket_service_connected(websocket_service, reason="test connected")
    websocket_service.hassette.send_event = AsyncMock()

    await websocket_service.dispatch(
        {
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "origin": "LOCAL",
                "time_fired": "2024-01-01T00:00:00+00:00",
                "context": {"id": "ctx", "parent_id": None, "user_id": None},
                "data": {
                    "entity_id": "light.kitchen",
                    "old_state": None,
                    "new_state": {"entity_id": "light.kitchen", "state": "on"},
                },
            },
        }
    )

    send_event_call = websocket_service.hassette.send_event.await_args
    assert send_event_call is not None
    event = send_event_call.args[0]
    assert isinstance(event, RawStateChangeEvent)
    assert get_websocket_generation(event) == 1


async def test_dispatch_routes_result_messages(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService
) -> None:
    """Ensure result messages are passed to the responder helper."""
    respond_mock = Mock()
    monkeypatch.setattr(websocket_service, "respond_if_necessary", respond_mock)

    await websocket_service.dispatch({"type": "result", "id": 1})

    respond_mock.assert_called_once_with({"type": "result", "id": 1})
