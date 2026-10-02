"""WebsocketService.send_and_wait: sent-but-unanswered commands raise the OutcomeUnknownError family.

A response timeout raises ``ResponseTimeoutError`` and a disconnect while waiting raises
``ResponseLostError``. Both mean the command reached (or may have reached) Home Assistant, so it
may or may not have applied. Non-retried sends go out exactly once; a timed-out non-retried send
stays in the pending-responses table, marked timed out, so a late reply is logged and settles it.

Log assertions mock ``websocket_service.logger`` (or ``_pending.logger`` for late replies, which
``PendingResponses`` logs) rather than using caplog: another test in the same process can disable
propagation on the ``hassette`` logger, which would blind caplog.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from hassette.core import websocket_responses as websocket_responses_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import (
    FailedMessageError,
    OutcomeUnknownError,
    ResponseLostError,
    ResponseTimeoutError,
    RetryableConnectionClosedError,
)
from hassette.testing._ws_mocks import build_fake_ws

from .conftest import cleanup_disconnected, run_cleanup


def _rendered(call) -> str:
    """The message a mocked logger call would have produced (%-style args applied)."""
    msg, *args = call.args
    return msg % tuple(args)


def _drop_connection(websocket_service: WebsocketService, *, close_code: int | None = None) -> None:
    """Make every send fail its response future as cleanup() does on a disconnect."""

    async def drop(**data):
        websocket_service._pending.entries[data["id"]].future.set_exception(
            RetryableConnectionClosedError("WebSocket disconnected", close_code=close_code)
        )

    websocket_service.send_json = AsyncMock(side_effect=drop)


def _time_out_immediately(websocket_service: WebsocketService) -> None:
    websocket_service.hassette.config.websocket.response_timeout_seconds = 0
    websocket_service.send_json = AsyncMock()


async def _timed_out_write(websocket_service: WebsocketService, **data) -> int:
    """Send a non-retried command that times out; return the msg id it went out under."""
    with pytest.raises(ResponseTimeoutError):
        await websocket_service.send_and_wait(retry_on_timeout=False, **data)
    return websocket_service.send_json.await_args.kwargs["id"]


class TestResponseTimeout:
    async def test_non_retried_send_goes_out_once_and_raises_response_timeout(
        self, websocket_service: WebsocketService
    ) -> None:
        """A write that times out is sent once and raises the distinguishable outcome-unknown type."""
        _time_out_immediately(websocket_service)

        with pytest.raises(ResponseTimeoutError) as exc_info:
            await websocket_service.send_and_wait(type="fire_event", event_type="doorbell", retry_on_timeout=False)

        assert websocket_service.send_json.await_count == 1
        exc = exc_info.value
        assert isinstance(exc, OutcomeUnknownError)
        assert isinstance(exc, FailedMessageError)
        assert not isinstance(exc, TimeoutError)
        assert exc.code is None

    async def test_retried_read_raises_response_timeout_on_last_attempt(
        self, websocket_service: WebsocketService
    ) -> None:
        """Reads keep retrying on timeout; the final attempt raises the same type as a write."""
        _time_out_immediately(websocket_service)
        attempts = 2

        with (
            patch("hassette.core.websocket_service.MAX_RETRY_ATTEMPTS", attempts),
            pytest.raises(ResponseTimeoutError),
        ):
            await websocket_service.send_and_wait(type="get_states")

        assert websocket_service.send_json.await_count == attempts

    async def test_message_names_type_id_and_timeout_without_payload_values(
        self, websocket_service: WebsocketService
    ) -> None:
        """The message carries no payload values; the full outgoing payload lives on original_data."""
        _time_out_immediately(websocket_service)

        with pytest.raises(ResponseTimeoutError) as exc_info:
            await websocket_service.send_and_wait(
                type="input_text/create", name="WiFi", initial="hunter2", retry_on_timeout=False
            )

        msg_id = websocket_service.send_json.await_args.kwargs["id"]
        msg = str(exc_info.value)
        assert "input_text/create" in msg
        assert str(msg_id) in msg
        assert "0s" in msg
        assert "hunter2" not in msg
        assert exc_info.value.original_data == {
            "type": "input_text/create",
            "name": "WiFi",
            "initial": "hunter2",
            "id": msg_id,
        }

    async def test_timeout_logs_warning_when_raised(self, websocket_service: WebsocketService) -> None:
        """Raising an outcome-unknown error leaves a WARNING behind even if the caller swallows it."""
        _time_out_immediately(websocket_service)
        websocket_service.logger = Mock()

        msg_id = await _timed_out_write(websocket_service, type="fire_event", event_type="doorbell")

        websocket_service.logger.warning.assert_called_once()
        rendered = _rendered(websocket_service.logger.warning.call_args)
        assert "fire_event" in rendered
        assert str(msg_id) in rendered


class TestResponseLost:
    async def test_disconnect_while_waiting_raises_response_lost_without_retry(
        self, websocket_service: WebsocketService
    ) -> None:
        """A disconnect while waiting is outcome-unknown and is not retried, even for a read."""
        _drop_connection(websocket_service, close_code=1006)

        with pytest.raises(ResponseLostError) as exc_info:
            await websocket_service.send_and_wait(type="get_states")

        assert websocket_service.send_json.await_count == 1
        exc = exc_info.value
        assert isinstance(exc, OutcomeUnknownError)
        assert isinstance(exc, RetryableConnectionClosedError)
        assert not isinstance(exc, FailedMessageError)
        assert exc.close_code == 1006
        assert "get_states" in str(exc)

    @pytest.mark.parametrize(
        "teardown",
        [
            pytest.param(lambda ws: ws.partial_cleanup(), id="reconnect"),
            pytest.param(run_cleanup, id="shutdown"),
        ],
    )
    async def test_teardown_fails_pending_send_with_peer_close_code(
        self, websocket_service: WebsocketService, teardown
    ) -> None:
        """Teardown after a peer close fails a waiting send as ResponseLostError carrying the peer's close code."""
        sent = asyncio.Event()
        websocket_service.send_json = AsyncMock(side_effect=lambda **_: sent.set())
        websocket_service._ws = build_fake_ws(is_closed=True, close_code=4001)
        websocket_service._session = None
        websocket_service._recv_task = None

        task = asyncio.create_task(
            websocket_service.send_and_wait(type="call_service", domain="counter", retry_on_timeout=False)
        )
        await asyncio.wait_for(sent.wait(), timeout=1)

        await teardown(websocket_service)

        with pytest.raises(ResponseLostError) as exc_info:
            await task
        assert exc_info.value.close_code == 4001

    async def test_disconnect_logs_warning_when_raised(self, websocket_service: WebsocketService) -> None:
        _drop_connection(websocket_service)
        websocket_service.logger = Mock()

        with pytest.raises(ResponseLostError):
            await websocket_service.send_and_wait(type="fire_event", event_type="doorbell", retry_on_timeout=False)

        websocket_service.logger.warning.assert_called_once()
        msg_id = websocket_service.send_json.await_args.kwargs["id"]
        rendered = _rendered(websocket_service.logger.warning.call_args)
        assert "fire_event" in rendered
        assert str(msg_id) in rendered


class TestLateReplyToTimedOutWrite:
    async def test_late_success_logs_info_and_drops_entry(self, websocket_service: WebsocketService) -> None:
        """A late success settles a timed-out write as applied."""
        _time_out_immediately(websocket_service)
        msg_id = await _timed_out_write(websocket_service, type="fire_event", event_type="doorbell")
        websocket_service._pending.logger = Mock()

        websocket_service.respond_if_necessary({"type": "result", "id": msg_id, "success": True, "result": None})

        websocket_service._pending.logger.warning.assert_not_called()
        websocket_service._pending.logger.info.assert_called_once()
        rendered = _rendered(websocket_service._pending.logger.info.call_args)
        assert "fire_event" in rendered
        assert str(msg_id) in rendered
        assert msg_id not in websocket_service._pending.entries

    async def test_late_failure_logs_warning_and_drops_entry(self, websocket_service: WebsocketService) -> None:
        """A late failure reports HA's error for a timed-out write, not that it failed to apply."""
        _time_out_immediately(websocket_service)
        msg_id = await _timed_out_write(websocket_service, type="counter/delete", counter_id="motion")
        websocket_service._pending.logger = Mock()

        websocket_service.respond_if_necessary(
            {"type": "result", "id": msg_id, "success": False, "error": {"code": "not_found", "message": "x"}}
        )

        websocket_service._pending.logger.info.assert_not_called()
        websocket_service._pending.logger.warning.assert_called_once()
        rendered = _rendered(websocket_service._pending.logger.warning.call_args)
        assert "counter/delete" in rendered
        assert str(msg_id) in rendered
        assert msg_id not in websocket_service._pending.entries

    async def test_reply_racing_the_deadline_is_returned_or_logged(self, websocket_service: WebsocketService) -> None:
        """A reply queued as the response timeout fires is never silently dropped.

        The reply lands after the deadline but before the sending task resumes. It must either
        come back as the call's result or be logged as a late reply, leaving nothing recorded.
        """
        websocket_service.hassette.config.websocket.response_timeout_seconds = 0
        websocket_service._pending.logger = Mock()
        loop = asyncio.get_running_loop()

        async def reply_as_deadline_fires(**data) -> None:
            reply = {"type": "result", "id": data["id"], "success": True, "result": {"ok": True}}
            loop.call_soon(websocket_service.respond_if_necessary, reply)

        websocket_service.send_json = AsyncMock(side_effect=reply_as_deadline_fires)

        try:
            result = await websocket_service.send_and_wait(
                type="fire_event", event_type="doorbell", retry_on_timeout=False
            )
        except ResponseTimeoutError:
            await asyncio.sleep(0)
            websocket_service._pending.logger.info.assert_called_once()
        else:
            assert result == {"ok": True}
        assert websocket_service._pending.entries == {}

    async def test_cancelled_send_is_not_recorded(self, websocket_service: WebsocketService) -> None:
        """A caller that cancels has stopped caring about the outcome, so a late reply stays silent."""
        sent = asyncio.Event()
        websocket_service.send_json = AsyncMock(side_effect=lambda **_: sent.set())
        websocket_service._pending.logger = Mock()
        task = asyncio.create_task(
            websocket_service.send_and_wait(type="fire_event", event_type="doorbell", retry_on_timeout=False)
        )
        await asyncio.wait_for(sent.wait(), timeout=1)
        msg_id = websocket_service.send_json.await_args.kwargs["id"]

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        websocket_service.respond_if_necessary({"type": "result", "id": msg_id, "success": True, "result": None})

        assert websocket_service._pending.entries == {}
        assert websocket_service._pending.logger.method_calls == []

    async def test_retried_read_timeout_is_not_recorded(self, websocket_service: WebsocketService) -> None:
        """A late reply to a read settles nothing, so retried reads are never recorded."""
        _time_out_immediately(websocket_service)
        single_attempt = 1  # the read goes through the retrying path, which still records nothing

        with (
            patch("hassette.core.websocket_service.MAX_RETRY_ATTEMPTS", single_attempt),
            pytest.raises(ResponseTimeoutError),
        ):
            await websocket_service.send_and_wait(type="get_states")

        assert websocket_service._pending.entries == {}

    async def test_unrecorded_late_reply_is_silent(self, websocket_service: WebsocketService) -> None:
        websocket_service._pending.logger = Mock()

        websocket_service.respond_if_necessary({"type": "result", "id": 4242, "success": True})
        websocket_service.respond_if_necessary(
            {"type": "result", "id": 4243, "success": False, "error": {"code": "not_found", "message": "x"}}
        )

        assert websocket_service._pending.logger.method_calls == []

    async def test_reconnect_clears_record(self, websocket_service: WebsocketService) -> None:
        """Msg ids belong to one connection, so partial_cleanup() drops the record."""
        _time_out_immediately(websocket_service)
        await _timed_out_write(websocket_service, type="fire_event", event_type="doorbell")
        websocket_service._ws = None
        websocket_service._recv_task = None

        await websocket_service.partial_cleanup()

        assert websocket_service._pending.entries == {}

    async def test_cleanup_clears_record(self, websocket_service: WebsocketService) -> None:
        _time_out_immediately(websocket_service)
        await _timed_out_write(websocket_service, type="fire_event", event_type="doorbell")
        await cleanup_disconnected(websocket_service)

        assert websocket_service._pending.entries == {}

    async def test_cap_evicts_oldest_entry(self, websocket_service: WebsocketService) -> None:
        _time_out_immediately(websocket_service)

        cap = 2

        with patch.object(websocket_responses_module, "TIMED_OUT_WRITE_RECORD_CAP", cap):
            ids = [
                await _timed_out_write(websocket_service, type="fire_event", event_type=f"e{i}") for i in range(cap + 1)
            ]

        assert list(websocket_service._pending.entries) == ids[1:]
