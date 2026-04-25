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
"""

import asyncio
from unittest.mock import MagicMock

from hassette.bus.duration_timer import DurationTimer
from hassette.test_utils import wait_for

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_timer(
    duration: float = 0.05,
    predicates=None,
    entity_id: str = "light.kitchen",
    owner_id: str = "test_owner",
) -> tuple[DurationTimer, MagicMock, MagicMock]:
    """Create a DurationTimer with a real task_bucket (using asyncio directly for spawning)
    and mock cancellation subscription.

    Returns:
        (timer, task_bucket_mock, cancel_sub_mock)
    """
    cancel_sub_mock = MagicMock(name="cancel_sub")

    # task_bucket.spawn: use asyncio.ensure_future so tasks actually run
    task_bucket_mock = MagicMock(name="task_bucket")

    def spawn_side_effect(coro, *, name: str = "") -> asyncio.Task:  # noqa: ARG001
        return asyncio.ensure_future(coro)

    task_bucket_mock.spawn = MagicMock(side_effect=spawn_side_effect)

    create_cancel_sub = MagicMock(return_value=cancel_sub_mock)

    timer = DurationTimer(
        task_bucket=task_bucket_mock,
        duration=duration,
        predicates=predicates,
        entity_id=entity_id,
        owner_id=owner_id,
        create_cancel_sub=create_cancel_sub,
    )
    return timer, task_bucket_mock, cancel_sub_mock


def _make_event() -> MagicMock:
    """Make a mock event."""
    return MagicMock(name="event")


# ---------------------------------------------------------------------------
# Tests — basic timer lifecycle
# ---------------------------------------------------------------------------


async def test_start_spawns_task_and_fires_after_delay() -> None:
    """start() with a short delay fires the on_fire callback after the delay elapses."""
    timer, _, _ = _make_timer(duration=0.05)
    fired = asyncio.Event()

    async def on_fire() -> None:
        fired.set()

    timer.start(on_fire=on_fire)

    # Timer should be active immediately after start
    assert timer.is_active

    # Wait for the delay to elapse
    await asyncio.wait_for(fired.wait(), timeout=1.0)
    assert fired.is_set()


async def test_cancel_prevents_fire() -> None:
    """cancel() called before the delay elapses prevents on_fire from running."""
    timer, _, _cancel_sub = _make_timer(duration=0.5)
    fired = asyncio.Event()

    async def on_fire() -> None:
        fired.set()

    timer.start(on_fire=on_fire)
    assert timer.is_active
    task = timer._task
    assert task is not None

    timer.cancel()

    await wait_for(lambda: task.done(), timeout=2.0, desc="timer task cancelled")
    assert not fired.is_set()


async def test_cancel_is_idempotent() -> None:
    """Calling cancel() twice does not raise an exception."""
    timer, _, _ = _make_timer(duration=0.5)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)

    # Should not raise
    timer.cancel()
    timer.cancel()


async def test_start_cancels_previous_task() -> None:
    """Calling start() a second time cancels the first pending task."""
    timer, _, _ = _make_timer(duration=0.5)
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

    task_bucket_mock = MagicMock(name="task_bucket")

    def spawn_side_effect(coro, *, name: str = "") -> asyncio.Task:  # noqa: ARG001
        return asyncio.ensure_future(coro)

    task_bucket_mock.spawn = MagicMock(side_effect=spawn_side_effect)

    create_cancel_sub = MagicMock(side_effect=[cancel_sub_1, cancel_sub_2])

    timer = DurationTimer(
        task_bucket=task_bucket_mock,
        duration=0.5,
        predicates=None,
        entity_id="light.kitchen",
        owner_id="test_owner",
        create_cancel_sub=create_cancel_sub,
    )

    async def on_fire() -> None:
        pass

    # First start — should create cancel_sub_1
    timer.start(on_fire=on_fire)
    assert timer._cancel_sub is cancel_sub_1

    # Cancel the timer — clears _cancel_sub
    timer.cancel()
    assert timer._cancel_sub is None

    # Reset _cancelled for a second start cycle
    timer._cancelled = False

    # Second start — _cancel_sub is None so should create cancel_sub_2
    timer.start(on_fire=on_fire)
    assert timer._cancel_sub is cancel_sub_2

    assert create_cancel_sub.call_count == 2


async def test_is_active_reflects_pending_task() -> None:
    """is_active returns True after start(), False after cancel() or after firing."""
    timer, _, _ = _make_timer(duration=0.05)
    fired = asyncio.Event()

    async def on_fire() -> None:
        fired.set()

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
    timer, _, _ = _make_timer(duration=0.5)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)
    assert timer.is_active

    timer.cancel()
    assert not timer.is_active


# ---------------------------------------------------------------------------
# Tests — cancellation event handling
# ---------------------------------------------------------------------------


async def test_evaluate_cancel_event_matching_does_not_cancel() -> None:
    """Event that still matches predicates does not cancel the timer."""
    predicate = MagicMock(return_value=True)  # always matches
    timer, _, _ = _make_timer(duration=0.5, predicates=predicate)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)
    assert timer.is_active

    # Trigger the cancellation handler with a matching event
    timer.evaluate_cancel_event(_make_event())

    # Timer should still be active — predicate matched, no cancel
    assert timer.is_active
    assert not timer._cancelled

    # Cleanup
    timer.cancel()


async def test_evaluate_cancel_event_non_matching_cancels() -> None:
    """Event that fails predicates cancels the timer."""
    predicate = MagicMock(return_value=False)  # never matches
    timer, _, _cancel_sub = _make_timer(duration=0.5, predicates=predicate)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)
    assert timer.is_active

    # Trigger the cancellation handler with a non-matching event
    timer.evaluate_cancel_event(_make_event())

    # Timer should be cancelled
    assert timer._cancelled
    assert not timer.is_active


async def test_evaluate_cancel_event_none_predicate_does_not_cancel() -> None:
    """When predicates is None, cancellation events are ignored (no predicate = always match)."""
    timer, _, _ = _make_timer(duration=0.5, predicates=None)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)
    assert timer.is_active

    # evaluate_cancel_event with None predicates should not cancel
    timer.evaluate_cancel_event(_make_event())

    assert timer.is_active
    assert not timer._cancelled

    # Cleanup
    timer.cancel()


# ---------------------------------------------------------------------------
# Tests — synchronous cancellation subscription removal
# ---------------------------------------------------------------------------


async def test_cancel_removes_cancellation_listener_synchronously() -> None:
    """cancel() calls cancel_sub.cancel() directly, not via task_bucket.spawn()."""
    timer, task_bucket_mock, cancel_sub = _make_timer(duration=0.5)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)

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
    timer, _, cancel_sub = _make_timer(duration=0.5)

    async def on_fire() -> None:
        pass

    timer.start(on_fire=on_fire)

    # Patch cancel_sub.cancel to capture state at call time
    cancelled_when_sub_cancelled: list[bool] = []

    def record_state():
        cancelled_when_sub_cancelled.append(timer._cancelled)

    cancel_sub.cancel = MagicMock(side_effect=record_state)

    timer.cancel()

    # _cancelled must have been True when cancel_sub.cancel() was called
    assert len(cancelled_when_sub_cancelled) == 1
    assert cancelled_when_sub_cancelled[0] is True


# ---------------------------------------------------------------------------
# Tests — listener wiring via Listener.create()
# ---------------------------------------------------------------------------


def test_listener_create_does_not_build_duration_timer() -> None:
    """Listener.create() does not construct DurationTimer — BusService.add_listener() does."""
    from hassette.bus.listeners import Listener

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    listener = Listener.create(
        task_bucket=task_bucket,
        owner_id="test_owner",
        topic="test.topic",
        handler=lambda: None,
        duration=5.0,
        entity_id="light.kitchen",
    )

    assert listener._duration_timer is None
    assert listener.duration == 5.0
    assert listener.entity_id == "light.kitchen"


def test_listener_create_no_duration_timer_when_no_duration() -> None:
    """Listener.create(duration=None) leaves _duration_timer as None."""
    from hassette.bus.listeners import Listener

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    listener = Listener.create(
        task_bucket=task_bucket,
        owner_id="test_owner",
        topic="test.topic",
        handler=lambda: None,
    )

    assert listener._duration_timer is None


def test_listener_cancel_cancels_duration_timer() -> None:
    """Listener.cancel() calls DurationTimer.cancel() when _duration_timer is set."""
    from hassette.bus.listeners import Listener

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    listener = Listener.create(
        task_bucket=task_bucket,
        owner_id="test_owner",
        topic="test.topic",
        handler=lambda: None,
        duration=5.0,
        entity_id="light.kitchen",
    )

    # Simulate what BusService.add_listener() does
    listener._duration_timer = DurationTimer(
        task_bucket=task_bucket,
        duration=5.0,
        predicates=None,
        entity_id="light.kitchen",
        owner_id="test_owner",
        create_cancel_sub=MagicMock(return_value=MagicMock()),
    )

    duration_timer = listener._duration_timer
    cancel_calls = []
    original_cancel = duration_timer.cancel

    def spy_cancel():
        cancel_calls.append(True)
        original_cancel()

    duration_timer.cancel = spy_cancel

    listener.cancel()

    assert len(cancel_calls) == 1
