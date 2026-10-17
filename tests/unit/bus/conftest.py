"""Shared fixtures for bus unit tests."""

import contextlib
import typing
from collections.abc import Callable, Coroutine, Generator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from tests.support.factories import make_mock_parent

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig
    from hassette.bus.bus import Bus
    from hassette.bus.listeners import Listener
    from hassette.testing import HassetteHarness


@pytest.fixture
async def hassette_with_bus(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "typing.AsyncIterator[Hassette]":
    """Variant of tests.support.fixtures.hassette_with_bus scoped to function instead of module.

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


def listener_key(bus: "Bus", *, name: str = "my_listener", topic: str = "test.topic") -> tuple[str, int, str, str]:
    """Return the natural key `bus._registered_listeners` stores a listener under."""
    return (bus.parent.app_key, bus.parent.index, name, topic)


@contextlib.contextmanager
def capture_bus_spawns(
    bus: "Bus",
    *,
    add_listener: "Callable[[Listener], Coroutine[Any, Any, int]] | None" = None,
    mark_listener_cancelled: "Callable[[int], Coroutine[Any, Any, None]] | None" = None,
) -> Generator[list[Coroutine[Any, Any, Any]]]:
    """Capture coroutines passed to `bus.bus_service.task_bucket.spawn`, optionally swapping collaborators.

    Yields the list the captured coroutines are appended to; the test awaits them itself to run the
    spawned work (e.g. `mark_listener_cancelled`). `add_listener` / `mark_listener_cancelled` replace
    the matching `bus.bus_service` attribute when given. All three are restored on exit.
    """
    service = bus.bus_service
    original_add = service.add_listener
    original_mark = service.mark_listener_cancelled
    original_spawn = service.task_bucket.spawn
    spawned: list[Coroutine[Any, Any, Any]] = []

    def capture_spawn(coro: Coroutine[Any, Any, Any], **_kwargs: Any) -> MagicMock:
        spawned.append(coro)
        return MagicMock()

    if add_listener is not None:
        service.add_listener = add_listener
    if mark_listener_cancelled is not None:
        service.mark_listener_cancelled = mark_listener_cancelled
    service.task_bucket.spawn = capture_spawn
    try:
        yield spawned
    finally:
        service.add_listener = original_add
        service.mark_listener_cancelled = original_mark
        service.task_bucket.spawn = original_spawn
