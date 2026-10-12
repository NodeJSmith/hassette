"""WebsocketService test-double helpers."""

from collections.abc import Coroutine
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from hassette.testing._ws_mocks import make_task_bucket_spawn_stub

if TYPE_CHECKING:
    from hassette.core.websocket_service import WebsocketService


def stub_connect_sequence(websocket_service: "WebsocketService") -> list[Coroutine]:
    """Stub the task bucket and event subscription so the real connect sequence can run.

    Replaces ``task_bucket`` with a mock whose ``spawn`` records coroutines instead of running them,
    and ``subscribe_events`` with a mock returning subscription id 42. Returns the recorded
    coroutines, which ``run_connect_sequence`` closes. A test that needs a different subscription
    outcome assigns its own ``subscribe_events`` afterwards.
    """
    spawned_coros, spawn_stub = make_task_bucket_spawn_stub()
    websocket_service.task_bucket = MagicMock()  # pyright: ignore[reportAttributeAccessIssue]
    websocket_service.task_bucket.spawn = spawn_stub
    websocket_service.subscribe_events = AsyncMock(return_value=42)  # pyright: ignore[reportAttributeAccessIssue]
    return spawned_coros
