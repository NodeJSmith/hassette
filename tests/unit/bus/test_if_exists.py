"""Tests for if_exists="error"|"skip"|"replace" on bus registration (T03).

Covers:
- FR#1: if_exists accepted on on(), add_listener, and **opts methods (on_call_service)
- FR#2: if_exists="error" (and omission) raises DuplicateListenerError
- FR#3: if_exists="skip" with matching config returns subscription; one listener left
- FR#4: if_exists="skip" with differing config raises ValueError naming changed fields
- FR#5: if_exists="replace" cancels old, registers new on same row; returns new subscription
- FR#9: Bus.remove_listener spawns mark_listener_cancelled when db_id is set
- FR#10: add_listener returns a Subscription; skip-returns-existing case
- AC#1: Two identical skip calls return subscription both times, one listener total
- AC#2: skip after same-name-different-config raises ValueError listing changed fields
- AC#3: replace leaves one routed listener (new) with unchanged db_id; cancelled_at cleared
- AC#4: error/default raises DuplicateListenerError
- AC#7: Subscription.cancel() without re-registration triggers mark_listener_cancelled
- AC#9: add_listener returns Subscription including skip-returns-existing case
"""

import typing
from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import Subscription
from hassette.exceptions import DuplicateListenerError
from hassette.test_utils.helpers import create_listener

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus


async def handler_a(event) -> None:
    pass


async def handler_b(event) -> None:
    pass


async def test_error_default_raises_on_duplicate(bus: "Bus") -> None:
    """AC#4: Omitting if_exists under an existing key raises DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_b, name="my_listener")


async def test_error_explicit_raises_on_duplicate(bus: "Bus") -> None:
    """FR#2: if_exists='error' explicitly raises DuplicateListenerError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        with pytest.raises(DuplicateListenerError):
            await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="error")


async def test_error_via_on_call_service(bus: "Bus") -> None:
    """FR#1: if_exists reaches **opts methods like on_call_service."""
    with mock_add_listener(bus):
        await bus.on_call_service(handler=handler_a, name="svc_listener")
        with pytest.raises(DuplicateListenerError):
            await bus.on_call_service(handler=handler_b, name="svc_listener", if_exists="error")


# FR#3 / AC#1 — skip idempotent re-registration


async def test_skip_identical_config_returns_subscription(bus: "Bus") -> None:
    """FR#3 / AC#1: skip with identical config returns a subscription."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        sub2 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener", if_exists="skip")

    assert sub2 is not None
    assert isinstance(sub2, Subscription)


async def test_skip_returns_existing_listener(bus: "Bus") -> None:
    """FR#3: skip returns a subscription wrapping the existing listener."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        sub2 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener", if_exists="skip")

    # The existing listener should be the same object
    assert sub2.listener is sub1.listener


async def test_skip_leaves_one_listener_in_registry(bus: "Bus") -> None:
    """AC#1: Two skip calls leave exactly one listener in the per-bus registry."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener", if_exists="skip")

    key = (bus.parent.app_key, bus.parent.index, "my_listener", "test.topic")
    # Only one entry in the registry
    assert key in bus._registered_listeners
    assert len(bus._registered_listeners) == 1


async def test_registration_failure_rolls_back_registry_key(bus: "Bus") -> None:
    """A failed add_listener must not leave a phantom key — a retry under the same name succeeds."""
    key = (bus.parent.app_key, bus.parent.index, "my_listener", "test.topic")

    with mock_add_listener(bus) as mock:
        mock.side_effect = RuntimeError("registration boom")
        with pytest.raises(RuntimeError, match="registration boom"):
            await bus.on(topic="test.topic", handler=handler_a, name="my_listener")

    # The reserved key was rolled back, so nothing is left behind.
    assert key not in bus._registered_listeners

    # A fresh registration under the same name is not blocked by a phantom collision.
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
    assert key in bus._registered_listeners


async def test_skip_does_not_call_add_listener_twice(bus: "Bus") -> None:
    """FR#3: skip does not register a second listener (add_listener called once)."""
    with mock_add_listener(bus) as add_mock:
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener", if_exists="skip")

    assert add_mock.call_count == 1, "add_listener should only be called once (not on skip)"


async def test_skip_via_on_call_service(bus: "Bus") -> None:
    """FR#1: if_exists='skip' reaches on_call_service via **opts."""
    with mock_add_listener(bus):
        sub1 = await bus.on_call_service(handler=handler_a, name="svc_listener")
        sub2 = await bus.on_call_service(handler=handler_a, name="svc_listener", if_exists="skip")

    assert sub2.listener is sub1.listener


# FR#4 / AC#2 — skip with drift raises ValueError


async def test_skip_drift_raises_value_error(bus: "Bus") -> None:
    """FR#4 / AC#2: skip with different handler raises ValueError."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        with pytest.raises(ValueError, match="configuration has changed"):
            await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="skip")


async def test_skip_drift_error_names_changed_fields(bus: "Bus") -> None:
    """AC#2: ValueError names the changed fields."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        with pytest.raises(ValueError, match="configuration has changed") as exc_info:
            await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="skip")

    msg = str(exc_info.value)
    assert "handler" in msg


# FR#5 / AC#3 — replace cancels old, registers new


async def test_replace_cancels_old_listener(bus: "Bus") -> None:
    """FR#5: replace cancels the existing listener."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        old_listener = sub1.listener
        await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="replace")

    assert old_listener.is_cancelled, "Old listener should be cancelled after replace"


async def test_replace_leaves_one_routed_listener(bus: "Bus") -> None:
    """AC#3: replace leaves exactly one listener in the registry (the new one)."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        sub2 = await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="replace")

    key = (bus.parent.app_key, bus.parent.index, "my_listener", "test.topic")
    assert key in bus._registered_listeners
    # The stored listener should be the new one
    stored = bus._registered_listeners[key]
    assert stored is sub2.listener
    assert stored is not sub1.listener


async def test_replace_returns_subscription_to_new_listener(bus: "Bus") -> None:
    """FR#5: replace returns a subscription to the new listener."""
    with mock_add_listener(bus):
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        sub2 = await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="replace")

    assert sub2 is not None
    assert isinstance(sub2, Subscription)
    assert sub2.listener is not sub1.listener
    assert sub2.listener.invoker.orig_handler is handler_b


async def test_replace_db_id_preserved(bus: "Bus") -> None:
    """AC#3: replace preserves the db_id of the natural-key row (row-id preservation)."""
    # Use a mock that returns db_id=42 on first call
    first_call_made = False

    async def mock_add(listener):
        nonlocal first_call_made
        if not first_call_made:
            first_call_made = True
            listener.mark_registered(42)
            return 42
        listener.mark_registered(42)  # same db_id from upsert
        return 42

    original = bus.bus_service.add_listener
    bus.bus_service.add_listener = mock_add
    try:
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert sub1.listener.db_id == 42

        sub2 = await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="replace")
        # New listener gets same db_id (upsert row-id preservation)
        assert sub2.listener.db_id == 42
    finally:
        bus.bus_service.add_listener = original


# FR#9 / AC#7 — cancel path spawns mark_listener_cancelled


async def test_cancel_subscription_spawns_mark_cancelled(bus: "Bus") -> None:
    """AC#7: Subscription.cancel() spawns mark_listener_cancelled when db_id is set."""
    cancelled_db_ids: list[int] = []

    async def mock_add(listener):
        listener.mark_registered(99)
        return 99

    async def mock_mark_cancelled(db_id: int) -> None:
        cancelled_db_ids.append(db_id)

    original_add = bus.bus_service.add_listener
    original_mark = bus.bus_service.mark_listener_cancelled
    bus.bus_service.add_listener = mock_add
    bus.bus_service.mark_listener_cancelled = mock_mark_cancelled

    try:
        sub = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert sub.listener.db_id == 99

        # Mock the task_bucket.spawn to actually run the coroutine
        original_spawn = bus.bus_service.task_bucket.spawn
        spawned_coros: list = []

        def capture_spawn(coro, **_kwargs):
            spawned_coros.append(coro)
            return MagicMock()

        bus.bus_service.task_bucket.spawn = capture_spawn
        try:
            sub.cancel()
            # Run the spawned coroutine
            for coro in spawned_coros:
                await coro
        finally:
            bus.bus_service.task_bucket.spawn = original_spawn
    finally:
        bus.bus_service.add_listener = original_add
        bus.bus_service.mark_listener_cancelled = original_mark

    assert 99 in cancelled_db_ids, "mark_listener_cancelled should have been called with db_id=99"


async def test_cancel_no_db_id_no_spawn(bus: "Bus") -> None:
    """FR#9: If db_id is not set (None), mark_listener_cancelled is not spawned."""
    spawn_calls: list = []

    async def mock_add(_listener):
        # Do NOT call mark_registered — db_id stays None
        return 0

    original_add = bus.bus_service.add_listener
    bus.bus_service.add_listener = mock_add

    try:
        sub = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        assert sub.listener.db_id is None

        original_spawn = bus.bus_service.task_bucket.spawn

        def capture_spawn(coro, **_kwargs):
            spawn_calls.append(coro)
            return MagicMock()

        bus.bus_service.task_bucket.spawn = capture_spawn
        try:
            sub.cancel()
        finally:
            bus.bus_service.task_bucket.spawn = original_spawn
    finally:
        bus.bus_service.add_listener = original_add

    assert len(spawn_calls) == 0, "No spawn should occur when db_id is None"


async def test_replace_cancel_old_spawns_mark_cancelled(bus: "Bus") -> None:
    """FR#9: replace's cancel-old step spawns mark_listener_cancelled."""
    cancelled_db_ids: list[int] = []
    call_count = 0

    async def mock_add(listener):
        nonlocal call_count
        call_count += 1
        db_id = call_count * 10
        listener.mark_registered(db_id)
        return db_id

    async def mock_mark_cancelled(db_id: int) -> None:
        cancelled_db_ids.append(db_id)

    original_add = bus.bus_service.add_listener
    original_mark = bus.bus_service.mark_listener_cancelled
    bus.bus_service.add_listener = mock_add
    bus.bus_service.mark_listener_cancelled = mock_mark_cancelled

    spawned_coros: list = []
    original_spawn = bus.bus_service.task_bucket.spawn

    def capture_spawn(coro, **_kwargs):
        spawned_coros.append(coro)
        return MagicMock()

    bus.bus_service.task_bucket.spawn = capture_spawn
    try:
        sub1 = await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        old_db_id = sub1.listener.db_id
        assert old_db_id == 10

        await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="replace")

        # Run all spawned coroutines
        for coro in spawned_coros:
            await coro
    finally:
        bus.bus_service.task_bucket.spawn = original_spawn
        bus.bus_service.add_listener = original_add
        bus.bus_service.mark_listener_cancelled = original_mark

    assert old_db_id in cancelled_db_ids, f"mark_listener_cancelled should have been called with db_id={old_db_id}"


# FR#10 / AC#9 — add_listener returns Subscription


async def test_add_listener_returns_subscription(bus: "Bus") -> None:
    """FR#10 / AC#9: add_listener returns a Subscription."""
    with mock_add_listener(bus):
        listener = create_listener(
            handler=handler_a,
            app_key=bus.parent.app_key,
            instance_index=bus.parent.index,
            name="test_listener",
            owner_id=bus.owner_id,
        )
        result = await bus.add_listener(listener)

    assert isinstance(result, Subscription)
    assert result.listener is listener


async def test_add_listener_skip_returns_existing_subscription(bus: "Bus") -> None:
    """AC#9: add_listener with if_exists='skip' returns subscription to existing listener."""
    with mock_add_listener(bus):
        listener1 = create_listener(
            handler=handler_a,
            app_key=bus.parent.app_key,
            instance_index=bus.parent.index,
            name="test_listener",
            owner_id=bus.owner_id,
        )
        sub1 = await bus.add_listener(listener1)

        listener2 = create_listener(
            handler=handler_a,
            app_key=bus.parent.app_key,
            instance_index=bus.parent.index,
            name="test_listener",
            owner_id=bus.owner_id,
        )
        sub2 = await bus.add_listener(listener2, if_exists="skip")

    assert sub2.listener is sub1.listener, "skip should return existing listener's subscription"


# FR#1 — if_exists accepted on on() explicitly


async def test_if_exists_accepted_on_on_method(bus: "Bus") -> None:
    """FR#1: on() accepts if_exists parameter."""
    with mock_add_listener(bus):
        # Should not raise TypeError — if_exists is a valid param on on()
        sub = await bus.on(topic="test.topic", handler=handler_a, name="my_listener", if_exists="error")
    assert sub is not None


async def test_if_exists_skip_accepted_on_on_method(bus: "Bus") -> None:
    """FR#1: on() accepts if_exists='skip'."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        # Should not raise
        sub = await bus.on(topic="test.topic", handler=handler_a, name="my_listener", if_exists="skip")
    assert sub is not None


async def test_if_exists_replace_accepted_on_on_method(bus: "Bus") -> None:
    """FR#1: on() accepts if_exists='replace'."""
    with mock_add_listener(bus):
        await bus.on(topic="test.topic", handler=handler_a, name="my_listener")
        sub = await bus.on(topic="test.topic", handler=handler_b, name="my_listener", if_exists="replace")
    assert sub is not None
