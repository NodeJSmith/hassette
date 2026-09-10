"""WebsocketService fixtures for tests/unit/core/."""

import pytest

from hassette.core.websocket_service import WebsocketService
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
