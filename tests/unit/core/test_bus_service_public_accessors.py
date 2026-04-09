"""Unit tests for BusService public accessor properties.

Tests cover:

- ``is_dispatch_idle`` — returns True when ``_dispatch_idle_event`` is set,
  False when it is cleared.
- ``dispatch_pending_count`` — returns the current value of ``_dispatch_pending``.

These properties are the recommended public surface for drain helpers and test
infrastructure. The tests verify that they delegate to the correct private fields
without adding any extra logic.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.bus_service import BusService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hassette_mock() -> MagicMock:
    """Return a MagicMock Hassette with just enough attributes for BusService.__init__."""
    hassette = MagicMock()
    hassette.config.bus_service_log_level = "DEBUG"
    hassette.config.log_level = "DEBUG"
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.bus_excluded_domains = []
    hassette.config.bus_excluded_entities = []
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
def bus_service() -> BusService:
    """Construct a BusService backed by mocks, ready for accessor tests."""
    hassette = _make_hassette_mock()
    stream = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock()
    return BusService(hassette, stream=stream, executor=executor)


# ---------------------------------------------------------------------------
# is_dispatch_idle
# ---------------------------------------------------------------------------


def test_is_dispatch_idle_true_when_no_pending(bus_service: BusService) -> None:
    """is_dispatch_idle is True when the idle event is set (no dispatches in flight).

    BusService initialises with the idle event set, so a fresh instance must
    report idle.
    """
    assert bus_service._dispatch_idle_event.is_set()
    assert bus_service.is_dispatch_idle is True


def test_is_dispatch_idle_false_when_event_is_cleared(bus_service: BusService) -> None:
    """is_dispatch_idle is False when the idle event has been cleared.

    Simulates the state during an active dispatch by clearing the event
    directly, matching what BusService.dispatch() does internally.
    """
    bus_service._dispatch_idle_event.clear()
    assert bus_service.is_dispatch_idle is False


def test_is_dispatch_idle_delegates_to_event_not_pending_count(bus_service: BusService) -> None:
    """is_dispatch_idle reads _dispatch_idle_event, not _dispatch_pending.

    Verifies that the property is a pure delegate — setting pending to 0
    while the event is cleared still returns False (event is authoritative).
    """
    bus_service._dispatch_idle_event.clear()
    bus_service._dispatch_pending = 0
    # Event is cleared, so idle must be False regardless of the counter
    assert bus_service.is_dispatch_idle is False

    # Setting the event makes it True again
    bus_service._dispatch_idle_event.set()
    assert bus_service.is_dispatch_idle is True


# ---------------------------------------------------------------------------
# dispatch_pending_count
# ---------------------------------------------------------------------------


def test_dispatch_pending_count_zero_for_fresh_service(bus_service: BusService) -> None:
    """dispatch_pending_count is 0 for a freshly constructed BusService."""
    assert bus_service.dispatch_pending_count == 0


def test_dispatch_pending_count_reflects_current_value(bus_service: BusService) -> None:
    """dispatch_pending_count returns the current value of _dispatch_pending."""
    bus_service._dispatch_pending = 3
    assert bus_service.dispatch_pending_count == 3

    bus_service._dispatch_pending = 0
    assert bus_service.dispatch_pending_count == 0


def test_dispatch_pending_count_tracks_increments(bus_service: BusService) -> None:
    """dispatch_pending_count updates as _dispatch_pending changes."""
    for expected in range(1, 6):
        bus_service._dispatch_pending = expected
        assert bus_service.dispatch_pending_count == expected
