"""WebSocket stub helpers for tests.

`build_fake_ws()` returns a thin aiohttp ClientWebSocketResponse stub
with no Home Assistant protocol knowledge. Tests that need protocol
behaviour (authenticate, subscribe_events) stub those collaborators
separately.
"""

import asyncio
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

from aiohttp import ClientWebSocketResponse

from hassette.resources.lifecycle import mark_ready
from hassette.test_utils.config import TEST_TOTAL_TIMEOUT_SECONDS
from hassette.types.enums import ConnectionState

if TYPE_CHECKING:
    from hassette.core.websocket_service import WebsocketService


def build_fake_ws(*, is_closed: bool = False, close_code: int | None = None) -> ClientWebSocketResponse:
    """Return a lightweight websocket stub with adjustable state.

    Args:
        is_closed: Whether the stub reports itself as closed via `.closed`.
        close_code: The value the stub reports via `.close_code`.

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
    fake_ws.close_code = close_code
    return cast("ClientWebSocketResponse", fake_ws)


def _configure_websocket_external_readiness_primitives(target: Any, *, generation: int = 1) -> None:
    """Stamp the common externally-ready websocket primitives on a real service or test double."""
    connected_event = getattr(target, "_connected_event", None)
    if not isinstance(connected_event, asyncio.Event):
        connected_event = asyncio.Event()
        target._connected_event = connected_event
    connected_event.set()

    send_ready_event = getattr(target, "_send_ready_event", None)
    if not isinstance(send_ready_event, asyncio.Event):
        send_ready_event = asyncio.Event()
        target._send_ready_event = send_ready_event
    send_ready_event.set()

    target._connected_generation = generation
    target._connected_at = time.monotonic()
    target._connected_signal_active = True


def configure_ready_websocket_mock(websocket_service: Mock, *, generation: int = 1) -> None:
    """Configure a websocket-service mock to look externally ready."""
    websocket_service.ready_event = asyncio.Event()
    websocket_service.ready_event.set()
    _configure_websocket_external_readiness_primitives(websocket_service, generation=generation)
    websocket_service.is_connected = True
    websocket_service.has_ever_connected = True
    websocket_service.get_connected_generation = Mock(return_value=generation)
    websocket_service.total_timeout_seconds = TEST_TOTAL_TIMEOUT_SECONDS
    websocket_service.wait_connected = AsyncMock(return_value=True)
    websocket_service.wait_connected_generation = AsyncMock(return_value=generation)
    websocket_service.wait_initial_connection = AsyncMock(return_value=True)


def mark_websocket_service_connected(websocket_service: "WebsocketService", *, reason: str) -> None:
    """Mark a WebsocketService externally ready for tests.

    For a heavier-weight alternative that fires a real event through the bus, see
    ``AppTestHarness.simulate_websocket_connected()`` in ``hassette.test_utils.simulation``.
    """
    mark_ready(websocket_service, reason=reason)
    websocket_service._connection_state = ConnectionState.CONNECTED
    websocket_service._ever_connected = True
    _configure_websocket_external_readiness_primitives(websocket_service)
