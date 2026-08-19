"""Regression tests for #1221: subscribe_events double-subscribe on retry.

Complements test_connection.py (connection/auth), test_dispatch.py (send/dispatch),
and test_reconnect.py (disconnect/reconnect-retry).
"""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

from hassette.core.websocket_service import WebsocketService


def _make_subscribe_side_effect(ws: WebsocketService, *, succeed_on_call: int = 2) -> Callable[..., Awaitable[None]]:
    """Build a send side effect that times out subscribe_events until the Nth call."""
    call_count = 0

    async def side_effect(**data: object) -> None:
        nonlocal call_count
        call_count += 1
        if data.get("type") == "subscribe_events" and call_count >= succeed_on_call:
            ws.hassette.config.websocket.response_timeout_seconds = 5
            msg_id = data["id"]
            fut = ws._response_futures[msg_id]
            fut.set_result(None)

    return side_effect


class TestSubscribeEventsRetry:
    """Regression tests for #1221: subscribe_events double-subscribe on retry."""

    async def test_returns_confirmed_id_after_retry(self, websocket_service: WebsocketService) -> None:
        """After a timeout+retry, subscribe_events returns the ID from the successful attempt."""
        websocket_service.hassette.config.websocket.response_timeout_seconds = 0
        websocket_service._send_json_when_socket_live = AsyncMock(
            side_effect=_make_subscribe_side_effect(websocket_service, succeed_on_call=2)
        )

        sub_id = await websocket_service.subscribe_events()

        subscribe_calls = [
            c
            for c in websocket_service._send_json_when_socket_live.call_args_list
            if c.kwargs.get("type") == "subscribe_events"
        ]
        first_attempt_id = subscribe_calls[0].kwargs["id"]
        second_attempt_id = subscribe_calls[1].kwargs["id"]

        assert first_attempt_id != second_attempt_id, "Retry should use a different msg_id"
        assert sub_id == second_attempt_id, "Returned ID must match the attempt HA confirmed"
        assert sub_id != first_attempt_id, "Returned ID must not be the abandoned first attempt"

    async def test_proactively_unsubscribes_abandoned_attempt(self, websocket_service: WebsocketService) -> None:
        """On retry, the abandoned subscription is proactively unsubscribed."""
        websocket_service.hassette.config.websocket.response_timeout_seconds = 0
        websocket_service._send_json_when_socket_live = AsyncMock(
            side_effect=_make_subscribe_side_effect(websocket_service, succeed_on_call=3)
        )

        await websocket_service.subscribe_events()

        all_calls = websocket_service._send_json_when_socket_live.call_args_list
        unsubscribe_calls = [c for c in all_calls if c.kwargs.get("type") == "unsubscribe_events"]
        subscribe_calls = [c for c in all_calls if c.kwargs.get("type") == "subscribe_events"]
        first_attempt_id = subscribe_calls[0].kwargs["id"]

        assert len(unsubscribe_calls) >= 1, "Should proactively unsubscribe the abandoned attempt"
        assert unsubscribe_calls[0].kwargs["subscription"] == first_attempt_id

    async def test_cleanup_targets_confirmed_id_only(self, websocket_service: WebsocketService) -> None:
        """_subscription_ids contains only the confirmed ID, not abandoned ones."""
        websocket_service.hassette.config.websocket.response_timeout_seconds = 0
        websocket_service._send_json_when_socket_live = AsyncMock(
            side_effect=_make_subscribe_side_effect(websocket_service, succeed_on_call=2)
        )

        sub_id = await websocket_service.subscribe_events()
        websocket_service._subscription_ids.add(sub_id)

        subscribe_calls = [
            c
            for c in websocket_service._send_json_when_socket_live.call_args_list
            if c.kwargs.get("type") == "subscribe_events"
        ]
        first_attempt_id = subscribe_calls[0].kwargs["id"]

        assert sub_id in websocket_service._subscription_ids
        assert first_attempt_id not in websocket_service._subscription_ids

    async def test_no_response_futures_leak_after_retry(self, websocket_service: WebsocketService) -> None:
        """All response futures are cleaned up after retry, even for abandoned attempts."""
        websocket_service.hassette.config.websocket.response_timeout_seconds = 0
        websocket_service._send_json_when_socket_live = AsyncMock(
            side_effect=_make_subscribe_side_effect(websocket_service, succeed_on_call=2)
        )

        await websocket_service.subscribe_events()

        assert websocket_service._response_futures == {}, "All futures should be cleaned up"
