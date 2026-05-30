"""Shared fixtures for bus unit tests."""

import contextlib
import typing
from collections.abc import Generator
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import Hassette, HassetteConfig
    from hassette.bus.bus import Bus
    from hassette.test_utils.harness import HassetteHarness


@pytest.fixture
async def hassette_with_bus(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "typing.AsyncIterator[Hassette]":
    """Function-scoped bus harness for isolation between tests."""
    async with hassette_harness(test_config).with_bus() as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource with a mock parent that has an app_key."""
    b = hassette_with_bus._bus  # pyright: ignore[reportReturnType]
    mock_parent = Mock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.unique_name = "test_app.0"
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestApp"
    b.parent = mock_parent
    return b  # pyright: ignore[reportReturnType]


@contextlib.contextmanager
def mock_add_listener(bus: "Bus") -> Generator[Mock]:
    """Replace bus.bus_service.add_listener with an AsyncMock, restoring on exit.

    Default return is 1 (a fake db_id). Tests that need a specific db_id
    should set ``add_mock.return_value`` explicitly.
    """
    mock = AsyncMock(return_value=1)
    original = bus.bus_service.add_listener
    bus.bus_service.add_listener = mock
    try:
        yield mock
    finally:
        bus.bus_service.add_listener = original
