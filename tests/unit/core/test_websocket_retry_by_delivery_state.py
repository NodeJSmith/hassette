"""``send_and_wait`` and ``subscribe_events`` retry by delivery state: only a response timeout is retried.

A not-sent command means the connection just dropped (reconnect is the recovery), a rejected one would be
refused again, and a lost one may already have applied.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest

import hassette.core.websocket_io as websocket_io_module
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import (
    CommandNotSentError,
    CommandRejectedError,
    ResponseLostError,
    ResponseTimeoutError,
    WebsocketClosedError,
)
from tests.support.websocket_mocks import awaited_future

ATTEMPTS = 3

Failure = Callable[[WebsocketService, dict[str, Any]], Awaitable[None]]


async def no_reply(_ws: WebsocketService, _data: dict[str, Any]) -> None:
    """The frame goes out and nothing answers; RESPONSE_TIMEOUT_SECONDS is 0, so the wait times out."""


async def not_sent(_ws: WebsocketService, _data: dict[str, Any]) -> None:
    raise CommandNotSentError("not sent")


async def rejected(ws: WebsocketService, data: dict[str, Any]) -> None:
    """An HA error reply without a code: the case the old ``code is None`` rule used to retry."""
    awaited_future(ws, data["id"]).set_exception(CommandRejectedError("refused", code=None))


async def lost(ws: WebsocketService, data: dict[str, Any]) -> None:
    awaited_future(ws, data["id"]).set_exception(WebsocketClosedError("WebSocket disconnected"))


# (failure, class send_and_wait raises, class subscribe_events raises, sends). A lost subscription stays
# the internal close signal: only the connect sequence calls subscribe_events, and its reconnect loop
# handles any HassetteError.
CASES = [
    pytest.param(no_reply, ResponseTimeoutError, ResponseTimeoutError, ATTEMPTS, id="timeout_retried"),
    pytest.param(not_sent, CommandNotSentError, CommandNotSentError, 1, id="not_sent"),
    pytest.param(rejected, CommandRejectedError, CommandRejectedError, 1, id="codeless_rejection"),
    pytest.param(lost, ResponseLostError, WebsocketClosedError, 1, id="lost"),
]


@pytest.fixture
def stub_failure(websocket_service: WebsocketService, monkeypatch: pytest.MonkeyPatch):
    """Replace ``send_json`` with one that applies a failure; a zero response timeout makes ``no_reply`` time out."""
    monkeypatch.setattr(websocket_io_module, "RESPONSE_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(websocket_io_module, "MAX_RETRY_ATTEMPTS", ATTEMPTS)
    monkeypatch.setattr(websocket_io_module, "wait_exponential_jitter", lambda: lambda _state: 0)

    def install(failure: Failure) -> AsyncMock:
        async def send(**data: Any) -> None:
            if data.get("type") != "unsubscribe_events":
                await failure(websocket_service, data)

        websocket_service.send_json = AsyncMock(side_effect=send)
        return websocket_service.send_json

    return install


def sends_of(send_json: AsyncMock, command_type: str) -> int:
    return sum(1 for call in send_json.await_args_list if call.kwargs.get("type") == command_type)


@pytest.mark.parametrize(("failure", "raised", "_subscribe_raised", "sends"), CASES)
async def test_send_and_wait_retries_only_timeouts(
    websocket_service: WebsocketService,
    stub_failure,
    failure: Failure,
    raised: type[Exception],
    _subscribe_raised: type[Exception],
    sends: int,
) -> None:
    send_json = stub_failure(failure)

    with pytest.raises(raised):
        await websocket_service.send_and_wait(type="get_states")

    assert sends_of(send_json, "get_states") == sends


@pytest.mark.parametrize(("failure", "_raised", "subscribe_raised", "sends"), CASES)
async def test_subscribe_events_retries_only_timeouts(
    websocket_service: WebsocketService,
    stub_failure,
    failure: Failure,
    _raised: type[Exception],
    subscribe_raised: type[Exception],
    sends: int,
) -> None:
    send_json = stub_failure(failure)

    with pytest.raises(subscribe_raised):
        await websocket_service.subscribe_events("state_changed")

    assert sends_of(send_json, "subscribe_events") == sends
