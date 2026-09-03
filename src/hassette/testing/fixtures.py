"""Tier 1 pytest fixtures — ship in the wheel for app authors.

``dummy_cache`` and ``event_capture`` are registerable pytest fixtures. This
module imports ``pytest`` at module level, so importing any name from it
requires the ``test`` extra. ``build_harness`` (a Tier 1 async context
manager, not a fixture) lives in the sibling ``build_harness`` module
instead, so importing it — or any other Tier 1 symbol via ``hassette.testing``
— does not pull in ``pytest``.
"""

import pytest

from hassette.cache import DummyCache
from hassette.testing.event_capture import EventCapture


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
