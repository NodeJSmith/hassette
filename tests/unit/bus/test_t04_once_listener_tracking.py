"""Tests for T04: once-listener collision tracking and fire-time removal callback.

Verify criteria:
- FR#6 / AC#5: Two once=True listeners with same name+topic and default if_exists raise
  DuplicateListenerError; the once-exemption in _resolve_collision is removed.
- FR#7 / AC#6: After a once-listener fires, its natural key is released from
  _registered_listeners (a subsequent registration under the same key succeeds).
- FR#7: Bus.on_shutdown deregisters the removal callback from BusService.
- FR#9 / AC#8: When a once-listener fires, its database row has cancelled_at set.
"""

import typing
from unittest.mock import MagicMock

import pytest

from hassette.exceptions import DuplicateListenerError

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.bus.listeners import Listener


async def handler_a(event) -> None:
    pass


async def handler_b(event) -> None:
    pass


# FR#6 / AC#5 — once-listeners participate in collision tracking


async def test_once_listeners_collide_with_duplicate_error(bus: "Bus") -> None:
    """AC#5: Two once=True listeners with same name+topic raise DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_b, name="once_listener", once=True)


async def test_once_listener_key_tracked_in_registered_listeners(bus: "Bus") -> None:
    """FR#6: A once=True listener's natural key is stored in _registered_listeners."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)

    key = (bus.parent.app_key, bus.parent.index, "once_listener", "test.topic")
    assert key in bus._registered_listeners


async def test_once_if_exists_replace_works(bus: "Bus") -> None:
    """FR#6: once=True with if_exists='replace' cancels old and registers new."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)
        sub2 = await bus.on(topic="test.topic", handler=handler_b, name="once_listener", once=True, if_exists="replace")

    assert sub1.listener.is_cancelled
    assert sub2.listener is not sub1.listener


# FR#7 / AC#6 — once-fire releases the key (new registration succeeds)


def _get_bus_removal_callback(bus: "Bus"):
    """Get the removal callback registered by this bus, regardless of owner_id key.

    The bus fixture replaces bus.parent after __init__, so bus.owner_id changes.
    The callback was registered under the owner_id that was current at __init__ time.
    We find it by looking for the bound method in the callback values.
    """
    for callback in bus.bus_service._removal_callbacks.values():
        if getattr(callback, "__self__", None) is bus:
            return callback
    return None


async def test_once_key_released_after_fire(bus: "Bus") -> None:
    """AC#6: After a once-listener fires, a new registration under the same key succeeds."""
    cancelled_db_ids: list[int] = []
    call_count = 0

    async def mock_add(listener: "Listener") -> int:
        nonlocal call_count
        call_count += 1
        listener.mark_registered(call_count)
        return call_count

    async def mock_mark_cancelled(db_id: int) -> None:
        cancelled_db_ids.append(db_id)

    spawned_coros: list = []
    original_spawn = bus.bus_service.task_bucket.spawn

    def capture_spawn(coro, **_kwargs):
        spawned_coros.append(coro)
        return MagicMock()

    original_add = bus.bus_service.add_listener
    original_mark = bus.bus_service.mark_listener_cancelled
    bus.bus_service.add_listener = mock_add
    bus.bus_service.mark_listener_cancelled = mock_mark_cancelled
    bus.bus_service.task_bucket.spawn = capture_spawn

    try:
        # Register a once-listener
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)

        key = (bus.parent.app_key, bus.parent.index, "once_listener", "test.topic")
        assert key in bus._registered_listeners

        # Simulate BusService removing the listener (once-fire path) via the callback
        listener = bus._registered_listeners[key]
        # Invoke the removal callback directly to simulate what BusService.remove_listener does
        callback = _get_bus_removal_callback(bus)
        assert callback is not None, "Bus must register a removal callback on BusService"
        callback(listener)

        # Run spawned coroutines (mark_listener_cancelled)
        for coro in spawned_coros:
            await coro

        # Key must be released
        assert key not in bus._registered_listeners, "Natural key must be released after once-fire"

        # Now re-register under same key — must succeed without raising
        sub2 = await bus.on(topic="test.topic", handler=handler_b, name="once_listener", once=True)
        assert sub2 is not None
    finally:
        bus.bus_service.task_bucket.spawn = original_spawn
        bus.bus_service.add_listener = original_add
        bus.bus_service.mark_listener_cancelled = original_mark


# FR#9 / AC#8 — once-fire spawns mark_listener_cancelled


async def test_once_fire_spawns_mark_listener_cancelled(bus: "Bus") -> None:
    """AC#8: When a once-listener fires (removal callback invoked), cancelled_at is set."""
    cancelled_db_ids: list[int] = []
    db_id_assigned = 77

    async def mock_add(listener: "Listener") -> int:
        listener.mark_registered(db_id_assigned)
        return db_id_assigned

    async def mock_mark_cancelled(db_id: int) -> None:
        cancelled_db_ids.append(db_id)

    spawned_coros: list = []
    original_spawn = bus.bus_service.task_bucket.spawn

    def capture_spawn(coro, **_kwargs):
        spawned_coros.append(coro)
        return MagicMock()

    original_add = bus.bus_service.add_listener
    original_mark = bus.bus_service.mark_listener_cancelled
    bus.bus_service.add_listener = mock_add
    bus.bus_service.mark_listener_cancelled = mock_mark_cancelled
    bus.bus_service.task_bucket.spawn = capture_spawn

    try:
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)

        key = (bus.parent.app_key, bus.parent.index, "once_listener", "test.topic")
        listener = bus._registered_listeners[key]

        # Invoke the removal callback (simulates BusService.remove_listener for once-fire)
        callback = _get_bus_removal_callback(bus)
        assert callback is not None, "Bus must register a removal callback on BusService"
        callback(listener)

        # Run spawned coroutines
        for coro in spawned_coros:
            await coro
    finally:
        bus.bus_service.task_bucket.spawn = original_spawn
        bus.bus_service.add_listener = original_add
        bus.bus_service.mark_listener_cancelled = original_mark

    assert db_id_assigned in cancelled_db_ids, (
        f"mark_listener_cancelled should have been called with db_id={db_id_assigned}"
    )


async def test_once_fire_callback_no_crash_when_no_db_id(bus: "Bus") -> None:
    """FR#7: Removal callback does not crash or spawn when db_id is not set."""
    spawned_coros: list = []
    original_spawn = bus.bus_service.task_bucket.spawn

    def capture_spawn(coro, **_kwargs):
        spawned_coros.append(coro)
        return MagicMock()

    bus.bus_service.task_bucket.spawn = capture_spawn

    async def mock_add(_listener: "Listener") -> int:
        # Simulated failure mode: skip mark_registered so db_id stays None. The real
        # BusService.add_listener always calls mark_registered, so this exercises the
        # defensive `db_id is not None` guard against a path that cannot occur in production.
        return 0

    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = mock_add

    try:
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)

        key = (bus.parent.app_key, bus.parent.index, "once_listener", "test.topic")
        listener = bus._registered_listeners.get(key)
        assert listener is not None

        callback = _get_bus_removal_callback(bus)
        assert callback is not None, "Bus must register a removal callback on BusService"
        # Should not crash even with no db_id
        callback(listener)
    finally:
        bus.bus_service.task_bucket.spawn = original_spawn
        bus.bus_service.add_listener = original_add

    assert len(spawned_coros) == 0, "No spawn when db_id is None"


# FR#7 — on_shutdown deregisters the removal callback


async def test_shutdown_deregisters_removal_callback(bus: "Bus") -> None:
    """FR#7: Bus.on_shutdown deregisters the removal callback from BusService."""
    # The bus should have registered its callback in __init__
    callback_before = _get_bus_removal_callback(bus)
    assert callback_before is not None, "Bus must register a removal callback on BusService in __init__"

    # Trigger shutdown
    await bus.on_shutdown()

    callback_after = _get_bus_removal_callback(bus)
    assert callback_after is None, "Bus must deregister its removal callback on shutdown"


async def test_callback_no_op_when_key_already_gone(bus: "Bus") -> None:
    """FR#7: Invoking the removal callback after its key is already gone is a safe no-op.

    This is the tolerance that makes orphaned once-fires after hot-reload safe: when a
    listener's natural key has already been popped (by a prior removal, or because a new
    Bus replaced the registry entry), the callback finds was_present=False and must neither
    crash nor spawn mark_listener_cancelled.
    """
    # Register a listener so we have something to fire
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)

    key = (bus.parent.app_key, bus.parent.index, "once_listener", "test.topic")
    listener = bus._registered_listeners[key]

    # Simulate: callback is replaced (e.g. by a new Bus after hot-reload)
    # Pop the key first so the callback has nothing to pop
    bus._registered_listeners.pop(key, None)

    # Spy on spawn to prove the no-op path schedules no task — the only thing it could spawn
    # here is mark_listener_cancelled. Restore after so the patch can't leak if the fixture
    # scope ever changes.
    original_spawn = bus.bus_service.task_bucket.spawn
    spawn_spy = MagicMock()
    bus.bus_service.task_bucket.spawn = spawn_spy

    # Invoke the old callback with the listener — must not raise
    callback = _get_bus_removal_callback(bus)
    assert callback is not None
    try:
        # This must be a no-op: no crash, and no cancelled_at spawn for an already-gone key.
        callback(listener)
        spawn_spy.assert_not_called()
    finally:
        bus.bus_service.task_bucket.spawn = original_spawn
