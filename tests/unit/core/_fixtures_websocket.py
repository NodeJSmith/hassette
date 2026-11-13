"""WebsocketService fixtures for tests/unit/core/."""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from hassette.core.websocket_service import WebsocketService
from hassette.resources.service import Service
from tests.support.mock_hassette import make_ws_hassette_stub

HA_CONFIG: dict[str, Any] = {
    "state": "RUNNING",
    "latitude": 52.37,
    "longitude": 4.89,
    "elevation": 12,
    "time_zone": "Europe/Amsterdam",
    "unit_system": {"length": "km"},
}
"""A valid ``get_config`` reply from a Home Assistant whose core is RUNNING."""

RECV_TASK_STAND_IN_SECONDS = 10
"""How long the sleep standing in for a live recv task runs; far longer than any gate test takes."""


@pytest.fixture
async def websocket_service() -> WebsocketService:
    """Create a WebsocketService with a fully-mocked hassette stub.

    Unsealed, so a test can attach extra attributes (e.g. ``send_event``) after construction.
    """
    hassette = make_ws_hassette_stub(sealed=False)
    return WebsocketService(hassette=hassette)


async def run_cleanup(websocket_service: WebsocketService) -> None:
    """Run ``cleanup()`` with ``Service.cleanup`` stubbed, so only WebsocketService's own teardown runs."""
    with patch.object(Service, "cleanup", new=AsyncMock()):
        await websocket_service.cleanup()


async def cleanup_disconnected(websocket_service: WebsocketService) -> None:
    """Run ``cleanup()`` on a service with no socket, session, or receive task attached."""
    websocket_service._ws = None
    websocket_service._session = None
    websocket_service._recv_task = None
    await run_cleanup(websocket_service)


def stub_refused_attempts(websocket_service: WebsocketService, *, failures: int) -> AsyncMock:
    """Make ``run_connection`` raise ``ConnectionRefusedError`` ``failures`` times, then return and end ``serve()``.

    Returns the stub, so a test can assert how many attempts ``serve()`` made via ``await_count``.
    """
    run_connection = AsyncMock(side_effect=[*(ConnectionRefusedError("refused") for _ in range(failures)), None])
    websocket_service.run_connection = run_connection  # pyright: ignore[reportAttributeAccessIssue]
    return run_connection


def last_sent_msg_id(websocket_service: WebsocketService) -> int:
    """Return the ``id`` of the last frame sent through a ``send_json`` stubbed with ``AsyncMock``."""
    call = cast("AsyncMock", websocket_service.send_json).await_args
    assert call is not None, "send_json was never awaited"
    return call.kwargs["id"]


async def run_core_running_gate(websocket_service: WebsocketService) -> None:
    """Run ``wait_for_core_running`` against a live sleep standing in for the recv task."""
    recv_task = asyncio.create_task(asyncio.sleep(RECV_TASK_STAND_IN_SECONDS))
    try:
        await websocket_service.wait_for_core_running(recv_task)
    finally:
        recv_task.cancel()
        await asyncio.gather(recv_task, return_exceptions=True)
