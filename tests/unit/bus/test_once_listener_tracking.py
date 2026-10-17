"""Tests for once-listener collision tracking and fire-time removal callback.

Verify criteria:
- Two once=True listeners with same name+topic and default if_exists raise
  DuplicateListenerError; the once-exemption in _resolve_collision is removed.
- After a once-listener fires, its natural key is released from
  _registered_listeners (a subsequent registration under the same key succeeds).
- Bus.on_shutdown deregisters the removal callback from BusService.
- When a once-listener fires, its database row has cancelled_at set.
"""

import typing
from unittest.mock import MagicMock

import pytest

from hassette.exceptions import DuplicateListenerError

from .conftest import capture_bus_spawns, listener_key, mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.bus.listeners import Listener

ONCE_NAME = "once_listener"


async def handler_a(event) -> None:
    pass


async def handler_b(event) -> None:
    pass


# once-listeners participate in collision tracking


async def test_once_listeners_collide_with_duplicate_error(bus: "Bus") -> None:
    """Two once=True listeners with same name+topic raise DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_b, name="once_listener", once=True)


async def test_once_listener_key_tracked_in_registered_listeners(bus: "Bus") -> None:
    """A once=True listener's natural key is stored in _registered_listeners."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)

    assert listener_key(bus, name=ONCE_NAME) in bus._registered_listeners


async def test_once_if_exists_replace_works(bus: "Bus") -> None:
    """once=True with if_exists='replace' cancels old and registers new."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="once_listener", once=True)
        sub2 = await bus.on(topic="test.topic", handler=handler_b, name="once_listener", once=True, if_exists="replace")

    assert sub1.listener.is_cancelled
    assert sub2.listener is not sub1.listener


# once-fire releases the key (new registration succeeds)


def get_bus_removal_callback(bus: "Bus"):
    """Get the removal callback registered by this bus, regardless of owner_id key.

    The bus fixture replaces bus.parent after __init__, so bus.owner_id changes.
    The callback was registered under the owner_id that was current at __init__ time.
    We find it by looking for the bound method in the callback values.
    """
    for callback in bus.bus_service._removal_callbacks.values():
        if getattr(callback, "__self__", None) is bus:
            return callback
    return None


async def register_once_listener(bus: "Bus") -> "tuple[tuple[str, int, str, str], Listener]":
    """Register the `once_listener` once-listener on `test.topic`; return its natural key and `Listener`."""
    await bus.on(topic="test.topic", handler=handler_a, name=ONCE_NAME, once=True)
    key = listener_key(bus, name=ONCE_NAME)
    return key, bus._registered_listeners[key]


def invoke_removal_callback(bus: "Bus", listener: "Listener") -> None:
    """Fire the bus's removal callback for `listener`, as BusService.remove_listener does on once-fire."""
    callback = get_bus_removal_callback(bus)
    assert callback is not None, "Bus must register a removal callback on BusService"
    callback(listener)


async def test_once_key_released_after_fire(bus: "Bus") -> None:
    """After a once-listener fires, a new registration under the same key succeeds."""
    call_count = 0

    async def mock_add(listener: "Listener") -> int:
        nonlocal call_count
        call_count += 1
        listener.mark_registered(call_count)
        return call_count

    async def mock_mark_cancelled(_db_id: int) -> None:
        pass

    with capture_bus_spawns(bus, add_listener=mock_add, mark_listener_cancelled=mock_mark_cancelled) as spawned:
        key, listener = await register_once_listener(bus)
        invoke_removal_callback(bus, listener)

        # Run spawned coroutines (mark_listener_cancelled)
        for coro in spawned:
            await coro

        # Key must be released
        assert key not in bus._registered_listeners, "Natural key must be released after once-fire"

        # Now re-register under same key — must succeed without raising
        sub2 = await bus.on(topic="test.topic", handler=handler_b, name=ONCE_NAME, once=True)
        assert sub2 is not None


# once-fire spawns mark_listener_cancelled


async def test_once_fire_spawns_mark_listener_cancelled(bus: "Bus") -> None:
    """When a once-listener fires (removal callback invoked), cancelled_at is set."""
    cancelled_db_ids: list[int] = []
    db_id_assigned = 77

    async def mock_add(listener: "Listener") -> int:
        listener.mark_registered(db_id_assigned)
        return db_id_assigned

    async def mock_mark_cancelled(db_id: int) -> None:
        cancelled_db_ids.append(db_id)

    with capture_bus_spawns(bus, add_listener=mock_add, mark_listener_cancelled=mock_mark_cancelled) as spawned:
        _, listener = await register_once_listener(bus)
        invoke_removal_callback(bus, listener)

        for coro in spawned:
            await coro

    assert db_id_assigned in cancelled_db_ids, (
        f"mark_listener_cancelled should have been called with db_id={db_id_assigned}"
    )


async def test_once_fire_callback_no_crash_when_no_db_id(bus: "Bus") -> None:
    """Removal callback does not crash or spawn when db_id is not set."""

    async def mock_add(_listener: "Listener") -> int:
        # Simulated failure mode: skip mark_registered so db_id stays None. The real
        # BusService.add_listener always calls mark_registered, so this exercises the
        # defensive `db_id is not None` guard against a path that cannot occur in production.
        return 0

    with capture_bus_spawns(bus, add_listener=mock_add) as spawned:
        _, listener = await register_once_listener(bus)
        assert listener.db_id is None
        # Should not crash even with no db_id
        invoke_removal_callback(bus, listener)

    assert len(spawned) == 0, "No spawn when db_id is None"


# on_shutdown deregisters the removal callback


async def test_shutdown_deregisters_removal_callback(bus: "Bus") -> None:
    """Bus.on_shutdown deregisters the removal callback from BusService."""
    # The bus should have registered its callback in __init__
    callback_before = get_bus_removal_callback(bus)
    assert callback_before is not None, "Bus must register a removal callback on BusService in __init__"

    # Trigger shutdown
    await bus.on_shutdown()

    callback_after = get_bus_removal_callback(bus)
    assert callback_after is None, "Bus must deregister its removal callback on shutdown"


async def test_callback_no_op_when_key_already_gone(bus: "Bus") -> None:
    """Invoking the removal callback after its key is already gone is a safe no-op.

    This is the tolerance that makes orphaned once-fires after hot-reload safe: when a
    listener's natural key has already been popped (by a prior removal, or because a new
    Bus replaced the registry entry), the callback finds was_present=False and must neither
    crash nor spawn mark_listener_cancelled.
    """
    # Register a listener so we have something to fire
    with mock_add_listener(bus):
        key, listener = await register_once_listener(bus)

    # Simulate: callback is replaced (e.g. by a new Bus after hot-reload)
    # Pop the key first so the callback has nothing to pop
    bus._registered_listeners.pop(key, None)

    # Spy on spawn to prove the no-op path schedules no task — the only thing it could spawn
    # here is mark_listener_cancelled. Restore after so the patch can't leak if the fixture
    # scope ever changes.
    original_spawn = bus.bus_service.task_bucket.spawn
    spawn_spy = MagicMock()
    bus.bus_service.task_bucket.spawn = spawn_spy
    try:
        # This must be a no-op: no crash, and no cancelled_at spawn for an already-gone key.
        invoke_removal_callback(bus, listener)
        spawn_spy.assert_not_called()
    finally:
        bus.bus_service.task_bucket.spawn = original_spawn
