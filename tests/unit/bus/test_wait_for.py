"""Unit tests for Bus.wait_for().

Covers: a future resolving on a matching event dispatched after registration (and not resolving
on anything dispatched before it existed); timeout behavior, including `timeout=None`;
auto-generated vs. user-provided listener names; the underlying listener being `once=True` and
auto-removed after firing; listener removal (shutdown/explicit cancel) cancelling the pending
future; `where=` predicate filtering; the return value being a bare `Event`, never wrapped in
`guard_await`/`Subscription`; and the pending-futures-count WARNING threshold.
"""

import asyncio
import contextlib
import inspect
import itertools
import logging
import types
import typing
from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import Subscription
from hassette.event_handling import predicates as P
from hassette.events.base import Event
from hassette.testing import create_state_change_event
from hassette.types.enums import Topic
from tests.support.factories import make_hassette_event

from .test_once_listener_tracking import get_bus_removal_callback

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

    from hassette.bus.bus import Bus
    from hassette.bus.listeners import Listener


@contextlib.contextmanager
def wait_for_add_listener_mock(bus: "Bus") -> "Iterator[tuple[list[Listener], asyncio.Event]]":
    """Stub bus_service.add_listener with real db_id assignment + a registration-completed gate.

    Unlike `conftest.mock_add_listener` (which always returns a fake db_id without calling
    `mark_registered`), wait_for asserts `listener.db_id is not None` immediately after
    registration — it needs a mock that actually marks the listener registered. `ready` is set
    each time a registration completes so tests can deterministically await "the task has
    reached its blocking wait" instead of racing a bare `asyncio.sleep(0)` (see
    CLAUDE.md's regression-test guidance on startup races).
    """
    registered: list[Listener] = []
    ready = asyncio.Event()
    counter = itertools.count(1)

    async def mock_add(listener: "Listener") -> int:
        db_id = next(counter)
        listener.mark_registered(db_id)
        registered.append(listener)
        ready.set()
        return db_id

    original = bus.bus_service.add_listener
    bus.bus_service.add_listener = mock_add
    try:
        yield registered, ready
    finally:
        bus.bus_service.add_listener = original


async def _await_registration(ready: asyncio.Event) -> None:
    await asyncio.wait_for(ready.wait(), timeout=1)
    ready.clear()


async def _fire(listener: "Listener", event) -> None:
    """Simulate a router delivering `event` to `listener` (bypassing dispatch/task machinery)."""
    await listener.invoker.orig_handler(event)


async def test_wait_for_resolves_on_matching_event(bus: "Bus") -> None:
    """Dispatching a matching event resolves the wait_for future with that event."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1))
        await _await_registration(ready)

        event = make_hassette_event(topic="test.topic")
        await _fire(registered[0], event)

        result = await asyncio.wait_for(task, timeout=1)
        assert result is event


async def test_wait_for_dispatches_through_real_async_path(bus: "Bus") -> None:
    """The internal listener handler must be async so Bus's normal dispatch pipeline
    (`make_async_handler`/`TaskBucket.make_async_adapter`) keeps future resolution on the
    event loop thread rather than routing it through the thread-pool executor — an
    `asyncio.Future` is not safe to mutate from a worker thread.

    Every other test in this file resolves the future via `_fire()`, which calls
    `listener.invoker.orig_handler(event)` directly and bypasses this classification
    entirely — none of them would catch a regression here. This test instead drives the
    listener's real `async_handler` wrapper (the one `BusService`'s dispatch machinery
    actually calls), the same object `make_async_handler` builds at registration time.
    """
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="real_dispatch_check"))
        await _await_registration(ready)

        listener = registered[0]
        assert inspect.iscoroutinefunction(listener.invoker.orig_handler), (
            "wait_for's internal handler must be `async def`, or Bus's dispatch pipeline "
            "routes it through the thread-pool executor instead of the event loop thread"
        )

        event = make_hassette_event(topic="test.topic")
        await listener.invoker.async_handler(event)

        result = await asyncio.wait_for(task, timeout=1)
        assert result is event


async def test_wait_for_only_matches_events_after_registration(bus: "Bus") -> None:
    """A wait_for call does not resolve on an event that "happened" before it existed.

    There is no listener to receive an event before wait_for creates one, so this is proven
    structurally: starting a fresh wait_for and firing nothing new leaves it pending (it only
    resolves once a genuinely new event is fired through its own listener).
    """
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1))
        await _await_registration(ready)

        # No new event fired yet — the wait must still be pending.
        await asyncio.sleep(0)
        assert not task.done()

        event = make_hassette_event(topic="test.topic")
        await _fire(registered[0], event)
        result = await asyncio.wait_for(task, timeout=1)
        assert result is event


async def test_wait_for_raises_timeout_error(bus: "Bus") -> None:
    """No matching event within `timeout` raises asyncio.TimeoutError."""
    with wait_for_add_listener_mock(bus), pytest.raises(TimeoutError):
        await bus.wait_for("test.topic", timeout=0.05)


async def test_wait_for_accepts_none_timeout(bus: "Bus") -> None:
    """timeout=None is accepted and does not raise while waiting."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=None))
        await _await_registration(ready)

        # Give the loop a couple of ticks — still pending, no timeout ever fires.
        await asyncio.sleep(0)
        assert not task.done()

        event = make_hassette_event(topic="test.topic")
        await _fire(registered[0], event)
        result = await asyncio.wait_for(task, timeout=1)
        assert result is event


async def test_wait_for_auto_generates_name(bus: "Bus") -> None:
    """Omitting name= registers the listener under a `_wait_for_` prefixed name."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1))
        await _await_registration(ready)

        assert registered[0].identity.name is not None
        assert registered[0].identity.name.startswith("_wait_for_")

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_wait_for_uses_provided_name(bus: "Bus") -> None:
    """A user-provided name= is used as the listener name verbatim."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="my_wait"))
        await _await_registration(ready)

        assert registered[0].identity.name == "my_wait"

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_wait_for_listener_is_once_and_removed_after_firing(bus: "Bus") -> None:
    """The underlying listener uses once=True and is removed from the registry after firing."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="once_check"))
        await _await_registration(ready)

        listener = registered[0]
        assert listener.invoker.once is True

        key = (bus.parent.app_key, bus.parent.index, "once_check", "test.topic")
        assert key in bus._registered_listeners

        event = make_hassette_event(topic="test.topic")
        await _fire(listener, event)
        await asyncio.wait_for(task, timeout=1)

        # The dispatch-time removal (BusService.remove_listener → _on_listener_removed) is
        # simulated explicitly: `_fire` calls the handler directly, bypassing the router's
        # own once-fire removal. Invoke the removal callback the same way
        # test_once_listener_tracking.py does to prove the key is released.
        callback = get_bus_removal_callback(bus)
        assert callback is not None
        callback(listener)
        assert key not in bus._registered_listeners


async def test_shutdown_cancels_pending_wait_for_future(bus: "Bus") -> None:
    """Removing the listener (e.g. shutdown) cancels the pending future -> CancelledError."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=5, name="shutdown_check"))
        await _await_registration(ready)

        listener = registered[0]
        callback = get_bus_removal_callback(bus)
        assert callback is not None
        callback(listener)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)


async def test_on_shutdown_batches_cancellation_warning_into_one_summary_line(
    bus: "Bus", caplog: pytest.LogCaptureFixture
) -> None:
    """Bus.on_shutdown() logs one summary WARNING for all pending wait_for futures it cancels,
    not one WARNING per future — see Finding 3, design.md's shutdown-logging note.
    """
    with wait_for_add_listener_mock(bus) as (registered, ready):
        tasks = []
        for i in range(3):
            tasks.append(asyncio.create_task(bus.wait_for("test.topic", timeout=5, name=f"shutdown_batch_{i}")))
            await _await_registration(ready)

        callback = get_bus_removal_callback(bus)
        assert callback is not None

        # wait_for_add_listener_mock only stubs registration, not bus_service's own listener
        # storage, so the real remove_listeners_by_owner() would find nothing to remove. Route
        # remove_all_listeners() through the same removal callback production wiring reaches
        # (BusService -> _on_listener_removed), mirroring test_shutdown_cancels_pending_wait_for_future.
        original_remove_all = bus.remove_all_listeners

        def fake_remove_all_listeners() -> None:
            for listener in list(registered):
                callback(listener)

        bus.remove_all_listeners = fake_remove_all_listeners
        try:
            with caplog.at_level(logging.WARNING, logger=bus.logger.name):
                await bus.on_shutdown()
        finally:
            bus.remove_all_listeners = original_remove_all

        for task in tasks:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)

        cancellation_records = [r for r in caplog.records if "wait_for future" in r.getMessage()]
        assert len(cancellation_records) == 1, (
            f"expected exactly one summary WARNING, got {len(cancellation_records)}: "
            f"{[r.getMessage() for r in cancellation_records]}"
        )
        assert "3" in cancellation_records[0].getMessage()
        assert "during shutdown" in cancellation_records[0].getMessage()


async def test_non_shutdown_cancellation_still_logs_per_future(bus: "Bus", caplog: pytest.LogCaptureFixture) -> None:
    """Outside of on_shutdown(), the removal callback still logs one WARNING per cancelled
    future — batching is shutdown-specific, not a general suppression of this WARNING.
    """
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=5, name="explicit_cancel"))
        await _await_registration(ready)

        listener = registered[0]
        callback = get_bus_removal_callback(bus)
        assert callback is not None

        with caplog.at_level(logging.WARNING, logger=bus.logger.name):
            callback(listener)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

        cancellation_records = [r for r in caplog.records if "Cancelling pending wait_for future" in r.getMessage()]
        assert len(cancellation_records) == 1


async def test_removal_after_successful_match_does_not_raise(bus: "Bus") -> None:
    """A successful match resolves the future before removal fires; the `not fut.done()` guard
    means a subsequent removal-callback invocation must not disturb the already-returned result.
    """
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="match_then_remove"))
        await _await_registration(ready)

        listener = registered[0]
        event = make_hassette_event(topic="test.topic")
        await _fire(listener, event)
        result = await asyncio.wait_for(task, timeout=1)
        assert result is event

        callback = get_bus_removal_callback(bus)
        assert callback is not None
        # Must not raise or attempt to cancel an already-resolved future.
        callback(listener)


async def test_wait_for_where_clause_filters_events(bus: "Bus") -> None:
    """where= predicates are attached to the listener and filter events correctly."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        where = P.EntityMatches("light.kitchen") & P.StateTo("on")
        task = asyncio.create_task(bus.wait_for(str(Topic.HASS_EVENT_STATE_CHANGED), where=where, timeout=1))
        await _await_registration(ready)

        listener = registered[0]

        non_matching = create_state_change_event(entity_id="light.kitchen", old_value="on", new_value="off")
        assert listener.matches(non_matching) is False
        assert not task.done()

        matching = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")
        assert listener.matches(matching) is True
        await _fire(listener, matching)

        result = await asyncio.wait_for(task, timeout=1)
        assert result is matching


async def test_wait_for_not_wrapped_in_guard_await(bus: "Bus") -> None:
    """wait_for's return value is a plain Event, not a Subscription/guard_await wrapper.

    on()/on_state_change() etc. return `Coroutine[Any, Any, Subscription]` wrapped via
    guard_await, specifically so a forgotten `await` can be detected and warned about.
    wait_for's coroutine is a bare `async def` with no guard_await wrapping — calling it
    produces an ordinary coroutine object, and awaiting it resolves to an `Event`, never a
    `Subscription`.
    """
    with wait_for_add_listener_mock(bus) as (registered, ready):
        coro = bus.wait_for("test.topic", timeout=1)
        assert isinstance(coro, types.CoroutineType)

        task = asyncio.create_task(coro)
        await _await_registration(ready)

        event = make_hassette_event(topic="test.topic")
        await _fire(registered[0], event)
        result = await asyncio.wait_for(task, timeout=1)

        assert isinstance(result, Event)
        assert not isinstance(result, Subscription)


async def test_multiple_concurrent_waits_resolve_independently(bus: "Bus") -> None:
    """Multiple concurrent wait_for calls on the same topic each get their own listener/future."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task1 = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="wait_1"))
        task2 = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="wait_2"))

        while len(registered) < 2:
            await _await_registration(ready)

        listener1, listener2 = registered
        assert listener1 is not listener2
        assert listener1.db_id != listener2.db_id

        event1 = make_hassette_event(topic="test.topic", data="one")
        event2 = make_hassette_event(topic="test.topic", data="two")
        await _fire(listener1, event1)
        await _fire(listener2, event2)

        result1 = await asyncio.wait_for(task1, timeout=1)
        result2 = await asyncio.wait_for(task2, timeout=1)
        assert result1 is event1
        assert result2 is event2


async def test_pending_futures_warning_at_threshold(bus: "Bus", caplog: pytest.LogCaptureFixture) -> None:
    """A WARNING is logged once pending wait_for futures cross the 20 threshold."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        tasks = []
        with caplog.at_level(logging.WARNING, logger=bus.logger.name):
            for i in range(20):
                tasks.append(asyncio.create_task(bus.wait_for("test.topic", timeout=5, name=f"wait_{i}")))
                await _await_registration(ready)

        assert len(registered) == 20
        assert any("pending wait_for futures" in record.getMessage() for record in caplog.records)

        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def test_dispatch_once_fire_removal_does_not_double_cancel(bus: "Bus") -> None:
    """Regression: wait_for's own `finally: subscription.cancel()` must not re-cancel a
    listener that the real dispatch machinery already removed.

    `_fire()` (used by every other test in this file) calls the handler directly, bypassing
    `BusService._dispatch`'s own `finally: self.remove_listener(listener)` for once=True
    listeners — so it never exercises the double-removal bug. Here `listener.cancel()` plus
    the removal callback (fetched via `get_bus_removal_callback`, same as
    `test_once_listener_tracking.py` — see that helper's docstring for why owner_id-keyed
    lookup doesn't work once a test overrides `bus.parent`) are invoked directly to mirror
    exactly what `BusService.remove_listener` does, immediately after the handler resolves
    the future. This matches the real event-loop ordering: the handler runs synchronously
    inside dispatch, and the once-removal happens before wait_for's suspended coroutine ever
    resumes to run its own `finally` block.
    """
    cancelled_db_ids: list[int] = []
    spawned_coros: list = []

    async def mock_mark_cancelled(db_id: int) -> None:
        cancelled_db_ids.append(db_id)

    def capture_spawn(coro, **_kwargs):
        spawned_coros.append(coro)
        return MagicMock()

    original_mark = bus.bus_service.mark_listener_cancelled
    original_spawn = bus.bus_service.task_bucket.spawn
    bus.bus_service.mark_listener_cancelled = mock_mark_cancelled
    bus.bus_service.task_bucket.spawn = capture_spawn

    try:
        with wait_for_add_listener_mock(bus) as (registered, ready):
            task = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="dispatch_once_check"))
            await _await_registration(ready)

            listener = registered[0]
            event = make_hassette_event(topic="test.topic")

            # Handler resolves the future synchronously, then the real once-fire removal
            # (BusService.remove_listener: listener.cancel() + fire_removal_callback) runs
            # before wait_for's coroutine resumes.
            await _fire(listener, event)
            listener.cancel()
            callback = get_bus_removal_callback(bus)
            assert callback is not None
            callback(listener)

            result = await asyncio.wait_for(task, timeout=1)
            assert result is event

        for coro in spawned_coros:
            await coro

        assert cancelled_db_ids.count(listener.db_id) == 1, (
            "mark_listener_cancelled must be spawned exactly once per once-fire, not once "
            "from the real dispatch removal and again from wait_for's own cleanup"
        )
    finally:
        bus.bus_service.mark_listener_cancelled = original_mark
        bus.bus_service.task_bucket.spawn = original_spawn


async def test_wait_for_removes_future_from_registry_on_completion(bus: "Bus") -> None:
    """The future is popped from _wait_for_futures whether it resolves, times out, or is cancelled."""
    with wait_for_add_listener_mock(bus) as (registered, ready):
        task = asyncio.create_task(bus.wait_for("test.topic", timeout=1, name="cleanup_check"))
        await _await_registration(ready)

        listener = registered[0]
        assert listener.db_id in bus._wait_for_futures

        event = make_hassette_event(topic="test.topic")
        await _fire(listener, event)
        await asyncio.wait_for(task, timeout=1)

        assert listener.db_id not in bus._wait_for_futures
