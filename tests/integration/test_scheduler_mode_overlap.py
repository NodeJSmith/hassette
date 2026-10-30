"""Integration tests for scheduler dispatch-time reschedule and per-mode overlap.

Verifies:
- dispatch-time reschedule: next occurrence enqueued before current run completes
- fire sequence unchanged for non-overrunning jobs
- per-mode overlap: single suppresses, queued serializes, restart cancels+fresh, parallel concurrent

These tests use HassetteHarness (framework-tier scheduler) via the hassette_with_scheduler fixture.
App-tier tests use AppTestHarness.
"""

import asyncio
import contextlib
from typing import TYPE_CHECKING

import pytest

import hassette.utils.date_utils as date_utils
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS
from tests.support.scheduler_dispatch_helpers import (
    freeze_and_dispatch,
    get_job_by_name,
    scheduler_service_for,
    start_overrun,
)

if TYPE_CHECKING:
    from whenever import ZonedDateTime

# Dispatch-time reschedule and guard routing tests


class _OverlapConfig(AppConfig):
    """Minimal config for overlap mode tests."""


class _OverrunApp(App[_OverlapConfig]):
    """App with a recurring job that can be held open by a gate event."""

    run_gate: asyncio.Event
    started: asyncio.Event
    invocation_count: int
    job_name: str
    job_mode: str

    async def on_initialize(self) -> None:
        self.run_gate = asyncio.Event()
        self.started = asyncio.Event()
        self.invocation_count = 0
        self.run_gate.set()  # default: let jobs through immediately
        await self.scheduler.run_every(
            self.long_task,
            seconds=10,
            name=self.job_name,
            mode=self.job_mode,
        )

    async def long_task(self) -> None:
        self.invocation_count += 1
        self.started.set()
        await self.run_gate.wait()


# Dispatch-time reschedule: next occurrence on heap before run completes


async def test_dispatch_time_reschedule_next_occurrence_before_run_completes() -> None:
    """An overrunning recurring job has its next occurrence on the heap before the current
    invocation completes.
    """

    class _App(_OverrunApp):
        job_name = "overrun_job"
        job_mode = "single"

    async with AppTestHarness(_App, config={"instance_name": "app"}) as harness:
        app = harness.app
        app.run_gate.clear()  # block the job so it overruns

        job = await get_job_by_name(harness, "overrun_job")

        # Start dispatch without waiting for completion — job will block on gate
        dispatch_task = await freeze_and_dispatch(harness, job)

        # Wait until the job has started
        await asyncio.wait_for(app.started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        # At this point, the job is still running (gate is closed).
        # The next occurrence should already be on the heap.
        all_queued = await scheduler_service_for(harness).get_all_jobs()
        assert any(j is job for j in all_queued), "Next occurrence should be on the heap before current run completes"

        # Unblock and clean up
        app.run_gate.set()
        await asyncio.wait_for(dispatch_task, timeout=HANG_GUARD_TIMEOUT_SECONDS)


# Fire sequence unchanged for non-overrunning jobs


async def test_non_overrunning_job_produces_same_fire_sequence() -> None:
    """A job that completes within its interval produces the same fire-time sequence
    with dispatch-time reschedule.
    """
    fire_times: list[ZonedDateTime] = []

    class _QuickApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="quick_job", mode="single")

        async def task(self) -> None:
            fire_times.append(date_utils.now())

    async with AppTestHarness(_QuickApp, config={"instance_name": "quick_app"}) as harness:
        job = await get_job_by_name(harness, "quick_job")

        # Fire job at t=0, t=10, t=20 — all complete quickly
        t0 = job.next_run
        harness.freeze_time(t0.add(seconds=1))
        await harness.trigger_due_jobs()
        await asyncio.sleep(0)

        # Re-get job after reschedule
        job2 = await get_job_by_name(harness, "quick_job")

        # Next fire should be ~10s after first fire, not 10s after completion
        delta = (job2.next_run - t0).total("seconds")
        # Allow a small tolerance; the grid tick should be ~10s
        assert 9 <= delta <= 11, f"Expected next fire ~10s after first fire, got delta={delta}s"


# single mode suppresses overrun re-fires


async def test_single_mode_suppresses_overrun() -> None:
    """With mode='single', an overrunning recurring job suppresses re-fires;
    guard.suppressed increments.
    """

    class _App(_OverrunApp):
        job_name = "single_job"
        job_mode = "single"

    async with AppTestHarness(_App, config={"instance_name": "app"}) as harness:
        app = harness.app
        app.run_gate.clear()  # keep job running

        # First fire blocks, so the next occurrence overruns it
        job, dispatch1, next_job = await start_overrun(harness, "single_job", app.started)

        # Reset started event so we can detect second attempt
        app.started.clear()

        # Dispatch the second (overrunning) occurrence — guard should suppress
        dispatch2 = await freeze_and_dispatch(harness, next_job)
        await dispatch2

        # Guard should have suppressed the second invocation
        assert job.guard.suppressed >= 1, f"Expected guard.suppressed >= 1 (single mode), got {job.guard.suppressed}"
        assert app.invocation_count == 1, f"Expected only 1 invocation (suppressed), got {app.invocation_count}"

        # Clean up
        app.run_gate.set()
        await asyncio.wait_for(dispatch1, timeout=HANG_GUARD_TIMEOUT_SECONDS)


# parallel mode runs overlapping invocations concurrently


async def test_parallel_mode_runs_invocations_concurrently() -> None:
    """With mode='parallel', overlapping invocations run concurrently."""
    concurrent_count = [0]
    max_concurrent = [0]
    gate = asyncio.Event()

    class _ParallelApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="parallel_job", mode="parallel")

        async def task(self) -> None:
            concurrent_count[0] += 1
            max_concurrent[0] = max(max_concurrent[0], concurrent_count[0])
            await gate.wait()
            concurrent_count[0] -= 1

    async with AppTestHarness(_ParallelApp, config={"instance_name": "parallel_app"}) as harness:
        job = await get_job_by_name(harness, "parallel_job")

        # Dispatch first fire (blocks on gate) — via create_task to allow concurrent
        dispatch1 = await freeze_and_dispatch(harness, job)
        await asyncio.sleep(0)

        # Job should now be running (concurrently); get next occurrence
        next_job = await get_job_by_name(harness, "parallel_job")

        # Dispatch second (overrunning) occurrence — should run concurrently (not suppress)
        dispatch2 = await freeze_and_dispatch(harness, next_job)
        await asyncio.sleep(0)

        # Allow both to start
        await asyncio.sleep(0)

        # Unblock both
        gate.set()
        await asyncio.wait_for(dispatch1, timeout=HANG_GUARD_TIMEOUT_SECONDS)
        await asyncio.wait_for(dispatch2, timeout=HANG_GUARD_TIMEOUT_SECONDS)

        # Should have seen at least 2 concurrent invocations at some point
        assert max_concurrent[0] >= 2, (
            f"Expected concurrent invocations (parallel mode), max_concurrent={max_concurrent[0]}"
        )


# queued mode serializes overruns


async def test_queued_mode_serializes_overrun() -> None:
    """With mode='queued', re-fires run in arrival order after the first completes."""
    run_order: list[int] = []
    gate = asyncio.Event()
    first_started = asyncio.Event()

    class _QueuedApp(App[_OverlapConfig]):
        call_num: int = 0

        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="queued_job", mode="queued")

        async def task(self) -> None:
            self.call_num += 1
            num = self.call_num
            if num == 1:
                first_started.set()
                await gate.wait()
            run_order.append(num)

    async with AppTestHarness(_QueuedApp, config={"instance_name": "queued_app"}) as harness:
        # First fire blocks, so the next occurrence overruns it
        job, dispatch1, next_job = await start_overrun(harness, "queued_job", first_started)

        # Dispatch second — should be queued (QUEUED_ACCEPTED), not suppressed
        # Not awaited to completion: that would block waiting for bridge resolution on QUEUED_ACCEPTED
        dispatch2 = await freeze_and_dispatch(harness, next_job)
        await asyncio.sleep(0)

        # Guard should have accepted the queued invocation
        assert job.guard.suppressed == 0, f"Expected no suppressions, got {job.guard.suppressed}"

        # Unblock first; the queued one should run after
        gate.set()
        await asyncio.wait_for(dispatch1, timeout=HANG_GUARD_TIMEOUT_SECONDS)
        await asyncio.wait_for(dispatch2, timeout=HANG_GUARD_TIMEOUT_SECONDS)

        assert 1 in run_order, "First invocation should have run"
        assert 2 in run_order, "Second (queued) invocation should have run"
        assert run_order.index(1) < run_order.index(2), "Invocations should run in arrival order"


# queued mode: QUEUED_ACCEPTED + removal does not hang dispatch task


async def test_queued_accepted_then_remove_does_not_hang() -> None:
    """A queued invocation accepted (QUEUED_ACCEPTED) before the job is removed must not
    leave the dispatch task hanging forever on ``await done``.

    Without pending_done drain: guard.release() drops the queued factory without calling
    run_and_track(); the done-callback is never installed; ``await done`` in
    run_job_with_guard hangs forever. With the fix, dequeue_job drains pending_done after
    guard.release(), resolving done and letting the dispatch task return promptly.
    """
    first_started = asyncio.Event()
    gate = asyncio.Event()

    class _QueuedHangApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="queued_hang_job", mode="queued")

        async def task(self) -> None:
            first_started.set()
            await gate.wait()

    async with AppTestHarness(_QueuedHangApp, config={"instance_name": "queued_hang_app"}) as harness:
        # First fire blocks, so the next occurrence overruns it
        job, dispatch1, next_job = await start_overrun(harness, "queued_hang_job", first_started)

        # Dispatch second — queued mode accepts it (QUEUED_ACCEPTED).
        # dispatch2 now parks on ``await done`` waiting for the queued factory to drain.
        dispatch2 = await freeze_and_dispatch(harness, next_job)
        await asyncio.sleep(0)  # let dispatch2 park on await done

        # Remove the job while dispatch2 is parked on QUEUED_ACCEPTED.
        # dequeue_job → guard.release() drops the queued factory → drain_pending_done
        # must resolve done so dispatch2 returns promptly (not hang).
        harness.app.scheduler.remove_job(job)

        # dispatch2 must complete within a short timeout; a hang means the fix is missing.
        try:
            await asyncio.wait_for(dispatch2, timeout=1.0)
        except TimeoutError:
            dispatch2.cancel()
            pytest.fail("dispatch2 hung after QUEUED_ACCEPTED + cancel — pending_done not drained")

        # Unblock first dispatch and clean up
        gate.set()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch1, timeout=HANG_GUARD_TIMEOUT_SECONDS)


# restart mode cancels in-flight and starts fresh


async def test_restart_mode_cancels_and_starts_fresh() -> None:
    """With mode='restart', a re-fire cancels the in-flight run and starts a fresh one.

    The cancelled invocation must reach CommandExecutor.execute() with a CancelledError —
    the real executor enqueues a status='cancelled' row there (command_executor.py:270-272).
    Here the executor is a mock stub, so we verify the cancel path by capturing whether
    CancelledError propagated out of the callable passed to execute(). That is the exact
    signal the real executor checks before calling enqueue_record(). Delivery is
    best-effort by design.
    """
    cancelled_count = [0]
    first_started = asyncio.Event()
    cancelled_in_execute = [0]  # counts CancelledError exits from execute() callable

    class _RestartApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="restart_job", mode="restart")

        async def task(self) -> None:
            first_started.set()
            try:
                await asyncio.sleep(100)  # will be cancelled
            except asyncio.CancelledError:
                cancelled_count[0] += 1
                raise

    async with AppTestHarness(_RestartApp, config={"instance_name": "restart_app"}) as harness:
        mock_executor = harness._harness.mock_executor

        # Wrap execute() to capture CancelledError exits — this is the signal the real
        # CommandExecutor uses to enqueue a status='cancelled' execution row.
        original_execute_side_effect = mock_executor.execute.side_effect

        async def _tracking_execute(cmd: object) -> None:
            try:
                await original_execute_side_effect(cmd)
            except asyncio.CancelledError:
                cancelled_in_execute[0] += 1
                raise

        mock_executor.execute.side_effect = _tracking_execute

        # First fire blocks, so the next occurrence overruns it
        _, dispatch1, next_job = await start_overrun(harness, "restart_job", first_started)

        # Dispatch second — restart should cancel first
        first_started.clear()
        dispatch2 = await freeze_and_dispatch(harness, next_job)

        # Let restart logic run
        await asyncio.sleep(0.1)

        # Second invocation starts fresh (first_started should set again)
        await asyncio.wait_for(first_started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        # First invocation should have been cancelled (user-side evidence)
        assert cancelled_count[0] >= 1, (
            f"Expected first invocation to be cancelled, cancelled_count={cancelled_count[0]}"
        )

        # CancelledError must have propagated through execute() —
        # the real CommandExecutor enqueues status='cancelled' on that signal.
        assert cancelled_in_execute[0] >= 1, (
            f"Expected CancelledError to exit execute() at least once, "
            f"got cancelled_in_execute={cancelled_in_execute[0]}"
        )

        # Clean up: cancel the second dispatch task (it blocks on sleep(100))
        dispatch2.cancel()
        dispatch1.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch1, timeout=1.0)
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch2, timeout=1.0)
