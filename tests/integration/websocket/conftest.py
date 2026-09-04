"""Shared fixtures for websocket service integration tests.

Complements test_connection.py, test_dispatch.py, test_reconnect.py, and
test_subscribe_events_retry.py.
"""

from typing import TYPE_CHECKING

import pytest

from hassette.core.websocket_service import WebsocketService

if TYPE_CHECKING:
    from hassette.testing import HassetteHarness


@pytest.fixture
def websocket_service(hassette_with_bus: "HassetteHarness") -> WebsocketService:
    """Create a fresh websocket service instance for each test."""
    hassette = hassette_with_bus.hassette
    return WebsocketService(hassette, parent=hassette)
