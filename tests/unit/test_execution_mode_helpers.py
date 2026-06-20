"""Unit tests for the shared dispatch-bridge helpers in execution_mode.

Covers: run_with_stall_watch, run_through_guard, drain_pending_done, STALL_THRESHOLD_SECONDS.
"""

import asyncio
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from hassette.execution_mode import (
    STALL_THRESHOLD_SECONDS,
    ExecutionModeGuard,
    drain_pending_done,
    run_through_guard,
    run_with_stall_watch,
)
from hassette.test_utils import wait_for
from hassette.types.enums import ExecutionMode


def make_spawn() -> tuple[Callable[..., asyncio.Task[None]], list[asyncio.Task[None]]]:
    """Return a spawn callable (wrapping create_task) and the list of tasks it created."""
    tasks: list[asyncio.Task[None]] = []

    def spawn(coro, *, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)
        tasks.append(task)
        return task

    return spawn, tasks


class TestStallThresholdSeconds:
    def test_is_float(self) -> None:
        assert isinstance(STALL_THRESHOLD_SECONDS, float)

    def test_positive_value(self) -> None:
        assert STALL_THRESHOLD_SECONDS > 0


class TestRunWithStallWatch:
    async def test_invocation_runs_to_completion(self) -> None:
        """invoke() is awaited and completes normally."""
        completed = False

        async def invoke() -> None:
            nonlocal completed
            completed = True

        warn = MagicMock()
        await run_with_stall_watch(invoke, warn, threshold=60.0)
        assert completed

    async def test_warn_not_called_on_fast_invocation(self) -> None:
        """warn is not called when invoke completes before the threshold."""
        warn = MagicMock()

        async def invoke() -> None:
            pass

        await run_with_stall_watch(invoke, warn, threshold=60.0)
        warn.assert_not_called()

    async def test_warn_fires_with_threshold_past_deadline(self) -> None:
        """warn(threshold) fires after the threshold elapses and receives the armed threshold."""
        started = asyncio.Event()
        gate = asyncio.Event()
        warn_calls: list[float] = []

        def warn(threshold: float) -> None:
            warn_calls.append(threshold)
            gate.set()  # unblock the invocation once warn fires

        async def invoke() -> None:
            started.set()
            await gate.wait()

        threshold = 0.05  # short threshold for testing
        task = asyncio.create_task(run_with_stall_watch(invoke, warn, threshold=threshold))
        await asyncio.wait_for(started.wait(), timeout=2.0)
        # warn.set() unblocks the gate, so awaiting the task is the deterministic
        # signal that the watchdog fired.
        await asyncio.wait_for(task, timeout=2.0)

        assert warn_calls == [threshold], f"expected warn called with {threshold}, got {warn_calls}"

    async def test_watchdog_cancelled_on_completion(self) -> None:
        """The watchdog handle is cancelled when invoke completes — no late warn fires."""
        warn_calls: list[float] = []

        def warn(threshold: float) -> None:
            warn_calls.append(threshold)

        async def invoke() -> None:
            pass

        await run_with_stall_watch(invoke, warn, threshold=0.05)
        # sleep past the threshold; the watchdog should be cancelled by now
        await asyncio.sleep(0.15)
        assert warn_calls == []

    async def test_watchdog_cancelled_on_cancellation(self) -> None:
        """The watchdog is cancelled in finally even when invoke raises CancelledError."""
        started = asyncio.Event()
        warn_calls: list[float] = []

        def warn(threshold: float) -> None:
            warn_calls.append(threshold)

        async def invoke() -> None:
            started.set()
            await asyncio.sleep(10)  # will be cancelled

        task = asyncio.create_task(run_with_stall_watch(invoke, warn, threshold=0.05))
        await asyncio.wait_for(started.wait(), timeout=2.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.15)
        assert warn_calls == []


class TestDrainPendingDone:
    async def test_resolves_all_unresolved_futures(self) -> None:
        """drain_pending_done sets result on every unresolved future in the set."""
        loop = asyncio.get_running_loop()
        futures = {loop.create_future(), loop.create_future(), loop.create_future()}
        drain_pending_done(futures)
        assert all(f.done() for f in futures)

    async def test_empties_the_set(self) -> None:
        """drain_pending_done discards all futures from the set."""
        loop = asyncio.get_running_loop()
        futures = {loop.create_future(), loop.create_future()}
        drain_pending_done(futures)
        assert len(futures) == 0

    async def test_skips_already_resolved_futures(self) -> None:
        """drain_pending_done does not error when a future is already resolved."""
        loop = asyncio.get_running_loop()
        already_done: asyncio.Future[None] = loop.create_future()
        already_done.set_result(None)
        futures = {already_done, loop.create_future()}
        drain_pending_done(futures)  # must not raise
        assert len(futures) == 0

    async def test_empty_set_is_a_noop(self) -> None:
        """drain_pending_done on an empty set does nothing."""
        futures: set[asyncio.Future[None]] = set()
        drain_pending_done(futures)  # must not raise
        assert len(futures) == 0


class TestRunThroughGuard:
    async def test_suppressed_resolves_future_inline(self) -> None:
        """SUPPRESSED outcome: resolve_done is called inline; await returns without hang."""
        guard = ExecutionModeGuard(ExecutionMode.SINGLE)
        spawn, _tasks = make_spawn()
        pending_done: set[asyncio.Future[None]] = set()

        # Hold a first invocation running so the guard is busy.
        gate = asyncio.Event()
        first_started = asyncio.Event()

        async def first_invoke() -> None:
            first_started.set()
            await gate.wait()

        first_task = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, first_invoke, MagicMock(), "t", 60.0)
        )
        await asyncio.wait_for(first_started.wait(), timeout=2.0)

        # Second call — guard will SUPPRESS it; must return without hanging.
        warn = MagicMock()

        async def second_invoke() -> None:
            pass

        # The running first invocation's future is parked; capture the count so we
        # can prove the SUPPRESSED call leaves no residue of its own future.
        pending_before_second = len(pending_done)
        second_task = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, second_invoke, warn, "t2", 60.0)
        )
        await asyncio.wait_for(second_task, timeout=2.0)
        assert not second_task.exception(), "second task raised unexpectedly"
        # The suppressed future was added then resolved+discarded inline, so the
        # set is back to exactly what it held before (the running first future).
        assert len(pending_done) == pending_before_second

        gate.set()
        await asyncio.wait_for(first_task, timeout=2.0)

    async def test_dropped_resolves_future_inline(self) -> None:
        """DROPPED outcome: future is resolved inline; function returns."""
        guard = ExecutionModeGuard(ExecutionMode.QUEUED, cap=1)
        spawn, _tasks = make_spawn()
        pending_done: set[asyncio.Future[None]] = set()

        gate = asyncio.Event()
        started = asyncio.Event()

        async def invoke_running() -> None:
            started.set()
            await gate.wait()

        async def invoke_queued() -> None:
            pass

        async def invoke_dropped() -> None:
            pass

        # Start one running + fill the queue (cap=1).
        first = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, invoke_running, MagicMock(), "r", 60.0)
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)

        second = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, invoke_queued, MagicMock(), "q", 60.0)
        )
        # Deterministically wait until the queued factory is parked before the
        # third call, so the third is guaranteed to hit the cap and be DROPPED.
        await wait_for(lambda: len(guard.pending) >= 1)

        # Third — queue is full; this should be DROPPED and return quickly.
        third = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, invoke_dropped, MagicMock(), "d", 60.0)
        )
        await asyncio.wait_for(third, timeout=2.0)

        gate.set()
        await asyncio.wait_for(first, timeout=2.0)
        await asyncio.wait_for(second, timeout=2.0)

    async def test_ran_awaits_done_future(self) -> None:
        """RAN outcome: await completes after the spawned task finishes."""
        guard = ExecutionModeGuard(ExecutionMode.SINGLE)
        spawn, _tasks = make_spawn()
        pending_done: set[asyncio.Future[None]] = set()

        completed = False

        async def invoke() -> None:
            nonlocal completed
            completed = True

        await run_through_guard(guard, spawn, pending_done, invoke, MagicMock(), "name", 60.0)

        assert completed
        # After successful await, pending_done should be empty (future resolved via done-callback).
        assert len(pending_done) == 0

    async def test_future_added_to_pending_done(self) -> None:
        """A future is added to pending_done before the guard call returns."""
        guard = ExecutionModeGuard(ExecutionMode.SINGLE)
        spawn, _tasks = make_spawn()
        pending_done: set[asyncio.Future[None]] = set()

        started = asyncio.Event()
        gate = asyncio.Event()

        async def invoke() -> None:
            started.set()
            await gate.wait()

        dispatch_task = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, invoke, MagicMock(), "n", 60.0)
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)
        # While the spawned task is running, pending_done should have the future.
        assert len(pending_done) == 1

        gate.set()
        await asyncio.wait_for(dispatch_task, timeout=2.0)
        # After completion it should be gone.
        assert len(pending_done) == 0

    async def test_spawn_called_with_keyword_name(self) -> None:
        """spawn is called with name as a keyword argument."""
        guard = ExecutionModeGuard(ExecutionMode.SINGLE)
        spawn_calls: list[dict] = []

        async def invoke() -> None:
            pass

        def spawn(coro, *, name: str) -> asyncio.Task[None]:
            spawn_calls.append({"name": name})
            return asyncio.create_task(coro, name=name)

        pending_done: set[asyncio.Future[None]] = set()
        await run_through_guard(guard, spawn, pending_done, invoke, MagicMock(), "my-task", 60.0)

        assert len(spawn_calls) == 1
        assert spawn_calls[0]["name"] == "my-task"

    async def test_drain_pending_done_resolves_queued_accepted_futures(self) -> None:
        """drain_pending_done after guard.release() resolves futures from QUEUED_ACCEPTED runs."""
        guard = ExecutionModeGuard(ExecutionMode.QUEUED)
        spawn, _tasks = make_spawn()
        pending_done: set[asyncio.Future[None]] = set()

        gate = asyncio.Event()
        started = asyncio.Event()

        async def invoke_running() -> None:
            started.set()
            await gate.wait()

        async def invoke_queued() -> None:
            pass

        first = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, invoke_running, MagicMock(), "r", 60.0)
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Queue one invocation; its future is in pending_done but the factory won't run until drain.
        second = asyncio.create_task(
            run_through_guard(guard, spawn, pending_done, invoke_queued, MagicMock(), "q", 60.0)
        )
        # Deterministically wait until the queued factory is parked before releasing.
        await wait_for(lambda: len(guard.pending) >= 1)

        # Release + drain.
        await guard.release()
        drain_pending_done(pending_done)

        # Both futures should now be resolved; second_task should complete.
        await asyncio.wait_for(second, timeout=2.0)
        await asyncio.wait_for(first, timeout=2.0)
        assert len(pending_done) == 0
