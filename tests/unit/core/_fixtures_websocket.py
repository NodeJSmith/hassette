"""WebsocketService fixtures for tests/unit/core/."""

from unittest.mock import AsyncMock, patch

import pytest

from hassette.core.websocket_service import WebsocketService
from hassette.resources.service import Service
from tests.support.mock_hassette import make_ws_hassette_stub


@pytest.fixture
async def websocket_service() -> WebsocketService:
    """Create a WebsocketService with a fully-mocked hassette stub.

    Unsealed, so a test can attach extra attributes (e.g. ``send_event``) after construction.
    Lifecycle transitions are non-strict -- use ``websocket_service_strict`` for the strict variant.
    """
    hassette = make_ws_hassette_stub(sealed=False)
    return WebsocketService(hassette=hassette)


@pytest.fixture
async def websocket_service_strict() -> WebsocketService:
    """Create a WebsocketService with strict_lifecycle=True, which raises on an invalid transition."""
    hassette = make_ws_hassette_stub(strict_lifecycle=True, sealed=False)
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
