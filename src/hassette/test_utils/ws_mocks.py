"""WebSocket stub helpers for tests.

`build_fake_ws()` returns a thin aiohttp ClientWebSocketResponse stub
with no Home Assistant protocol knowledge. Tests that need protocol
behaviour (authenticate, subscribe_events) stub those collaborators
separately.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from aiohttp import ClientWebSocketResponse


def build_fake_ws(*, is_closed: bool = False) -> ClientWebSocketResponse:
    """Return a lightweight websocket stub with adjustable state.

    Args:
        is_closed: Whether the stub reports itself as closed via `.closed`.

    Returns:
        A `ClientWebSocketResponse` stub whose `send_json`, `receive_json`,
        `receive`, and `close` methods are `AsyncMock` instances.
    """
    fake_ws = SimpleNamespace()
    fake_ws.closed = is_closed
    fake_ws.send_json = AsyncMock()
    fake_ws.receive_json = AsyncMock()
    fake_ws.receive = AsyncMock()
    fake_ws.close = AsyncMock()
    return cast("ClientWebSocketResponse", fake_ws)
