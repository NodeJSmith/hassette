import asyncio
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aiohttp import ClientWebSocketResponse, WSMsgType
from aiohttp.client_exceptions import ClientConnectionResetError, ClientConnectorError

import hassette.core.websocket_service as websocket_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import (
    ConnectionClosedError,
    CouldNotFindHomeAssistantError,
    FailedMessageError,
    InvalidAuthError,
    RetryableConnectionClosedError,
)
from hassette.resources.base import ResourceStatus
from hassette.types import Topic
from hassette.types.enums import ConnectionState

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


@pytest.fixture
def websocket_service(hassette_with_bus: "HassetteHarness") -> WebsocketService:
    """Create a fresh websocket service instance for each test."""
    hassette = hassette_with_bus.hassette
    return WebsocketService(hassette, parent=hassette)


def build_fake_ws(*, is_closed: bool = False) -> ClientWebSocketResponse:
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
    """Verify the connected property mirrors the connection state machine."""

    assert websocket_service.connected is False

    # CONNECTED state → connected
    websocket_service._connection_state = ConnectionState.CONNECTED
    assert websocket_service.connected is True

    # CONNECTING state → not connected
    websocket_service._connection_state = ConnectionState.CONNECTING
    assert websocket_service.connected is False

    # DISCONNECTED state → not connected
    websocket_service._connection_state = ConnectionState.DISCONNECTED
    assert websocket_service.connected is False


async def test_send_json_injects_message_id_when_absent(websocket_service: WebsocketService) -> None:
    """Ensure send_json injects a message id and forwards the payload."""

    fake_ws = build_fake_ws()
    websocket_service._ws = fake_ws
    websocket_service._connection_state = ConnectionState.CONNECTED

    await websocket_service.send_json(type="ping")
    payload = fake_ws.send_json.await_args.args[0]  # pyright: ignore
    assert payload["type"] == "ping", "Expected original payload to be forwarded"
    assert payload["id"] == 1, "Expected send_json to add a message id when absent"


async def test_send_json_preserves_message_id_when_present(websocket_service: WebsocketService) -> None:
    """Ensure send_json preserves a message id when present."""

    fake_ws = build_fake_ws()
    websocket_service._ws = fake_ws
    websocket_service._connection_state = ConnectionState.CONNECTED

    await websocket_service.send_json(type="pong", id=41)
    second_payload = fake_ws.send_json.await_args_list[0].args[0]  # pyright: ignore
    assert second_payload["id"] == 41, "Expected explicit message id to be preserved"


async def test_send_json_requires_connection(websocket_service: WebsocketService) -> None:
    """Raise when attempting to send without an established connection (DISCONNECTED state)."""
    with pytest.raises(ConnectionClosedError):
        await websocket_service.send_json(type="ping")


async def test_send_json_checks_connection_state(websocket_service: WebsocketService) -> None:
    """Raise when connection_state is not CONNECTED (CONNECTING state)."""

    fake_ws = build_fake_ws(is_closed=True)
    websocket_service._ws = fake_ws
    # State machine is CONNECTING — not yet CONNECTED, so connected returns False
    websocket_service._connection_state = ConnectionState.CONNECTING

    with pytest.raises(ConnectionClosedError):
        await websocket_service.send_json(type="ping")


async def test_send_json_propagates_reset_error(websocket_service: WebsocketService) -> None:
    """Surface ClientConnectionResetError when the websocket resets."""

    fake_ws = build_fake_ws()
    fake_ws.send_json.side_effect = ClientConnectionResetError("boom")  # pyright: ignore

    websocket_service._ws = fake_ws
    websocket_service._connection_state = ConnectionState.CONNECTED

    with pytest.raises(ClientConnectionResetError):
        await websocket_service.send_json(type="ping")


async def test_send_json_wraps_generic_exceptions(websocket_service: WebsocketService) -> None:
    """Wrap unexpected errors in FailedMessageError."""

    fake_ws = build_fake_ws()
    fake_ws.send_json.side_effect = RuntimeError("unexpected")  # pyright: ignore

    websocket_service._ws = fake_ws
    websocket_service._connection_state = ConnectionState.CONNECTED

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


async def test_send_and_wait_times_out(websocket_service: WebsocketService, monkeypatch) -> None:
    """Raise FailedMessageError after exhausting retries on timeout."""
    monkeypatch.setattr(websocket_module, "MAX_RETRY_ATTEMPTS", 2)
    websocket_service.hassette.config.websocket.response_timeout_seconds = 0

    websocket_service.send_json = AsyncMock(return_value=None)

    with pytest.raises(FailedMessageError):
        await websocket_service.send_and_wait(type="no_response")

    assert websocket_service._response_futures == {}, "Expected future mapping to be cleared after timeout"


async def test_send_and_wait_retries_on_timeout(websocket_service: WebsocketService) -> None:
    """send_and_wait retries transient timeouts and succeeds when HA responds."""
    websocket_service.hassette.config.websocket.response_timeout_seconds = 0
    call_count = 0

    async def send_side_effect(**data: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            websocket_service.hassette.config.websocket.response_timeout_seconds = 5
            msg_id = data["id"]
            fut = websocket_service._response_futures[msg_id]
            fut.set_result({"ok": True})

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    result = await websocket_service.send_and_wait(type="get_states")

    assert result == {"ok": True}
    assert call_count == 2


async def test_send_and_wait_no_retry_on_ha_error(websocket_service: WebsocketService) -> None:
    """send_and_wait does not retry HA application errors (non-None code)."""

    async def send_side_effect(**data: object) -> None:
        msg_id = data["id"]
        fut = websocket_service._response_futures[msg_id]
        fut.set_exception(FailedMessageError("not found", code="not_found"))

    websocket_service.send_json = AsyncMock(side_effect=send_side_effect)

    with pytest.raises(FailedMessageError, match="not found"):
        await websocket_service.send_and_wait(type="get_entity_source")

    assert websocket_service.send_json.call_count == 1


async def test_respond_if_necessary_sets_result(websocket_service: WebsocketService) -> None:
    """Fulfill waiting futures when result payloads indicate success."""
    pending_future = websocket_service.hassette.loop.create_future()
    websocket_service._response_futures[5] = pending_future

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
    websocket_service._response_futures[9] = pending_future

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


async def test_authenticate_happy_path(websocket_service: WebsocketService) -> None:
    """Authenticate when Home Assistant replies with auth_ok."""
    fake_ws = build_fake_ws()
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
    fake_ws = build_fake_ws()
    fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "auth_invalid"}])
    websocket_service._ws = fake_ws

    with pytest.raises(InvalidAuthError):
        await websocket_service.authenticate()


async def test_dispatch_sends_events(monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService) -> None:
    """Forward Home Assistant events onto Hassette's event bus."""

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
    await websocket_service.dispatch(data)

    mock_create.assert_called_once_with(data)
    send_event_mock.assert_awaited_once_with(dummy_event)


async def test_dispatch_routes_result_messages(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService
) -> None:
    """Ensure result messages are passed to the responder helper."""
    respond_mock = Mock()
    monkeypatch.setattr(websocket_service, "respond_if_necessary", respond_mock)

    await websocket_service.dispatch({"type": "result", "id": 1})

    respond_mock.assert_called_once_with({"type": "result", "id": 1})


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


def make_failing_recv_task(error: Exception) -> asyncio.Task:
    """Create a task that raises the given error, simulating a failed recv loop."""

    async def _fail():
        raise error

    return asyncio.create_task(_fail())


async def test_disconnect_event_fires_on_recv_loop_failure(websocket_service: WebsocketService) -> None:
    """Fire WEBSOCKET_DISCONNECTED when the recv loop dies unexpectedly."""
    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock
    # The real make_connection calls mark_ready() via start_recv_and_subscribe; mirror that here
    websocket_service.mark_ready(reason="test: simulating successful connection")

    with (
        patch.object(
            websocket_service,
            "make_connection",
            return_value=make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()

    topics_sent = [call.args[0].topic for call in send_event_mock.await_args_list]
    assert Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED in topics_sent


async def test_marked_not_ready_on_recv_loop_failure(websocket_service: WebsocketService) -> None:
    """Mark the service not-ready immediately when the recv loop fails."""
    websocket_service.mark_ready(reason="test: verify ready→not-ready transition")
    websocket_service.hassette.send_event = AsyncMock()

    with (
        patch.object(
            websocket_service,
            "make_connection",
            return_value=make_failing_recv_task(
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
            "make_connection",
            return_value=make_failing_recv_task(
                RetryableConnectionClosedError("peer gone"),
            ),
        ),
        pytest.raises(RetryableConnectionClosedError),
    ):
        await websocket_service.serve()


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
    """start_recv_and_subscribe spawns recv, calls mark_ready, sets _connected_at, returns recv task."""
    fake_task = asyncio.create_task(asyncio.sleep(0))
    websocket_service.task_bucket = MagicMock()

    # Capture and discard the coroutine argument to avoid "coroutine never awaited" warning
    spawned_coros = []

    def _spawn_side_effect(coro, *, name=None):  # noqa: ARG001
        spawned_coros.append(coro)
        return fake_task

    websocket_service.task_bucket.spawn = Mock(side_effect=_spawn_side_effect)
    websocket_service.send_connection_established_event = AsyncMock()
    websocket_service.subscribe_events = AsyncMock(return_value=42)
    websocket_service.mark_ready = Mock()
    # Stub _emit_readiness_event: this test focuses on mark_ready/subscription behavior;
    # readiness event emission is covered by test_websocket_readiness_events.py.
    websocket_service._emit_readiness_event = AsyncMock()

    # start_recv_and_subscribe calls set_connection_state(CONNECTED).
    # DISCONNECTED → CONNECTED is invalid; the real flow goes through CONNECTING first
    # (set by serve() before calling make_connection). Set CONNECTING as the pre-condition.
    websocket_service._connection_state = ConnectionState.CONNECTING

    result = await websocket_service.start_recv_and_subscribe()

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
    """partial_cleanup cancels recv task, closes ws, clears futures and subscription ids."""
    fake_ws = build_fake_ws()
    fake_recv_task = asyncio.create_task(asyncio.sleep(100))
    websocket_service._ws = fake_ws
    websocket_service._recv_task = fake_recv_task
    websocket_service._subscription_ids = {1, 2}

    # Seed a pending future
    fut = websocket_service.hassette.loop.create_future()
    websocket_service._response_futures[99] = fut

    await websocket_service.partial_cleanup()

    assert websocket_service._ws is None
    assert websocket_service._recv_task is None
    assert websocket_service._subscription_ids == set()
    assert websocket_service._response_futures == {}
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


async def test_early_drop_retries_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """An early-drop within the stable window is retried transparently.

    Verifies: handle_failed never called, make_connection called 3 times,
    partial_cleanup called 2 times, DISCONNECTED event emitted 2 times,
    mark_not_ready called twice.
    """
    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock

    # First two make_connection calls succeed but recv task fails immediately.
    # Third call succeeds with clean exit.
    call_count = 0
    partial_cleanup_count = 0
    make_connection_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count, make_connection_count
        call_count += 1
        make_connection_count += 1
        # Simulate _connected_at being set (within stable window) and mark_ready
        websocket_service._connected_at = time.monotonic()
        websocket_service.mark_ready(reason="test: simulating successful connection")
        if call_count <= 2:

            async def _fail():
                raise RetryableConnectionClosedError("peer gone")

            return asyncio.create_task(_fail())

        async def _clean():
            pass

        return asyncio.create_task(_clean())

    async def fake_partial_cleanup():
        nonlocal partial_cleanup_count
        partial_cleanup_count += 1

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = fake_partial_cleanup  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_max_retries", 5)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_initial_seconds", 0.001)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_max_seconds", 0.01)

    await websocket_service.serve()

    assert make_connection_count == 3, f"Expected 3 make_connection calls, got {make_connection_count}"
    assert partial_cleanup_count == 2, f"Expected 2 partial_cleanup calls, got {partial_cleanup_count}"

    # DISCONNECTED should have been sent 2 times (once per early drop)
    disconnected_count = sum(
        1
        for call in send_event_mock.await_args_list
        if call.args[0].topic == Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED
    )
    assert disconnected_count == 2, f"Expected 2 DISCONNECTED events, got {disconnected_count}"


async def test_early_drop_exhausts_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """After exhausting early-drop retry count, exception propagates out of serve()."""
    websocket_service.hassette.send_event = AsyncMock()

    call_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count
        call_count += 1
        websocket_service._connected_at = time.monotonic()
        websocket_service.mark_ready(reason="test: simulating successful connection")

        async def _fail():
            raise RetryableConnectionClosedError("dropped")

        return asyncio.create_task(_fail())

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_max_retries", 2)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_initial_seconds", 0.001)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_max_seconds", 0.01)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.serve()

    # Initial + 2 retries = 3 total attempts, then propagates
    assert call_count == 3, f"Expected 3 total make_connection calls, got {call_count}"
    assert not websocket_service.is_ready()


async def test_early_drop_exhausts_recovery_timeout(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """When recovery_elapsed exceeds max_recovery, failure propagates without further retry."""
    websocket_service.hassette.send_event = AsyncMock()

    call_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count
        call_count += 1
        websocket_service._connected_at = time.monotonic()
        websocket_service.mark_ready(reason="test: simulating successful connection")

        async def _fail():
            raise RetryableConnectionClosedError("dropped")

        return asyncio.create_task(_fail())

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

    # Configure very short max recovery (effectively 0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_max_retries", 10)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "max_recovery_seconds", 0.0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_initial_seconds", 0.001)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_max_seconds", 0.01)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.serve()

    # Should have made only 1 attempt then stopped due to recovery timeout
    assert call_count == 1, f"Expected 1 make_connection call (recovery timeout), got {call_count}"


async def test_stable_connection_failure_propagates_immediately(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """A drop outside the stable window propagates immediately without retry."""
    websocket_service.hassette.send_event = AsyncMock()

    call_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count
        call_count += 1
        # Set _connected_at to 60 seconds ago — outside any stable window
        websocket_service._connected_at = time.monotonic() - 60.0
        websocket_service.mark_ready(reason="test: simulating successful connection")

        async def _fail():
            raise RetryableConnectionClosedError("stable drop")

        return asyncio.create_task(_fail())

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)

    with pytest.raises(RetryableConnectionClosedError):
        await websocket_service.serve()

    # Only 1 attempt — stable drop doesn't retry
    assert call_count == 1, f"Expected 1 make_connection call, got {call_count}"


async def test_non_retryable_exception_in_stable_window(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """RuntimeError within stable window propagates immediately — not an early drop."""
    websocket_service.hassette.send_event = AsyncMock()

    call_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count
        call_count += 1
        websocket_service._connected_at = time.monotonic()
        websocket_service.mark_ready(reason="test: simulating successful connection")

        async def _fail():
            raise RuntimeError("unexpected internal error")

        return asyncio.create_task(_fail())

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)

    with pytest.raises(RuntimeError):
        await websocket_service.serve()

    assert call_count == 1, f"Expected 1 make_connection call, got {call_count}"


async def test_auth_failure_on_reconnect_logs_distinctive_message(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """InvalidAuthError after at least one early-drop retry propagates and leaves DISCONNECTED."""
    websocket_service.hassette.send_event = AsyncMock()

    call_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            websocket_service._connected_at = time.monotonic()
            websocket_service.mark_ready(reason="test: simulating successful connection")

            async def _fail():
                raise RetryableConnectionClosedError("dropped")

            return asyncio.create_task(_fail())
        raise InvalidAuthError("token revoked")

    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_max_retries", 5)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_initial_seconds", 0.001)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_max_seconds", 0.01)

    with pytest.raises(InvalidAuthError):
        await websocket_service.serve()

    assert call_count >= 2
    assert websocket_service.connection_state == ConnectionState.DISCONNECTED


async def test_send_connection_lost_event_idempotent(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event is a no-op when service is already not-ready."""
    send_event_mock = AsyncMock()
    websocket_service.hassette.send_event = send_event_mock

    # Service starts not-ready; calling send_connection_lost_event should be a no-op
    assert not websocket_service.is_ready()
    await websocket_service.send_connection_lost_event()

    disconnected_count = sum(
        1
        for call in send_event_mock.await_args_list
        if call.args[0].topic == Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED
    )
    assert disconnected_count == 0, "Expected no DISCONNECTED events when already not-ready"


async def test_send_connection_lost_event_self_suppressing(websocket_service: WebsocketService) -> None:
    """send_connection_lost_event does not propagate bus exceptions."""
    websocket_service.hassette.send_event = AsyncMock(side_effect=RuntimeError("bus is down"))
    websocket_service.mark_ready(reason="test: make service ready so event fires")

    # Should not raise even though the bus raises
    await websocket_service.send_connection_lost_event()


async def test_raw_recv_passes_close_code(websocket_service: WebsocketService) -> None:
    """raw_recv passes close_code from _ws.close_code when raising RetryableConnectionClosedError."""
    fake_ws = build_fake_ws()
    fake_ws.close_code = 1001  # pyright: ignore[reportAttributeAccessIssue]
    fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.CLOSE, data=None))
    websocket_service._ws = fake_ws

    with pytest.raises(RetryableConnectionClosedError) as exc_info:
        await websocket_service.raw_recv()

    assert exc_info.value.close_code == 1001, f"Expected close_code=1001, got {exc_info.value.close_code}"


async def test_service_status_stays_running_during_early_drop(
    monkeypatch: pytest.MonkeyPatch,
    websocket_service: WebsocketService,
) -> None:
    """During early-drop retry: service status is RUNNING but is_ready() is False."""
    websocket_service.hassette.send_event = AsyncMock()

    statuses_during_retry: list[tuple[ResourceStatus, bool]] = []
    call_count = 0

    async def fake_make_connection(_session):
        nonlocal call_count
        call_count += 1
        websocket_service._connected_at = time.monotonic()
        websocket_service.mark_ready(reason="test: simulating successful connection")

        if call_count == 1:

            async def _fail():
                raise RetryableConnectionClosedError("dropped")

            return asyncio.create_task(_fail())

        async def _clean():
            pass

        return asyncio.create_task(_clean())

    original_mark_not_ready = websocket_service.mark_not_ready

    def capturing_mark_not_ready(reason: str | None = None) -> None:
        original_mark_not_ready(reason=reason)
        statuses_during_retry.append((websocket_service.status, websocket_service.is_ready()))

    websocket_service.mark_not_ready = capturing_mark_not_ready  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.make_connection = fake_make_connection  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.partial_cleanup = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_max_retries", 5)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_stable_window_seconds", 30.0)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_initial_seconds", 0.001)
    monkeypatch.setattr(websocket_service.hassette.config.websocket, "early_drop_backoff_max_seconds", 0.01)

    # Set service to RUNNING state using ._status bypass — deliberate test fixture setup,
    # not a lifecycle operation. handle_running() requires STARTING → RUNNING which needs
    # a full initialize() first; here we just need the status to be RUNNING for the assertion.
    websocket_service._status = ResourceStatus.RUNNING
    await websocket_service.serve()

    assert len(statuses_during_retry) >= 1
    status, ready = statuses_during_retry[0]
    assert status == ResourceStatus.RUNNING, f"Expected RUNNING status, got {status}"
    assert not ready, "Expected is_ready()=False during early-drop retry"
