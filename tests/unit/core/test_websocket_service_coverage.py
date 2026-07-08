"""Coverage-focused unit tests for WebsocketService.

Targets branches not already exercised by test_ws_connection_state.py,
test_websocket_readiness_events.py, and tests/integration/test_websocket_service.py:
cleanup() teardown branches, make_connection()'s tenacity retry wrapper,
subscribe_events() payload construction, connect_ws()'s non-refused error path,
raw_recv()'s binary/unexpected-type branches, respond_if_necessary()'s guard
branches, and a handful of one-line property delegations.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from aiohttp import WSMsgType
from aiohttp.client_exceptions import ClientConnectorError

from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import FailedMessageError, InvalidAuthError, RetryableConnectionClosedError
from hassette.resources.service import Service
from hassette.test_utils import build_fake_ws, make_ws_hassette_stub
from hassette.types import Topic


@pytest.fixture
async def websocket_service() -> WebsocketService:
    """Create a WebsocketService with a fully-mocked hassette stub (sealed=False for extra attrs)."""
    hassette = make_ws_hassette_stub(sealed=False)
    return WebsocketService(hassette=hassette)


class TestTimeoutAndLogLevelProperties:
    def test_properties_delegate_to_config(self, websocket_service: WebsocketService) -> None:
        """resp/connection/total/heartbeat/authentication timeouts and config_log_level read from config."""
        cfg = websocket_service.hassette.config.websocket
        assert websocket_service.resp_timeout_seconds == cfg.response_timeout_seconds
        assert websocket_service.connection_timeout_seconds == cfg.connection_timeout_seconds
        assert websocket_service.total_timeout_seconds == cfg.total_timeout_seconds
        assert websocket_service.heartbeat_interval_seconds == cfg.heartbeat_interval_seconds
        assert websocket_service.authentication_timeout_seconds == cfg.authentication_timeout_seconds
        assert websocket_service.config_log_level == websocket_service.hassette.config.logging.websocket


class TestConnectWsErrorHandling:
    async def test_connect_ws_reraises_client_connector_error_without_refused_cause(
        self, websocket_service: WebsocketService
    ) -> None:
        """connect_ws re-raises ClientConnectorError as-is when its cause is not ConnectionRefusedError."""
        fake_session = MagicMock()
        other_cause = OSError("dns lookup failed")
        connector_error = ClientConnectorError.__new__(ClientConnectorError)
        connector_error.__cause__ = other_cause
        fake_session.ws_connect = AsyncMock(side_effect=connector_error)

        with pytest.raises(ClientConnectorError) as exc_info:
            await websocket_service.connect_ws(fake_session)

        assert exc_info.value is connector_error


class TestSubscribeEvents:
    async def test_subscribe_events_without_event_type_omits_filter(self, websocket_service: WebsocketService) -> None:
        """subscribe_events sends a bare subscribe_events payload when no event_type is given."""
        captured: dict = {}

        async def fake_send_json(**data):
            captured.update(data)
            msg_id = data["id"]
            fut = websocket_service._response_futures.get(msg_id)
            if fut and not fut.done():
                fut.set_result(None)

        websocket_service.send_json = AsyncMock(side_effect=fake_send_json)

        sub_id = await websocket_service.subscribe_events()

        assert captured["type"] == "subscribe_events"
        assert "event_type" not in captured
        assert captured["id"] == sub_id

    async def test_subscribe_events_with_event_type_includes_filter(self, websocket_service: WebsocketService) -> None:
        """subscribe_events includes the event_type filter in the payload when given."""
        captured: dict = {}

        async def fake_send_json(**data):
            captured.update(data)
            msg_id = data["id"]
            fut = websocket_service._response_futures.get(msg_id)
            if fut and not fut.done():
                fut.set_result(None)

        websocket_service.send_json = AsyncMock(side_effect=fake_send_json)

        sub_id = await websocket_service.subscribe_events(event_type="state_changed")

        assert captured["event_type"] == "state_changed"
        assert captured["id"] == sub_id


class TestSendAndWaitCallerProvidedId:
    async def test_uses_caller_provided_id_instead_of_generating_one(self, websocket_service: WebsocketService) -> None:
        """send_and_wait uses an explicitly-passed id (as subscribe_events does) rather than allocating one."""

        async def send_side_effect(**data):
            msg_id = data["id"]
            fut = websocket_service._response_futures[msg_id]
            fut.set_result({"ok": True})

        websocket_service.send_json = AsyncMock(
            side_effect=send_side_effect
        )  # boundary-exempt: collaborator of send_and_wait

        result = await websocket_service.send_and_wait(type="subscribe_events", id=99)

        assert result == {"ok": True}
        sent_id = websocket_service.send_json.await_args.kwargs["id"]
        assert sent_id == 99


class TestMakeConnectionRetries:
    async def test_make_connection_retries_transient_failures_then_succeeds(
        self, websocket_service: WebsocketService
    ) -> None:
        """make_connection retries connect_ws failures (not in NON_RETRYABLE) up to the configured attempts."""
        attempts = 0

        async def flaky_connect_ws(_session):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("transient connect failure")

        websocket_service.connect_ws = flaky_connect_ws  # boundary-exempt: collaborator of make_connection
        websocket_service.partial_cleanup = AsyncMock()  # boundary-exempt: collaborator of make_connection
        # boundary-exempt: collaborator of make_connection
        websocket_service.start_recv_and_subscribe = AsyncMock(return_value="recv-task-sentinel")

        max_attempts = 3
        websocket_service.hassette.config.websocket.connect_retry_max_attempts = max_attempts

        result = await websocket_service.make_connection(MagicMock())

        assert attempts == max_attempts, f"Expected {max_attempts} connect_ws attempts, got {attempts}"
        assert result == "recv-task-sentinel"
        assert websocket_service.partial_cleanup.await_count == max_attempts, (
            "partial_cleanup runs before every attempt"
        )

    async def test_make_connection_does_not_retry_invalid_auth(self, websocket_service: WebsocketService) -> None:
        """make_connection propagates InvalidAuthError immediately without retrying (NON_RETRYABLE)."""
        attempts = 0

        async def bad_auth_connect_ws(_session):
            nonlocal attempts
            attempts += 1
            raise InvalidAuthError("token rejected")

        websocket_service.connect_ws = bad_auth_connect_ws  # boundary-exempt: collaborator of make_connection
        websocket_service.partial_cleanup = AsyncMock()  # boundary-exempt: collaborator of make_connection

        with pytest.raises(InvalidAuthError):
            await websocket_service.make_connection(MagicMock())

        assert attempts == 1, f"Expected exactly 1 attempt for a non-retryable error, got {attempts}"


class TestBeforeShutdown:
    async def test_before_shutdown_sends_connection_lost_event(self, websocket_service: WebsocketService) -> None:
        """before_shutdown fires the WEBSOCKET_DISCONNECTED event via send_connection_lost_event."""
        websocket_service.mark_ready(reason="test: pre-shutdown ready state")
        send_event_mock = AsyncMock()
        websocket_service.hassette.send_event = send_event_mock

        await websocket_service.before_shutdown()

        topics = [call.args[0].topic for call in send_event_mock.await_args_list]
        assert Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED in topics


class TestSendConnectionEstablishedEvent:
    async def test_sends_connected_topic(self, websocket_service: WebsocketService) -> None:
        """send_connection_established_event fires exactly one WEBSOCKET_CONNECTED event."""
        send_event_mock = AsyncMock()
        websocket_service.hassette.send_event = send_event_mock

        await websocket_service.send_connection_established_event()

        send_event_mock.assert_awaited_once()
        sent_event = send_event_mock.await_args.args[0]
        assert sent_event.topic == Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED


class TestCleanup:
    async def test_cleanup_sets_exception_on_pending_futures_and_clears_them(
        self, websocket_service: WebsocketService
    ) -> None:
        """cleanup() resolves every pending response future with RetryableConnectionClosedError."""
        fut = websocket_service.hassette.loop.create_future()
        websocket_service._response_futures[7] = fut
        websocket_service._ws = None
        websocket_service._session = None
        websocket_service._recv_task = None

        with patch.object(Service, "cleanup", new=AsyncMock()):
            await websocket_service.cleanup()

        assert fut.done()
        assert isinstance(fut.exception(), RetryableConnectionClosedError)
        assert websocket_service._response_futures == {}

    async def test_cleanup_attempts_unsubscribe_for_each_subscription_and_clears_ids(
        self, websocket_service: WebsocketService
    ) -> None:
        """cleanup() calls send_json(unsubscribe_events) once per active subscription, then clears the set."""
        websocket_service._ws = build_fake_ws()
        websocket_service._subscription_ids = {1, 2}
        websocket_service._session = None
        websocket_service._recv_task = None

        send_json_mock = AsyncMock()
        websocket_service.send_json = send_json_mock  # boundary-exempt: collaborator of cleanup

        with patch.object(Service, "cleanup", new=AsyncMock()):
            await websocket_service.cleanup()

        assert send_json_mock.await_count == 2
        called_subscriptions = {call.kwargs["subscription"] for call in send_json_mock.await_args_list}
        assert called_subscriptions == {1, 2}
        assert websocket_service._subscription_ids == set()

    async def test_cleanup_skips_unsubscribe_when_websocket_already_closed(
        self, websocket_service: WebsocketService
    ) -> None:
        """cleanup() skips the unsubscribe loop (and leaves subscription_ids untouched) when ws.closed is True."""
        websocket_service._ws = build_fake_ws(is_closed=True)
        websocket_service._subscription_ids = {1}
        websocket_service._session = None
        websocket_service._recv_task = None

        send_json_mock = AsyncMock()
        websocket_service.send_json = send_json_mock  # boundary-exempt: collaborator of cleanup

        with patch.object(Service, "cleanup", new=AsyncMock()):
            await websocket_service.cleanup()

        send_json_mock.assert_not_awaited()
        assert websocket_service._subscription_ids == {1}, "skipped branch must not clear subscription_ids"

    async def test_cleanup_cancels_recv_task_closes_ws_and_session(self, websocket_service: WebsocketService) -> None:
        """cleanup() cancels the recv task, closes an open websocket, and closes the session."""
        fake_ws = build_fake_ws(is_closed=False)
        websocket_service._ws = fake_ws
        websocket_service._subscription_ids = set()

        recv_task = asyncio.create_task(asyncio.sleep(100))
        websocket_service._recv_task = recv_task

        fake_session = MagicMock()
        fake_session.close = AsyncMock()
        websocket_service._session = fake_session

        with patch.object(Service, "cleanup", new=AsyncMock()):
            await websocket_service.cleanup()

        assert websocket_service._recv_task is None
        assert recv_task.cancelled()
        fake_ws.close.assert_awaited_once()
        fake_session.close.assert_awaited_once()


class TestRawRecvEdgeCases:
    async def test_raw_recv_raises_when_ws_not_established(self, websocket_service: WebsocketService) -> None:
        """raw_recv raises RuntimeError immediately when self._ws is None."""
        websocket_service._ws = None

        with pytest.raises(RuntimeError, match="not established"):
            await websocket_service.raw_recv()

    async def test_raw_recv_ignores_binary_frame(self, websocket_service: WebsocketService) -> None:
        """raw_recv logs and returns without dispatching for a BINARY frame."""
        fake_ws = build_fake_ws()
        fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.BINARY, data=b"\x00\x01"))
        websocket_service._ws = fake_ws

        dispatch_mock = AsyncMock()
        websocket_service.dispatch = dispatch_mock  # boundary-exempt: collaborator of raw_recv

        await websocket_service.raw_recv()

        dispatch_mock.assert_not_awaited()

    async def test_raw_recv_ignores_unexpected_message_type(self, websocket_service: WebsocketService) -> None:
        """raw_recv logs and returns without dispatching or raising for an unhandled frame type."""
        fake_ws = build_fake_ws()
        fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.PONG, data=None))
        websocket_service._ws = fake_ws

        dispatch_mock = AsyncMock()
        websocket_service.dispatch = dispatch_mock  # boundary-exempt: collaborator of raw_recv

        await websocket_service.raw_recv()

        dispatch_mock.assert_not_awaited()

    async def test_raw_recv_swallows_invalid_json_without_dispatching(
        self, websocket_service: WebsocketService
    ) -> None:
        """raw_recv catches JSONDecodeError on malformed TEXT frames and skips dispatch."""
        fake_ws = build_fake_ws()
        fake_ws.receive = AsyncMock(return_value=SimpleNamespace(type=WSMsgType.TEXT, data="{not valid json"))
        websocket_service._ws = fake_ws

        dispatch_mock = AsyncMock()
        websocket_service.dispatch = dispatch_mock  # boundary-exempt: collaborator of raw_recv

        await websocket_service.raw_recv()

        dispatch_mock.assert_not_awaited()


class TestDispatchSuppressesErrors:
    async def test_dispatch_suppresses_exceptions_from_hass_event_handling(
        self, websocket_service: WebsocketService
    ) -> None:
        """dispatch() does not propagate exceptions raised while handling an 'event' message."""

        async def failing_dispatch_hass_event(_data):
            raise RuntimeError("boom")

        websocket_service.dispatch_hass_event = failing_dispatch_hass_event  # boundary-exempt: collaborator of dispatch

        await websocket_service.dispatch({"type": "event", "event": {}})  # must not raise

    async def test_dispatch_ignores_unknown_message_type(self, websocket_service: WebsocketService) -> None:
        """dispatch() falls through to the 'other' match case for a type it doesn't recognize."""
        respond_mock = Mock()
        websocket_service.respond_if_necessary = respond_mock  # boundary-exempt: collaborator of dispatch

        await websocket_service.dispatch({"type": "totally_unknown_type"})

        respond_mock.assert_not_called()


class TestRespondIfNecessaryGuards:
    def test_ignores_non_result_message(self, websocket_service: WebsocketService) -> None:
        """respond_if_necessary is a no-op for message types other than 'result'."""
        fut = websocket_service.hassette.loop.create_future()
        websocket_service._response_futures[1] = fut

        websocket_service.respond_if_necessary({"type": "event", "id": 1})

        assert not fut.done()

    def test_ignores_message_without_id(self, websocket_service: WebsocketService) -> None:
        """respond_if_necessary warns and returns without touching futures when id is missing."""
        fut = websocket_service.hassette.loop.create_future()
        websocket_service._response_futures[1] = fut

        websocket_service.respond_if_necessary({"type": "result", "success": True})

        assert not fut.done()
        assert 1 in websocket_service._response_futures

    def test_ignores_unmatched_id(self, websocket_service: WebsocketService) -> None:
        """respond_if_necessary is a no-op when the message id has no pending future."""
        fut = websocket_service.hassette.loop.create_future()
        websocket_service._response_futures[1] = fut

        websocket_service.respond_if_necessary({"type": "result", "id": 999, "success": True})

        assert not fut.done()

    def test_skips_already_done_future(self, websocket_service: WebsocketService) -> None:
        """respond_if_necessary leaves an already-resolved future untouched."""
        fut = websocket_service.hassette.loop.create_future()
        fut.set_result("first result")
        websocket_service._response_futures[3] = fut

        websocket_service.respond_if_necessary(
            {"type": "result", "id": 3, "success": False, "error": {"message": "late error"}}
        )

        assert fut.result() == "first result"

    def test_error_without_code_field_defaults_to_none(self, websocket_service: WebsocketService) -> None:
        """respond_if_necessary sets code=None on the exception when HA's error envelope omits 'code'."""
        fut = websocket_service.hassette.loop.create_future()
        websocket_service._response_futures[5] = fut

        websocket_service.respond_if_necessary(
            {"type": "result", "id": 5, "success": False, "error": {"message": "no code field here"}}
        )

        exc = fut.exception()
        assert isinstance(exc, FailedMessageError)
        assert exc.code is None


class TestAuthenticateUnexpectedResponse:
    async def test_raises_on_unexpected_auth_response_type(self, websocket_service: WebsocketService) -> None:
        """authenticate raises RuntimeError when HA sends neither auth_ok nor auth_invalid."""
        fake_ws = build_fake_ws()
        fake_ws.receive_json = AsyncMock(side_effect=[{"type": "auth_required"}, {"type": "something_else"}])
        websocket_service._ws = fake_ws

        with pytest.raises(RuntimeError, match="Unexpected authentication response"):
            await websocket_service.authenticate()
