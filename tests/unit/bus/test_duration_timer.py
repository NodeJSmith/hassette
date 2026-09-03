"""Unit tests for DurationTimer lifecycle and cancellation.

Tests cover:
- Timer fires after delay via start()
- cancel() prevents on_fire from running
- cancel() is idempotent (safe to call multiple times)
- start() cancels any previous pending task
- start() recreates the cancellation subscription when it's None
- is_active reflects pending state correctly
- evaluate_cancel_event with matching predicates does NOT cancel the timer
- evaluate_cancel_event with non-matching predicates cancels the timer
- cancel() removes the cancellation subscription synchronously (no task_bucket.spawn)
- completed is set even when on_fire() raises, and the exception still propagates
"""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from hassette.bus.duration_timer import DurationTimer
from hassette.testing import wait_for
from tests.support.helpers import async_noop, create_listener, make_task_bucket

if TYPE_CHECKING:
    from hassette.events.base import Event
    from hassette.types import Predicate


def make_timer(
    duration: float = 0.05,
    predicates: "Predicate | None" = None,
    entity_id: str = "light.kitchen",
    owner_id: str = "test_owner",
    normalize_cancel_event: "Callable[[Event[Any]], Event[Any]] | None" = None,
    create_cancel_sub: MagicMock | None = None,
) -> tuple[DurationTimer, MagicMock, MagicMock]:
    """Create a DurationTimer with a real task_bucket (using asyncio directly for spawning)
    and mock cancellation subscription.

    Pass `create_cancel_sub` to override the default single-value factory — e.g. a
    `side_effect` list, for tests that need a fresh cancel_sub on each `start()`.

    Returns:
        (timer, task_bucket_mock, cancel_sub_mock)
    """
    cancel_sub_mock = MagicMock(name="cancel_sub")

    # task_bucket.spawn: use asyncio.create_task so tasks actually run
    task_bucket_mock = MagicMock(name="task_bucket")

    def spawn_side_effect(coro: "Coroutine[Any, Any, Any]", *, name: str = "") -> asyncio.Task:  # noqa: ARG001
        return asyncio.create_task(coro)

    task_bucket_mock.spawn = MagicMock(side_effect=spawn_side_effect)

    if create_cancel_sub is None:
        create_cancel_sub = MagicMock(return_value=cancel_sub_mock)

    timer = DurationTimer(
        task_bucket=task_bucket_mock,
        duration=duration,
        predicates=predicates,
        entity_id=entity_id,
        owner_id=owner_id,
        create_cancel_sub=create_cancel_sub,
        normalize_cancel_event=normalize_cancel_event,
    )
    return timer, task_bucket_mock, cancel_sub_mock


def start_timer(
    duration: float = 0.5,
    predicates: "Predicate | None" = None,
    create_cancel_sub: MagicMock | None = None,
) -> tuple[DurationTimer, MagicMock, MagicMock]:
    """Create a DurationTimer via make_timer() and start it with a no-op on_fire callback.

    For tests that only care about lifecycle state (is_active, cancel, cancellation
    subscriptions) and don't need to observe on_fire actually running.

    Returns (timer, task_bucket_mock, cancel_sub_mock) — same shape as make_timer().
    """
    timer, task_bucket_mock, cancel_sub_mock = make_timer(
        duration=duration, predicates=predicates, create_cancel_sub=create_cancel_sub
    )
    timer.start(on_fire=async_noop)
    return timer, task_bucket_mock, cancel_sub_mock


def make_timer_with_fired_event(
    duration: float = 0.05,
) -> tuple[DurationTimer, asyncio.Event, Callable[[], Awaitable[None]]]:
    """Create a DurationTimer plus an unset `fired` Event and its on_fire callback.

    The timer is NOT started — some callers need to assert `is_active` state before
    calling `timer.start(on_fire=on_fire)` themselves.

    Returns (timer, fired, on_fire).
    """
    timer, _, _ = make_timer(duration=duration)
    fired = asyncio.Event()

    async def on_fire() -> None:
        fired.set()

    return timer, fired, on_fire


def make_event() -> MagicMock:  # factory-local: plain MagicMock, no spec=Event
    """Make a mock event."""
    return MagicMock(name="event")


async def test_start_spawns_task_and_fires_after_delay() -> None:
    """start() with a short delay fires the on_fire callback after the delay elapses."""
    timer, fired, on_fire = make_timer_with_fired_event(duration=0.05)

    timer.start(on_fire=on_fire)

    # Timer should be active immediately after start
    assert timer.is_active

    # Wait for the delay to elapse
    await asyncio.wait_for(fired.wait(), timeout=1.0)
    assert fired.is_set()


async def test_cancel_prevents_fire() -> None:
    """cancel() called before the delay elapses prevents on_fire from running."""
    timer, fired, on_fire = make_timer_with_fired_event(duration=0.5)

    timer.start(on_fire=on_fire)
    assert timer.is_active
    task = timer._task
    assert task is not None

    timer.cancel()

    await wait_for(lambda: task.done(), timeout=2.0, desc="timer task cancelled")
    assert not fired.is_set()


async def test_cancel_is_idempotent() -> None:
    """Calling cancel() twice does not raise an exception."""
    timer, _, _ = start_timer(duration=0.5)

    # Should not raise
    timer.cancel()
    timer.cancel()


async def test_start_cancels_previous_task() -> None:
    """Calling start() a second time cancels the first pending task."""
    timer, _, _ = make_timer(duration=0.5)
    fire_count = 0

    async def on_fire() -> None:
        nonlocal fire_count
        fire_count += 1

    timer.start(on_fire=on_fire)
    first_task = timer._task
    assert first_task is not None

    # Start again — should cancel the first task
    timer.start(on_fire=on_fire)
    second_task = timer._task
    assert second_task is not first_task

    await wait_for(lambda: first_task.cancelled(), desc="first timer task cancelled")
    assert first_task.cancelled()


async def test_start_recreates_cancel_subscription() -> None:
    """After cancel() clears the sub, start() creates a fresh cancellation subscription."""
    cancel_sub_1 = MagicMock(name="cancel_sub_1")
    cancel_sub_2 = MagicMock(name="cancel_sub_2")
    create_cancel_sub = MagicMock(side_effect=[cancel_sub_1, cancel_sub_2])

    # First start — should create cancel_sub_1
    timer, _, _ = start_timer(duration=0.5, create_cancel_sub=create_cancel_sub)
    assert timer._cancel_sub is cancel_sub_1

    # Cancel the timer — clears _cancel_sub
    timer.cancel()
    assert timer._cancel_sub is None

    # Reset _cancelled for a second start cycle
    timer._cancelled = False

    # Second start — _cancel_sub is None so should create cancel_sub_2
    timer.start(on_fire=async_noop)
    assert timer._cancel_sub is cancel_sub_2

    assert create_cancel_sub.call_count == 2


async def test_is_active_reflects_pending_task() -> None:
    """is_active returns True after start(), False after cancel() or after firing."""
    timer, fired, on_fire = make_timer_with_fired_event(duration=0.05)

    # Before start: not active
    assert not timer.is_active

    timer.start(on_fire=on_fire)
    # After start: active
    assert timer.is_active

    # Wait for fire
    await asyncio.wait_for(fired.wait(), timeout=1.0)
    # After fire: task is done, no longer active
    assert not timer.is_active


async def test_is_active_false_after_cancel() -> None:
    """is_active returns False after cancel()."""
    timer, _, _ = start_timer(duration=0.5)
    assert timer.is_active

    timer.cancel()
    assert not timer.is_active


async def test_evaluate_cancel_event_matching_does_not_cancel() -> None:
    """Event that still matches predicates does not cancel the timer."""
    predicate = MagicMock(return_value=True)  # always matches
    timer, _, _ = start_timer(duration=0.5, predicates=predicate)
    assert timer.is_active

    # Trigger the cancellation handler with a matching event
    timer.evaluate_cancel_event(make_event())

    # Timer should still be active — predicate matched, no cancel
    assert timer.is_active
    assert not timer._cancelled

    # Cleanup
    timer.cancel()


async def test_evaluate_cancel_event_non_matching_cancels() -> None:
    """Event that fails predicates cancels the timer."""
    predicate = MagicMock(return_value=False)  # never matches
    timer, _, _cancel_sub = start_timer(duration=0.5, predicates=predicate)
    assert timer.is_active

    # Trigger the cancellation handler with a non-matching event
    timer.evaluate_cancel_event(make_event())

    # Timer should be cancelled
    assert timer._cancelled
    assert not timer.is_active


async def test_evaluate_cancel_event_none_predicate_does_not_cancel() -> None:
    """When predicates is None, cancellation events are ignored (no predicate = always match)."""
    timer, _, _ = start_timer(duration=0.5, predicates=None)
    assert timer.is_active

    # evaluate_cancel_event with None predicates should not cancel
    timer.evaluate_cancel_event(make_event())

    assert timer.is_active
    assert not timer._cancelled

    # Cleanup
    timer.cancel()


async def test_cancel_removes_cancellation_listener_synchronously() -> None:
    """cancel() calls cancel_sub.cancel() directly, not via task_bucket.spawn()."""
    timer, task_bucket_mock, cancel_sub = start_timer(duration=0.5)

    # Reset spawn call count after start()
    task_bucket_mock.spawn.reset_mock()

    timer.cancel()

    # cancel_sub.cancel() should have been called directly
    cancel_sub.cancel.assert_called_once()

    # task_bucket.spawn should NOT have been called for sub removal
    task_bucket_mock.spawn.assert_not_called()


async def test_cancel_sets_cancelled_flag_first() -> None:
    """The _cancelled flag is set as the FIRST operation in cancel() (idempotency guard)."""
    # We verify by checking that _cancelled is True before any other cleanup runs.
    # Since cancel() is sync, we inspect state after the call.
    timer, _, cancel_sub = start_timer(duration=0.5)

    # Patch cancel_sub.cancel to capture state at call time
    cancelled_when_sub_cancelled: list[bool] = []

    def record_state() -> None:
        cancelled_when_sub_cancelled.append(timer._cancelled)

    cancel_sub.cancel = MagicMock(side_effect=record_state)

    timer.cancel()

    # _cancelled must have been True when cancel_sub.cancel() was called
    assert len(cancelled_when_sub_cancelled) == 1
    assert cancelled_when_sub_cancelled[0] is True


async def test_restart_while_active_does_not_leak_stale_completed_signal() -> None:
    """A stale, just-cancelled cycle's completed.set() must not fire the NEW cycle's Event.

    Regression test: start() reassigns self.completed to a new asyncio.Event() synchronously
    before the event loop has a chance to deliver CancelledError to the just-cancelled cycle's
    delayed_fire() task. Without capturing the target Event by reference at start() time, the
    stale coroutine's `self.completed.set()` does a live attribute lookup and spuriously
    completes the new cycle instead of the one it belongs to.
    """
    timer, _, _ = make_timer(duration=1.0)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)
    old_completed = timer.completed

    # Let the first cycle's task actually start running (reach its sleep) before restarting.
    await asyncio.sleep(0)

    # Restart while the first cycle is still active — internally cancels the old task.
    timer.start(on_fire=on_fire)
    new_completed = timer.completed
    assert new_completed is not old_completed

    # Give the event loop a couple of ticks to deliver CancelledError to the stale task.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert old_completed.is_set(), "old cycle's completed event should be set by its own cancellation"
    assert not new_completed.is_set(), "new cycle's completed event must not be spuriously set by the stale cycle"

    # Cleanup
    timer.cancel()


async def test_completed_set_when_on_fire_raises() -> None:
    """`completed` must be set even when on_fire() raises, so waiters don't time out.

    Regression test: delayed_fire() used to call cycle_completed.set() only after
    `await on_fire()` returned normally, so an exception from on_fire() (e.g. a
    state-reader, predicate, dispatch, or listener-removal failure) skipped the set
    entirely even though the timer task had finished. The exception must still
    propagate out of the task.
    """
    timer, _, _ = make_timer(duration=0.05)

    async def on_fire() -> None:
        raise ValueError("boom")

    timer.start(on_fire=on_fire)
    task = timer._task
    assert task is not None

    with pytest.raises(ValueError, match="boom"):
        await task

    assert timer.completed.is_set()


async def test_cancel_during_in_flight_fire_does_not_set_completed_early() -> None:
    """cancel() during an in-flight on_fire() must not set completed before the callback exits.

    Regression test: delayed_fire() clears self._task before awaiting on_fire(), so a
    cancel() arriving while on_fire() is still running has no pending task left to
    interrupt. cancel() used to call self.completed.set() unconditionally regardless,
    letting a waiter resume while the handler was still executing — contradicting the
    documented "completed marks every completed timer lifecycle" semantics. cancel()
    must only set completed when it actually interrupted a pending task; delayed_fire()'s
    own finally owns setting it for the in-flight case, once on_fire() actually exits.
    """
    timer, _, _ = make_timer(duration=0.05)

    on_fire_entered = asyncio.Event()
    release_on_fire = asyncio.Event()

    async def on_fire() -> None:
        on_fire_entered.set()
        await release_on_fire.wait()

    timer.start(on_fire=on_fire)
    task = timer._task
    assert task is not None

    await asyncio.wait_for(on_fire_entered.wait(), timeout=1.0)

    # on_fire() is now in flight — delayed_fire() has already cleared self._task.
    assert timer._task is None
    assert not timer.is_active

    timer.cancel()

    # cancel() had nothing pending to interrupt, so completed must NOT be set yet —
    # the handler is still running.
    assert not timer.completed.is_set()

    release_on_fire.set()
    await asyncio.wait_for(task, timeout=1.0)

    # Only now that on_fire() has exited does delayed_fire()'s finally set completed.
    assert timer.completed.is_set()


def test_listener_create_does_not_build_duration_timer() -> None:
    """Listener.create() does not construct DurationTimer — BusService.add_listener() does."""
    listener = create_listener(topic="test.topic", duration=5.0, entity_id="light.kitchen")

    assert listener.duration_config._timer is None
    assert listener.duration_config.duration == 5.0
    assert listener.duration_config.entity_id == "light.kitchen"


def test_listener_create_no_duration_timer_when_no_duration() -> None:
    """Listener.create(duration=None) leaves _duration_timer as None."""
    listener = create_listener(topic="test.topic")

    assert listener.duration_config is None


def test_listener_cancel_cancels_duration_timer() -> None:
    """Listener.cancel() calls DurationTimer.cancel() when _duration_timer is set."""
    task_bucket = make_task_bucket()

    listener = create_listener(topic="test.topic", duration=5.0, entity_id="light.kitchen", task_bucket=task_bucket)

    # Simulate what BusService.add_listener() does
    assert listener.duration_config is not None
    object.__setattr__(
        listener.duration_config,
        "_timer",
        DurationTimer(
            task_bucket=task_bucket,
            duration=5.0,
            predicates=None,
            entity_id="light.kitchen",
            owner_id="test_owner",
            create_cancel_sub=MagicMock(return_value=MagicMock()),
        ),
    )

    duration_timer = listener.duration_config._timer
    cancel_calls = []
    original_cancel = duration_timer.cancel

    def spy_cancel():
        cancel_calls.append(True)
        original_cancel()

    duration_timer.cancel = spy_cancel

    listener.cancel()

    assert len(cancel_calls) == 1
