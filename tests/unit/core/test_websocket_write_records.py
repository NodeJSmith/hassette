"""A recorded write's pending-reply entry owns its record from registration (spec 149 D1, D2, D9).

The reply, ``fail_all`` or eviction calls the entry's resolve callback exactly once; the caller only
stops waiting. Log assertions mock ``_pending.logger`` (see test_websocket_outcome_unknown.py for why).
"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

import hassette.core.websocket_io as websocket_io_module
from hassette.core import websocket_responses as websocket_responses_module
from hassette.core.pipeline_counters import PipelineCounter, PipelineCounters
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import CommandNotSentError, CommandRejectedError, ResponseLostError, ResponseTimeoutError

from .conftest import last_sent_msg_id, run_cleanup


class Calls:
    """A resolve callback that records each call as ``(outcome, details)``, leaving out details passed as None."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, outcome: Any, **details: Any) -> None:
        self.calls.append((outcome, {key: value for key, value in details.items() if value is not None}))

    @property
    def outcomes(self) -> list[str]:
        return [outcome for outcome, _ in self.calls]


def success_reply(msg_id: int, context_id: str = "ctx-1") -> dict[str, Any]:
    return {"type": "result", "id": msg_id, "success": True, "result": {"context": {"id": context_id}}}


def error_reply(msg_id: int) -> dict[str, Any]:
    return {"type": "result", "id": msg_id, "success": False, "error": {"code": "not_found", "message": "no service"}}


def pending_log(ws: WebsocketService) -> Mock:
    """The ``Mock`` the ``ws`` fixture put in place of ``PendingResponses``' logger."""
    return cast("Mock", ws._pending.logger)


@pytest.fixture
def ws(websocket_service: WebsocketService) -> WebsocketService:
    websocket_service._pending.logger = Mock()
    websocket_service._pending.counters = PipelineCounters()
    return websocket_service


async def send_recorded(ws: WebsocketService, on_resolve: Calls, **data: Any) -> "asyncio.Task[Any]":
    """Start a recorded awaited write and return its task once the frame went out."""
    sent = asyncio.Event()
    ws.send_json = AsyncMock(side_effect=lambda **_: sent.set())
    task = asyncio.create_task(ws.send_and_wait(retry_on_timeout=False, on_resolve=on_resolve, **data))
    await asyncio.wait_for(sent.wait(), timeout=1)
    return task


class TestAwaitedWrite:
    async def test_reply_resolves_record_and_caller(self, ws: WebsocketService) -> None:
        on_resolve = Calls()
        task = await send_recorded(ws, on_resolve, type="fire_event", event_type="doorbell")

        ws.respond_if_necessary(success_reply(last_sent_msg_id(ws)))

        assert await task == {"context": {"id": "ctx-1"}}
        assert on_resolve.calls == [("success", {"context_id": "ctx-1"})]
        assert ws._pending.entries == {}

    async def test_rejection_resolves_record_and_raises(self, ws: WebsocketService) -> None:
        on_resolve = Calls()
        task = await send_recorded(ws, on_resolve, type="fire_event", event_type="doorbell")

        ws.respond_if_necessary(error_reply(last_sent_msg_id(ws)))

        with pytest.raises(CommandRejectedError):
            await task
        assert on_resolve.calls == [("rejected", {"error_code": "not_found", "error_message": "no service"})]
        pending_log(ws).warning.assert_not_called()

    async def test_timeout_leaves_record_to_the_late_reply(
        self, ws: WebsocketService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(websocket_io_module, "RESPONSE_TIMEOUT_SECONDS", 0)
        on_resolve = Calls()
        ws.send_json = AsyncMock()

        with pytest.raises(ResponseTimeoutError):
            await ws.send_and_wait(retry_on_timeout=False, on_resolve=on_resolve, type="fire_event", event_type="x")
        assert on_resolve.calls == []
        assert ws._pending.background_count == 1

        ws.respond_if_necessary(success_reply(last_sent_msg_id(ws)))

        assert on_resolve.outcomes == ["success"]
        pending_log(ws).info.assert_called_once()  # today's late-reply line, not the rejected-call WARNING
        assert ws._pending.background_count == 0

    async def test_cancelled_write_resolves_when_the_connection_ends(self, ws: WebsocketService) -> None:
        on_resolve = Calls()
        task = await send_recorded(ws, on_resolve, type="fire_event", event_type="doorbell")

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert on_resolve.calls == []
        ws._pending.fail_all()

        assert on_resolve.outcomes == ["connection_lost"]

    async def test_disconnect_while_waiting_resolves_connection_lost(self, ws: WebsocketService) -> None:
        on_resolve = Calls()
        task = await send_recorded(ws, on_resolve, type="fire_event", event_type="doorbell")

        ws._pending.fail_all()

        with pytest.raises(ResponseLostError):
            await task
        assert on_resolve.outcomes == ["connection_lost"]

    async def test_failed_send_drops_the_entry_unresolved(self, ws: WebsocketService) -> None:
        """The caller records not_sent; the entry must not also resolve the record."""
        on_resolve = Calls()
        ws.send_json = AsyncMock(side_effect=CommandNotSentError("down"))

        with pytest.raises(CommandNotSentError):
            await ws.send_and_wait(retry_on_timeout=False, on_resolve=on_resolve, type="fire_event", event_type="x")
        ws._pending.fail_all()

        assert on_resolve.calls == []
        assert ws._pending.entries == {}

    async def test_record_requires_a_single_attempt(self, ws: WebsocketService) -> None:
        with pytest.raises(ValueError, match="retry_on_timeout=False"):
            await ws.send_and_wait(on_resolve=Calls(), type="fire_event", event_type="x")


class TestFireAndForget:
    async def test_reply_during_the_send_is_not_dropped(self, ws: WebsocketService) -> None:
        """The entry is registered before sending, so a reply racing send_json still resolves the record."""
        on_resolve = Calls()

        async def reply_while_sending(**data: Any) -> None:
            ws.respond_if_necessary(success_reply(data["id"], "ctx-fast"))

        ws.send_json = AsyncMock(side_effect=reply_while_sending)

        await ws.send_fire_and_forget(on_resolve, type="call_service", domain="light", service="turn_on")

        assert on_resolve.calls == [("success", {"context_id": "ctx-fast"})]
        assert ws._pending.entries == {}
        assert ws._pending.background_count == 0

    async def test_rejection_resolves_without_a_late_reply_line(self, ws: WebsocketService) -> None:
        on_resolve = Calls()
        ws.send_json = AsyncMock()

        await ws.send_fire_and_forget(on_resolve, type="call_service", domain="light", service="turn_on")
        ws.respond_if_necessary(error_reply(last_sent_msg_id(ws)))

        assert on_resolve.outcomes == ["rejected"]
        pending_log(ws).warning.assert_not_called()
        pending_log(ws).info.assert_not_called()

    async def test_failed_send_drops_the_entry_unresolved(self, ws: WebsocketService) -> None:
        on_resolve = Calls()
        ws.send_json = AsyncMock(side_effect=CommandNotSentError("down"))

        with pytest.raises(CommandNotSentError):
            await ws.send_fire_and_forget(on_resolve, type="call_service", domain="light", service="turn_on")

        assert on_resolve.calls == []
        assert ws._pending.entries == {}
        assert ws._pending.background_count == 0

    async def test_teardown_resolves_every_entry_even_when_one_callback_fails(self, ws: WebsocketService) -> None:
        ws.send_json = AsyncMock()
        broken = MagicMock(side_effect=RuntimeError("db gone"))
        healthy = Calls()
        await ws.send_fire_and_forget(broken, type="call_service")
        await ws.send_fire_and_forget(healthy, type="call_service")

        await run_cleanup(ws)

        assert healthy.outcomes == ["connection_lost"]
        pending_log(ws).exception.assert_called_once()
        assert ws._pending.entries == {}


class TestEviction:
    CAP = 2

    async def test_earliest_sent_background_entry_is_evicted_as_unresolved(self, ws: WebsocketService) -> None:
        ws.send_json = AsyncMock()
        callbacks = [Calls() for _ in range(self.CAP + 2)]

        with patch.object(websocket_responses_module, "BACKGROUND_ENTRY_CAP", self.CAP):
            for cb in callbacks:
                await ws.send_fire_and_forget(cb, type="call_service")

        assert [cb.outcomes for cb in callbacks] == [["unresolved"], ["unresolved"], [], []]
        assert callbacks[0].calls == [("unresolved", {})]
        assert ws._pending.background_count == self.CAP
        assert ws._pending.counters.get(PipelineCounter.API_WRITE_TRACKING_EVICTED) == 2
        pending_log(ws).warning.assert_called_once()  # one WARNING per episode

    async def test_awaited_entry_is_never_evicted_or_counted(self, ws: WebsocketService) -> None:
        waiting = Calls()
        task = await send_recorded(ws, waiting, type="fire_event", event_type="slow")
        ws.send_json = AsyncMock()

        with patch.object(websocket_responses_module, "BACKGROUND_ENTRY_CAP", self.CAP):
            for _ in range(self.CAP + 1):
                await ws.send_fire_and_forget(Calls(), type="call_service")

        assert waiting.calls == []
        assert ws._pending.background_count == self.CAP
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_abandoned_entry_keeps_its_send_order(self, ws: WebsocketService) -> None:
        """An awaited write that later loses its caller is older than writes sent after it, so it goes first."""
        first = Calls()
        task = await send_recorded(ws, first, type="fire_event", event_type="first")
        ws.send_json = AsyncMock()
        later = Calls()
        await ws.send_fire_and_forget(later, type="call_service")

        with patch.object(websocket_responses_module, "BACKGROUND_ENTRY_CAP", 1):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert first.outcomes == ["unresolved"]
        assert later.outcomes == []
