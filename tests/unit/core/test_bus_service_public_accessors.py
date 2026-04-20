"""Unit tests for BusService public accessor properties.

Tests cover:

- ``is_dispatch_idle`` — returns True when ``_dispatch_idle_event`` is set,
  False when it is cleared.
- ``dispatch_pending_count`` — returns the current value of ``_dispatch_pending``.
- ``drain_framework_registrations()`` — drains only framework keys.

These properties are the recommended public surface for drain helpers and test
infrastructure. The tests verify that they delegate to the correct private fields
without adding any extra logic.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.bus_service import BusService
from hassette.core.registration_tracker import RegistrationTracker
from hassette.types.types import FRAMEWORK_APP_KEY, FRAMEWORK_APP_KEY_PREFIX

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

    Direct private access is acceptable here — we are testing that the public
    properties delegate correctly to these fields. Production code must use
    ``is_dispatch_idle`` and ``dispatch_pending_count``.
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


def test_is_dispatch_idle_is_authoritative_over_pending_count(bus_service: BusService) -> None:
    """is_dispatch_idle reads the idle event, not the pending counter.

    When the event is set but _dispatch_pending is non-zero, the property must
    still return True — the event is the authoritative idle signal. This covers
    the inverse inconsistency case where a counter drift or concurrent update
    could produce a misleading False result if the wrong field were consulted.
    """
    # Set up the inconsistent state: counter says "busy", event says "idle"
    bus_service._dispatch_pending = 1
    bus_service._dispatch_idle_event.set()
    # Event is authoritative: is_dispatch_idle should be True
    assert bus_service.is_dispatch_idle is True
    # Counter is still 1 but is not authoritative for the idle check
    assert bus_service.dispatch_pending_count == 1


# ---------------------------------------------------------------------------
# drain_framework_registrations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_framework_registrations_drains_only_framework_keys(bus_service: BusService) -> None:
    """drain_framework_registrations() awaits only keys matching is_framework_key()."""
    drained: list[str] = []

    bus_service._reg_tracker = RegistrationTracker()
    bus_service._reg_tracker._tasks["my_app"] = []
    bus_service._reg_tracker._tasks[FRAMEWORK_APP_KEY] = []
    bus_service._reg_tracker._tasks[f"{FRAMEWORK_APP_KEY_PREFIX}service_watcher"] = []
    bus_service._reg_tracker._tasks[f"{FRAMEWORK_APP_KEY_PREFIX}core"] = []

    async def recording_await(app_key: str) -> None:
        drained.append(app_key)

    bus_service.await_registrations_complete = recording_await  # pyright: ignore[reportAttributeAccessIssue]

    await bus_service.drain_framework_registrations()

    assert "my_app" not in drained
    assert FRAMEWORK_APP_KEY in drained
    assert f"{FRAMEWORK_APP_KEY_PREFIX}service_watcher" in drained
    assert f"{FRAMEWORK_APP_KEY_PREFIX}core" in drained


@pytest.mark.asyncio
async def test_drain_framework_registrations_uses_list_snapshot(bus_service: BusService) -> None:
    """drain_framework_registrations() snapshots keys before iterating to avoid RuntimeError."""
    drained: list[str] = []
    framework_key = f"{FRAMEWORK_APP_KEY_PREFIX}core"

    bus_service._reg_tracker = RegistrationTracker()
    bus_service._reg_tracker._tasks[framework_key] = []

    async def recording_await(app_key: str) -> None:
        drained.append(app_key)
        bus_service._reg_tracker._tasks[f"{FRAMEWORK_APP_KEY_PREFIX}new_key"] = []

    bus_service.await_registrations_complete = recording_await  # pyright: ignore[reportAttributeAccessIssue]

    await bus_service.drain_framework_registrations()
    assert framework_key in drained
