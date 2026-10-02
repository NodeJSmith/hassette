"""WebsocketService.send_and_wait: sent-but-unanswered commands raise the OutcomeUnknownError family.

A response timeout raises ``ResponseTimeoutError`` and a disconnect while waiting raises
``ResponseLostError``. Both mean the command reached (or may have reached) Home Assistant, so it
may or may not have applied. Non-retried sends go out exactly once; a late reply to a timed-out
non-retried send is matched against a bounded record and logged so the outcome is settled.

Log assertions mock ``websocket_service.logger`` rather than using caplog: another test in the
same process can disable propagation on the ``hassette`` logger, which would blind caplog.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from hassette.core import websocket_service as websocket_service_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import (
    FailedMessageError,
    OutcomeUnknownError,
    ResponseLostError,
    ResponseTimeoutError,
    RetryableConnectionClosedError,
)
from hassette.resources.service import Service


def _rendered(call) -> str:
    """The message a mocked logger call would have produced (%-style args applied)."""
    msg, *args = call.args
    return msg % tuple(args)


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

        with patch("hassette.core.websocket_service.MAX_RETRY_ATTEMPTS", 2), pytest.raises(ResponseTimeoutError):
            await websocket_service.send_and_wait(type="get_states")

        assert websocket_service.send_json.await_count == 2

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

        async def drop_connection(**data):
            websocket_service._response_futures[data["id"]].set_exception(
                RetryableConnectionClosedError("WebSocket disconnected", close_code=1006)
            )

        websocket_service.send_json = AsyncMock(side_effect=drop_connection)

        with pytest.raises(ResponseLostError) as exc_info:
            await websocket_service.send_and_wait(type="get_states")

        assert websocket_service.send_json.await_count == 1
        exc = exc_info.value
        assert isinstance(exc, OutcomeUnknownError)
        assert isinstance(exc, RetryableConnectionClosedError)
        assert not isinstance(exc, FailedMessageError)
        assert exc.close_code == 1006
        assert "get_states" in str(exc)

    async def test_reconnect_cleanup_fails_pending_send_as_response_lost(
        self, websocket_service: WebsocketService
    ) -> None:
        """partial_cleanup() (reconnect) fails a waiting send, which surfaces as ResponseLostError."""
        sent = asyncio.Event()
        websocket_service.send_json = AsyncMock(side_effect=lambda **_: sent.set())
        websocket_service._ws = None
        websocket_service._recv_task = None

        task = asyncio.create_task(
            websocket_service.send_and_wait(type="call_service", domain="counter", retry_on_timeout=False)
        )
        await asyncio.wait_for(sent.wait(), timeout=1)

        await websocket_service.partial_cleanup()

        with pytest.raises(ResponseLostError):
            await task

    async def test_disconnect_logs_warning_when_raised(self, websocket_service: WebsocketService) -> None:
        async def drop_connection(**data):
            websocket_service._response_futures[data["id"]].set_exception(
                RetryableConnectionClosedError("WebSocket disconnected")
            )

        websocket_service.send_json = AsyncMock(side_effect=drop_connection)
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
        websocket_service.logger = Mock()

        websocket_service.respond_if_necessary({"type": "result", "id": msg_id, "success": True, "result": None})

        websocket_service.logger.warning.assert_not_called()
        websocket_service.logger.info.assert_called_once()
        rendered = _rendered(websocket_service.logger.info.call_args)
        assert "fire_event" in rendered
        assert str(msg_id) in rendered
        assert msg_id not in websocket_service._timed_out_writes

    async def test_late_failure_logs_warning_and_drops_entry(self, websocket_service: WebsocketService) -> None:
        """A late failure settles a timed-out write as not applied."""
        _time_out_immediately(websocket_service)
        msg_id = await _timed_out_write(websocket_service, type="counter/delete", counter_id="motion")
        websocket_service.logger = Mock()

        websocket_service.respond_if_necessary(
            {"type": "result", "id": msg_id, "success": False, "error": {"code": "not_found", "message": "x"}}
        )

        websocket_service.logger.info.assert_not_called()
        websocket_service.logger.warning.assert_called_once()
        rendered = _rendered(websocket_service.logger.warning.call_args)
        assert "counter/delete" in rendered
        assert str(msg_id) in rendered
        assert msg_id not in websocket_service._timed_out_writes

    async def test_retried_read_timeout_is_not_recorded(self, websocket_service: WebsocketService) -> None:
        """A late reply to a read settles nothing, so retried reads are never recorded."""
        _time_out_immediately(websocket_service)

        with patch("hassette.core.websocket_service.MAX_RETRY_ATTEMPTS", 1), pytest.raises(ResponseTimeoutError):
            await websocket_service.send_and_wait(type="get_states")

        assert len(websocket_service._timed_out_writes) == 0

    async def test_unrecorded_late_reply_is_silent(self, websocket_service: WebsocketService) -> None:
        websocket_service.logger = Mock()

        websocket_service.respond_if_necessary({"type": "result", "id": 4242, "success": True})
        websocket_service.respond_if_necessary(
            {"type": "result", "id": 4243, "success": False, "error": {"code": "not_found", "message": "x"}}
        )

        assert websocket_service.logger.method_calls == []

    async def test_reconnect_clears_record(self, websocket_service: WebsocketService) -> None:
        """Msg ids belong to one connection, so partial_cleanup() drops the record."""
        _time_out_immediately(websocket_service)
        await _timed_out_write(websocket_service, type="fire_event", event_type="doorbell")
        websocket_service._ws = None
        websocket_service._recv_task = None

        await websocket_service.partial_cleanup()

        assert len(websocket_service._timed_out_writes) == 0

    async def test_cleanup_clears_record(self, websocket_service: WebsocketService) -> None:
        _time_out_immediately(websocket_service)
        await _timed_out_write(websocket_service, type="fire_event", event_type="doorbell")
        websocket_service._ws = None
        websocket_service._session = None
        websocket_service._recv_task = None

        with patch.object(Service, "cleanup", new=AsyncMock()):
            await websocket_service.cleanup()

        assert len(websocket_service._timed_out_writes) == 0

    async def test_cap_evicts_oldest_entry(self, websocket_service: WebsocketService) -> None:
        _time_out_immediately(websocket_service)

        with patch.object(websocket_service_module, "TIMED_OUT_WRITE_RECORD_CAP", 2):
            ids = [await _timed_out_write(websocket_service, type="fire_event", event_type=f"e{i}") for i in range(3)]

        assert list(websocket_service._timed_out_writes) == ids[1:]
