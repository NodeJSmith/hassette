"""Tier 1 pytest fixtures — ship in the wheel for app authors.

``dummy_cache`` and ``event_capture`` are registerable pytest fixtures.
``build_harness`` is a Tier 1 async context manager (not a fixture) that
starts and stops a :class:`~hassette.testing._harness.HassetteHarness`.
"""

import contextlib
from typing import TYPE_CHECKING

import pytest

from hassette.cache import DummyCache
from hassette.testing._harness import HassetteHarness
from hassette.testing.event_capture import EventCapture

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@contextlib.asynccontextmanager
async def build_harness(harness: HassetteHarness) -> "AsyncIterator[HassetteHarness]":
    """Start and stop a HassetteHarness, reloading config on exit.

    Safe to use directly inside a test body (see e.g. ``tests/integration/test_apps_env.py``)
    because ``__aexit__`` then runs inline in the test's own already-running Task rather than
    being resumed later by pytest-asyncio. It is NOT safe to drive a ``yield``-based *fixture*
    from this context manager -- see ``tests/support/harness.py`` and
    ``tests/integration/conftest.py::hassette_instance`` for why.
    """
    try:
        await harness.start()
        yield harness
    finally:
        await harness.stop()
        harness.config.reload()


@pytest.fixture
def dummy_cache() -> DummyCache:
    """A fresh `DummyCache` instance for injecting into an App's `cache=` constructor parameter.

    Isolates cache state per test -- no temp directory management, no SQLite files.
    """
    return DummyCache()


@pytest.fixture
def event_capture() -> EventCapture:
    """A fresh `EventCapture` for intercepting `send_event` calls. Call `install(target)` to arm it."""
    return EventCapture()
