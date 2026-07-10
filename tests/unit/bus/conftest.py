"""Shared fixtures for bus unit tests."""

import contextlib
import typing
from collections.abc import Generator
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.test_utils.factories import make_mock_parent

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
    """Variant of test_utils.fixtures.hassette_with_bus scoped to function instead of module.

    Bus unit tests mutate listener state per-test (e.g. `bus.parent`, direct
    `add_listener` patching in `mock_add_listener`), so each test needs its own
    harness instead of sharing one across the module. Yields the raw `Hassette`
    instance rather than the `HassetteHarness` wrapper for direct access to `_bus`.
    """
    async with hassette_harness(test_config).with_bus() as harness:
        yield cast("Hassette", harness.hassette)


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource with a mock parent that has an app_key."""
    bus = hassette_with_bus._bus  # pyright: ignore[reportReturnType]
    bus.parent = make_mock_parent(app_key="test_app", index=0, source_tier="app")
    return bus  # pyright: ignore[reportReturnType]


@contextlib.contextmanager
def mock_add_listener(bus: "Bus") -> Generator[Mock]:
    """Replace bus.bus_service.add_listener with an AsyncMock, restoring on exit.

    Default return is 1 (a fake db_id). Unlike the real add_listener, this does NOT call
    listener.mark_registered, so listeners stay at db_id=None and removal paths take the
    no-spawn branch. Tests that assert on the mark_listener_cancelled spawn must use an
    inline mock that calls mark_registered (see test_once_listener_tracking.py).
    """
    mock = AsyncMock(return_value=1)
    original = bus.bus_service.add_listener
    bus.bus_service.add_listener = mock
    try:
        yield mock
    finally:
        bus.bus_service.add_listener = original
