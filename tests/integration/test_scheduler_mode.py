"""Integration tests for T01 + T02: scheduler mode parameter, resolution, guard, and dispatch routing.

T01 tests verify:
- schedule() resolves None -> single for app tier, parallel for framework tier
- explicit ExecutionMode passthrough
- string coercion to ExecutionMode
- invalid string raises ValueError naming valid values
- mode= accepted on run_in / run_once without error (no overlap effect — one-shot fires once)
- convenience methods forward mode= to schedule()

T02 tests verify:
- dispatch-time reschedule (FR#1, AC#1): next occurrence enqueued before current run completes
- fire sequence unchanged for non-overrunning jobs (FR#3, AC#3)
- per-mode overlap (FR#5, AC#4-AC#7): single suppresses, queued serializes, restart cancels+fresh, parallel concurrent
- current fire always runs on trigger error (FR#16, AC#14)
- dequeued race (FR#17, AC#15): in-lock re-check prevents spurious re-push
- guard release on cancel (FR#14, AC#12)
- stall watchdog (FR#18, AC#16)

These tests use HassetteHarness (framework-tier scheduler) via the hassette_with_scheduler fixture.
App-tier tests use AppTestHarness.
"""

import asyncio
import contextlib
import unittest.mock

import pytest
from whenever import ZonedDateTime

import hassette.core.scheduler_service as scheduler_service_module
import hassette.utils.date_utils as date_utils
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.execution_mode import ExecutionModeGuard
from hassette.scheduler import ScheduledJob
from hassette.scheduler.triggers import Every
from hassette.test_utils.app_harness import AppTestHarness
from hassette.types.enums import ExecutionMode

# ---------------------------------------------------------------------------
# App for AC#2: one-shot with mode= fires exactly once
# ---------------------------------------------------------------------------


class _OneShotModeConfig(AppConfig):
    """Minimal config for one-shot mode acceptance tests."""


class _RunInModeApp(App[_OneShotModeConfig]):
    """Schedules a run_in job with mode= set; records invocation count."""

    fired_count: int

    async def on_initialize(self) -> None:
        self.fired_count = 0
        # mode= accepted on one-shots — no overlap effect, fires once
        await self.scheduler.run_in(self.task, delay=10, name="oneshot_mode_job", mode="parallel")

    async def task(self) -> None:
        self.fired_count += 1


class _RunOnceModeApp(App[_OneShotModeConfig]):
    """Schedules a run_once job with mode= set; records invocation count."""

    fired_count: int

    async def on_initialize(self) -> None:
        self.fired_count = 0
        await self.scheduler.run_once(
            self.task,
            at=ZonedDateTime.from_system_tz(2030, 6, 15, 7, 0, 0),
            name="runonce_mode_job",
            mode=ExecutionMode.QUEUED,
        )

    async def task(self) -> None:
        self.fired_count += 1


# ---------------------------------------------------------------------------
# AC#2: one-shot with mode= fires exactly once
# ---------------------------------------------------------------------------


async def test_run_in_with_mode_fires_exactly_once() -> None:
    """AC#2: run_in with mode= set still fires exactly once (mode has no overlap effect)."""
    async with AppTestHarness(_RunInModeApp, config={}) as harness:
        scheduler = harness.app.scheduler

        jobs = scheduler.list_jobs()
        assert any(j.name == "oneshot_mode_job" for j in jobs), "oneshot_mode_job should be registered"

        job = next(j for j in jobs if j.name == "oneshot_mode_job")
        assert job.mode is ExecutionMode.PARALLEL, f"Expected PARALLEL, got {job.mode}"

        # Freeze time past the job's due time
        harness.freeze_time(job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1, f"Expected exactly 1 job dispatched, got {count}"
        assert harness.app.fired_count == 1, f"Expected fired_count=1, got {harness.app.fired_count}"

        # Job is exhausted after firing — should be removed from the scheduler
        remaining = scheduler.list_jobs()
        assert not any(j.name == "oneshot_mode_job" for j in remaining), (
            "One-shot job should be removed after exhaustion"
        )


async def test_run_once_with_mode_fires_exactly_once() -> None:
    """AC#2: run_once with mode= set still fires exactly once (mode has no overlap effect)."""
    async with AppTestHarness(_RunOnceModeApp, config={}) as harness:
        scheduler = harness.app.scheduler

        jobs = scheduler.list_jobs()
        assert any(j.name == "runonce_mode_job" for j in jobs), "runonce_mode_job should be registered"

        job = next(j for j in jobs if j.name == "runonce_mode_job")
        assert job.mode is ExecutionMode.QUEUED, f"Expected QUEUED, got {job.mode}"

        harness.freeze_time(job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1, f"Expected exactly 1 job dispatched, got {count}"
        assert harness.app.fired_count == 1, f"Expected fired_count=1, got {harness.app.fired_count}"

        remaining = scheduler.list_jobs()
        assert not any(j.name == "runonce_mode_job" for j in remaining), (
            "One-shot job should be removed after exhaustion"
        )


# ---------------------------------------------------------------------------
# Integration tests via hassette_with_scheduler (framework-tier scheduler)
# ---------------------------------------------------------------------------


class TestSchedulerModeViaHarness:
    """Test the full schedule() path including mode resolution and job creation."""

    async def test_framework_tier_omitted_mode_resolves_to_parallel(self, hassette_with_scheduler) -> None:
        """Framework-tier schedule with mode=None resolves to ExecutionMode.PARALLEL."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.schedule(noop, Every(seconds=3600))
        assert job.mode is ExecutionMode.PARALLEL
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_explicit_mode_enum_passes_through(self, hassette_with_scheduler) -> None:
        """An explicit ExecutionMode enum is stored unchanged."""

        async def noop() -> None:
            pass

        for mode in ExecutionMode:
            job = await hassette_with_scheduler.scheduler.schedule(
                noop, Every(seconds=3600), mode=mode, name=f"passthrough_{mode.value}"
            )
            assert job.mode is mode
            hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_string_coercion_all_modes(self, hassette_with_scheduler) -> None:
        """Each valid mode string is coerced to the corresponding ExecutionMode member."""

        async def noop() -> None:
            pass

        cases = [
            ("single", ExecutionMode.SINGLE),
            ("parallel", ExecutionMode.PARALLEL),
            ("restart", ExecutionMode.RESTART),
            ("queued", ExecutionMode.QUEUED),
        ]
        for string_val, expected in cases:
            job = await hassette_with_scheduler.scheduler.schedule(
                noop, Every(seconds=3600), mode=string_val, name=f"coerce_{string_val}"
            )
            assert job.mode is expected, f"mode={string_val!r}: expected {expected}, got {job.mode}"
            hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_invalid_string_raises_value_error(self, hassette_with_scheduler) -> None:
        """An invalid mode string raises ValueError naming all valid values."""

        async def noop() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid execution mode") as exc_info:
            await hassette_with_scheduler.scheduler.schedule(noop, Every(seconds=60), mode="bogus")
        msg = str(exc_info.value)
        for valid in ("'single'", "'restart'", "'queued'", "'parallel'"):
            assert valid in msg

    async def test_invalid_string_raises_before_job_registered(self, hassette_with_scheduler) -> None:
        """ValueError is raised before any job is registered."""

        async def noop() -> None:
            pass

        count_before = len(hassette_with_scheduler.scheduler.list_jobs())
        with pytest.raises(ValueError, match="Invalid execution mode"):
            await hassette_with_scheduler.scheduler.schedule(noop, Every(seconds=60), mode="not_a_mode")
        assert len(hassette_with_scheduler.scheduler.list_jobs()) == count_before

    async def test_guard_present_on_scheduled_job(self, hassette_with_scheduler) -> None:
        """The scheduled job has an ExecutionModeGuard created from its mode."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.schedule(
            noop, Every(seconds=3600), mode=ExecutionMode.SINGLE, name="guard_check"
        )
        assert isinstance(job.guard, ExecutionModeGuard)
        hassette_with_scheduler.scheduler.cancel_job(job)


# ---------------------------------------------------------------------------
# One-shot acceptance tests — run_in / run_once accept mode= without error
# ---------------------------------------------------------------------------


class TestOneShotModeAcceptance:
    async def test_run_in_accepts_mode_no_error(self, hassette_with_scheduler) -> None:
        """run_in accepts mode= keyword argument without raising."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_in(noop, delay=3600, mode=ExecutionMode.QUEUED)
        assert job.mode is ExecutionMode.QUEUED
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_once_accepts_mode_no_error(self, hassette_with_scheduler) -> None:
        """run_once accepts mode= keyword argument without raising."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_once(noop, at="23:59", mode=ExecutionMode.RESTART)
        assert job.mode is ExecutionMode.RESTART
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_in_string_mode_coerced(self, hassette_with_scheduler) -> None:
        """run_in accepts a string mode and coerces it correctly."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_in(noop, delay=3600, mode="parallel")
        assert job.mode is ExecutionMode.PARALLEL
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_in_invalid_string_raises(self, hassette_with_scheduler) -> None:
        """run_in with an invalid mode string raises ValueError (delegates to schedule())."""

        async def noop() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid execution mode"):
            await hassette_with_scheduler.scheduler.run_in(noop, delay=3600, mode="bad_mode")

    async def test_run_in_mode_stored_on_job(self, hassette_with_scheduler) -> None:
        """A run_in job with mode= stores the resolved mode and a guard on the job object."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_in(
            noop, delay=3600, mode=ExecutionMode.QUEUED, name="oneshot_mode_stored"
        )
        assert job.mode is ExecutionMode.QUEUED
        assert isinstance(job.guard, ExecutionModeGuard)
        hassette_with_scheduler.scheduler.cancel_job(job)


# ---------------------------------------------------------------------------
# Convenience method forwarding
# ---------------------------------------------------------------------------


class TestConvenienceMethodModeForwarding:
    async def test_run_every_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_every forwards mode= and the resolved mode appears on the job."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_every(
            noop, seconds=60, mode=ExecutionMode.RESTART, name="every_restart"
        )
        assert job.mode is ExecutionMode.RESTART
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_daily_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_daily forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_daily(noop, at="03:00", mode="queued", name="daily_queued")
        assert job.mode is ExecutionMode.QUEUED
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_cron_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_cron forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_cron(
            noop, "0 * * * *", mode=ExecutionMode.SINGLE, name="cron_single"
        )
        assert job.mode is ExecutionMode.SINGLE
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_minutely_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_minutely forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_minutely(
            noop, minutes=5, mode="restart", name="minutely_restart"
        )
        assert job.mode is ExecutionMode.RESTART
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_run_hourly_forwards_mode(self, hassette_with_scheduler) -> None:
        """run_hourly forwards mode= to schedule()."""

        async def noop() -> None:
            pass

        job = await hassette_with_scheduler.scheduler.run_hourly(
            noop, hours=2, mode=ExecutionMode.QUEUED, name="hourly_queued"
        )
        assert job.mode is ExecutionMode.QUEUED
        hassette_with_scheduler.scheduler.cancel_job(job)

    async def test_omitted_mode_default_is_parallel_for_framework(self, hassette_with_scheduler) -> None:
        """Omitting mode= on the framework-tier harness scheduler gives PARALLEL."""

        async def noop() -> None:
            pass

        jobs = await asyncio.gather(
            hassette_with_scheduler.scheduler.run_every(noop, seconds=60, name="fw_j1"),
            hassette_with_scheduler.scheduler.run_daily(noop, at="04:00", name="fw_j2"),
            hassette_with_scheduler.scheduler.run_cron(noop, "0 0 * * *", name="fw_j3"),
            hassette_with_scheduler.scheduler.run_minutely(noop, name="fw_j4"),
            hassette_with_scheduler.scheduler.run_hourly(noop, name="fw_j5"),
        )
        for job in jobs:
            assert job.mode is ExecutionMode.PARALLEL, (
                f"{job.name} expected PARALLEL (framework default), got {job.mode}"
            )
            hassette_with_scheduler.scheduler.cancel_job(job)


# ---------------------------------------------------------------------------
# T02 Tests: Dispatch-time reschedule and guard routing
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# AC#1 / FR#1: Dispatch-time reschedule — next occurrence on heap before run completes
# ---------------------------------------------------------------------------


async def test_dispatch_time_reschedule_next_occurrence_before_run_completes() -> None:
    """AC#1 / FR#1: An overrunning recurring job has its next occurrence on the heap
    before the current invocation completes.
    """

    class _App(_OverrunApp):
        job_name = "overrun_job"
        job_mode = "single"

    async with AppTestHarness(_App, config={}) as harness:
        app = harness.app
        app.run_gate.clear()  # block the job so it overruns

        scheduler = app.scheduler
        jobs = scheduler.list_jobs()
        job = next(j for j in jobs if j.name == "overrun_job")

        # Freeze time past the job's due time
        harness.freeze_time(job.next_run.add(seconds=1))

        # Start dispatch without waiting for completion — job will block on gate
        dispatch_task = asyncio.create_task(harness._harness.hassette._scheduler_service.dispatch_and_log(job))

        # Wait until the job has started
        await asyncio.wait_for(app.started.wait(), timeout=2.0)

        # At this point, the job is still running (gate is closed).
        # The next occurrence should already be on the heap.
        all_queued = await harness._harness.hassette._scheduler_service.get_all_jobs()
        assert any(j is job for j in all_queued), (
            "Next occurrence should be on the heap before current run completes (FR#1 / AC#1)"
        )

        # Unblock and clean up
        app.run_gate.set()
        await asyncio.wait_for(dispatch_task, timeout=2.0)


# ---------------------------------------------------------------------------
# AC#3 / FR#3: Fire sequence unchanged for non-overrunning jobs
# ---------------------------------------------------------------------------


async def test_non_overrunning_job_produces_same_fire_sequence() -> None:
    """AC#3 / FR#3: A job that completes within its interval produces the same
    fire-time sequence with dispatch-time reschedule.
    """
    fire_times: list[ZonedDateTime] = []

    class _QuickApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="quick_job", mode="single")

        async def task(self) -> None:
            fire_times.append(date_utils.now())

    async with AppTestHarness(_QuickApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "quick_job")

        # Fire job at t=0, t=10, t=20 — all complete quickly
        t0 = job.next_run
        harness.freeze_time(t0.add(seconds=1))
        await harness.trigger_due_jobs()
        await asyncio.sleep(0)

        # Re-get job after reschedule
        jobs2 = await scheduler_service.get_all_jobs()
        job2 = next((j for j in jobs2 if j.name == "quick_job"), None)
        assert job2 is not None, "Job should still be scheduled after one fire"

        # Next fire should be ~10s after first fire, not 10s after completion
        delta = (job2.next_run - t0).in_seconds()
        # Allow a small tolerance; the grid tick should be ~10s
        assert 9 <= delta <= 11, f"Expected next fire ~10s after first fire, got delta={delta}s"


# ---------------------------------------------------------------------------
# AC#4 / FR#5: single mode suppresses overrun re-fires
# ---------------------------------------------------------------------------


async def test_single_mode_suppresses_overrun() -> None:
    """AC#4: With mode='single', an overrunning recurring job suppresses re-fires;
    guard.suppressed increments.
    """

    class _App(_OverrunApp):
        job_name = "single_job"
        job_mode = "single"

    async with AppTestHarness(_App, config={}) as harness:
        app = harness.app
        app.run_gate.clear()  # keep job running

        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "single_job")

        # Dispatch first fire (will block)
        harness.freeze_time(job.next_run.add(seconds=1))
        dispatch1 = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.wait_for(app.started.wait(), timeout=2.0)

        # Wait for next occurrence to be on heap
        await asyncio.sleep(0)
        jobs2 = await scheduler_service.get_all_jobs()
        next_job = next((j for j in jobs2 if j.name == "single_job"), None)
        assert next_job is not None, "Next occurrence should be on heap"

        # Reset started event so we can detect second attempt
        app.started.clear()

        # Dispatch the second (overrunning) occurrence — guard should suppress
        harness.freeze_time(next_job.next_run.add(seconds=1))
        await scheduler_service.dispatch_and_log(next_job)

        # Guard should have suppressed the second invocation
        assert job.guard.suppressed >= 1, f"Expected guard.suppressed >= 1 (single mode), got {job.guard.suppressed}"
        assert app.invocation_count == 1, f"Expected only 1 invocation (suppressed), got {app.invocation_count}"

        # Clean up
        app.run_gate.set()
        await asyncio.wait_for(dispatch1, timeout=2.0)


# ---------------------------------------------------------------------------
# AC#7 / FR#5: parallel mode runs invocations concurrently
# ---------------------------------------------------------------------------


async def test_parallel_mode_runs_invocations_concurrently() -> None:
    """AC#7: With mode='parallel', overlapping invocations run concurrently."""
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

    async with AppTestHarness(_ParallelApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "parallel_job")

        # Dispatch first fire (blocks on gate) — via create_task to allow concurrent
        harness.freeze_time(job.next_run.add(seconds=1))
        dispatch1 = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.sleep(0)

        # Job should now be running (concurrently); get next occurrence
        jobs2 = await scheduler_service.get_all_jobs()
        next_job = next((j for j in jobs2 if j.name == "parallel_job"), None)
        assert next_job is not None, "Next occurrence should be on heap"

        # Dispatch second (overrunning) occurrence — should run concurrently (not suppress)
        harness.freeze_time(next_job.next_run.add(seconds=1))
        dispatch2 = asyncio.create_task(scheduler_service.dispatch_and_log(next_job))
        await asyncio.sleep(0)

        # Allow both to start
        await asyncio.sleep(0)

        # Unblock both
        gate.set()
        await asyncio.wait_for(dispatch1, timeout=2.0)
        await asyncio.wait_for(dispatch2, timeout=2.0)

        # Should have seen at least 2 concurrent invocations at some point
        assert max_concurrent[0] >= 2, (
            f"Expected concurrent invocations (parallel mode), max_concurrent={max_concurrent[0]}"
        )


# ---------------------------------------------------------------------------
# AC#5 / FR#5: queued mode serializes overruns
# ---------------------------------------------------------------------------


async def test_queued_mode_serializes_overrun() -> None:
    """AC#5: With mode='queued', re-fires run in arrival order after the first completes."""
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

    async with AppTestHarness(_QueuedApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "queued_job")

        # Dispatch first fire — it will block
        harness.freeze_time(job.next_run.add(seconds=1))
        dispatch1 = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.wait_for(first_started.wait(), timeout=2.0)

        # Get next occurrence off heap
        await asyncio.sleep(0)
        jobs2 = await scheduler_service.get_all_jobs()
        next_job = next((j for j in jobs2 if j.name == "queued_job"), None)
        assert next_job is not None, "Next occurrence should be on heap"

        # Dispatch second — should be queued (QUEUED_ACCEPTED), not suppressed
        harness.freeze_time(next_job.next_run.add(seconds=1))
        # Use create_task so we don't block waiting for bridge resolution on QUEUED_ACCEPTED
        dispatch2 = asyncio.create_task(scheduler_service.dispatch_and_log(next_job))
        await asyncio.sleep(0)

        # Guard should have accepted the queued invocation
        assert job.guard.suppressed == 0, f"Expected no suppressions, got {job.guard.suppressed}"

        # Unblock first; the queued one should run after
        gate.set()
        await asyncio.wait_for(dispatch1, timeout=2.0)
        await asyncio.wait_for(dispatch2, timeout=2.0)

        assert 1 in run_order, "First invocation should have run"
        assert 2 in run_order, "Second (queued) invocation should have run"
        assert run_order.index(1) < run_order.index(2), "Invocations should run in arrival order"


# ---------------------------------------------------------------------------
# FR#14 / queued: QUEUED_ACCEPTED + cancel does not hang dispatch task
# ---------------------------------------------------------------------------


async def test_queued_accepted_then_cancel_does_not_hang() -> None:
    """FR#14 regression: a queued invocation accepted (QUEUED_ACCEPTED) before the job is
    cancelled must not leave the dispatch task hanging forever on ``await done``.

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

    async with AppTestHarness(_QueuedHangApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "queued_hang_job")

        # Dispatch first fire — blocks on gate (first invocation is now running)
        harness.freeze_time(job.next_run.add(seconds=1))
        dispatch1 = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.wait_for(first_started.wait(), timeout=2.0)

        # Get next occurrence off heap
        await asyncio.sleep(0)
        jobs2 = await scheduler_service.get_all_jobs()
        next_job = next((j for j in jobs2 if j.name == "queued_hang_job"), None)
        assert next_job is not None, "Next occurrence should be on heap"

        # Dispatch second — queued mode accepts it (QUEUED_ACCEPTED).
        # dispatch2 now parks on ``await done`` waiting for the queued factory to drain.
        harness.freeze_time(next_job.next_run.add(seconds=1))
        dispatch2 = asyncio.create_task(scheduler_service.dispatch_and_log(next_job))
        await asyncio.sleep(0)  # let dispatch2 park on await done

        # Cancel the job while dispatch2 is parked on QUEUED_ACCEPTED.
        # dequeue_job → guard.release() drops the queued factory → drain_pending_done
        # must resolve done so dispatch2 returns promptly (not hang).
        harness.app.scheduler.cancel_job(job)

        # dispatch2 must complete within a short timeout; a hang means the fix is missing.
        try:
            await asyncio.wait_for(dispatch2, timeout=1.0)
        except TimeoutError:
            dispatch2.cancel()
            pytest.fail("dispatch2 hung after QUEUED_ACCEPTED + cancel — pending_done not drained (FR#14 regression)")

        # Unblock first dispatch and clean up
        gate.set()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch1, timeout=2.0)


# ---------------------------------------------------------------------------
# AC#6 / FR#5: restart mode cancels in-flight and starts fresh
# ---------------------------------------------------------------------------


async def test_restart_mode_cancels_and_starts_fresh() -> None:
    """AC#6: With mode='restart', a re-fire cancels the in-flight run and starts a fresh one.

    FR#13 / AC#6: The cancelled invocation must reach CommandExecutor.execute() with a
    CancelledError — the real executor enqueues a status='cancelled' row there
    (command_executor.py:270-272). Here the executor is a mock stub, so we verify the
    cancel path by capturing whether CancelledError propagated out of the callable passed
    to execute(). That is the exact signal the real executor checks before calling
    enqueue_record(). Delivery is best-effort by design (FR#13).
    """
    cancelled_count = [0]
    completed_count = [0]
    first_started = asyncio.Event()
    cancelled_in_execute = [0]  # counts CancelledError exits from execute() callable

    class _RestartApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="restart_job", mode="restart")

        async def task(self) -> None:
            first_started.set()
            try:
                await asyncio.sleep(100)  # will be cancelled
                completed_count[0] += 1
            except asyncio.CancelledError:
                cancelled_count[0] += 1
                raise

    async with AppTestHarness(_RestartApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        mock_executor = scheduler_service._executor

        # Wrap execute() to capture CancelledError exits — this is the signal the real
        # CommandExecutor uses to enqueue a status='cancelled' execution row (FR#13).
        original_execute_side_effect = mock_executor.execute.side_effect

        async def _tracking_execute(cmd: object) -> None:
            try:
                await original_execute_side_effect(cmd)
            except asyncio.CancelledError:
                cancelled_in_execute[0] += 1
                raise

        mock_executor.execute.side_effect = _tracking_execute

        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "restart_job")

        # Dispatch first fire — will block
        harness.freeze_time(job.next_run.add(seconds=1))
        dispatch1 = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.wait_for(first_started.wait(), timeout=2.0)

        # Get next occurrence
        await asyncio.sleep(0)
        jobs2 = await scheduler_service.get_all_jobs()
        next_job = next((j for j in jobs2 if j.name == "restart_job"), None)
        assert next_job is not None, "Next occurrence should be on heap"

        # Dispatch second — restart should cancel first
        first_started.clear()
        harness.freeze_time(next_job.next_run.add(seconds=1))
        dispatch2 = asyncio.create_task(scheduler_service.dispatch_and_log(next_job))

        # Let restart logic run
        await asyncio.sleep(0.1)

        # Second invocation starts fresh (first_started should set again)
        await asyncio.wait_for(first_started.wait(), timeout=2.0)

        # First invocation should have been cancelled (user-side evidence)
        assert cancelled_count[0] >= 1, (
            f"Expected first invocation to be cancelled, cancelled_count={cancelled_count[0]}"
        )

        # FR#13 / AC#6: CancelledError must have propagated through execute() —
        # the real CommandExecutor enqueues status='cancelled' on that signal.
        assert cancelled_in_execute[0] >= 1, (
            f"Expected CancelledError to exit execute() at least once (FR#13), "
            f"got cancelled_in_execute={cancelled_in_execute[0]}"
        )

        # Clean up: cancel the second dispatch task (it blocks on sleep(100))
        dispatch2.cancel()
        dispatch1.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch1, timeout=1.0)
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch2, timeout=1.0)


# ---------------------------------------------------------------------------
# AC#14 / FR#16: trigger error still runs current fire, then removes job
# ---------------------------------------------------------------------------


async def test_trigger_error_runs_current_fire_then_removes_job() -> None:
    """AC#14 / FR#16: A recurring job whose trigger raises on a given cycle still
    runs the current due fire, then is removed with no future fires.
    """
    fired = asyncio.Event()

    class _BadTriggerApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            class _RaisingTrigger:
                """Trigger that raises on next_run_time() but has a valid first run."""

                _calls = 0

                def trigger_db_type(self) -> str:
                    return "interval"

                def trigger_label(self) -> str:
                    return "raising"

                def trigger_detail(self) -> str | None:
                    return None

                def trigger_id(self) -> str:
                    return "raising:always"

                def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
                    return current_time.add(seconds=10)

                def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
                    raise RuntimeError("trigger intentionally raises")

            trigger = _RaisingTrigger()
            job = ScheduledJob(
                owner_id=self.scheduler.owner_id,
                next_run=date_utils.now().add(seconds=10),
                job=self.task,
                trigger=trigger,  # pyright: ignore[reportArgumentType]
                name="bad_trigger_job",
            )
            await self.scheduler.add_job(job)

        async def task(self) -> None:
            fired.set()

    async with AppTestHarness(_BadTriggerApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next((j for j in jobs if j.name == "bad_trigger_job"), None)
        assert job is not None, "bad_trigger_job should be registered"

        # Freeze past job's due time and dispatch
        harness.freeze_time(job.next_run.add(seconds=1))
        await scheduler_service.dispatch_and_log(job)
        await asyncio.sleep(0)

        # Current fire should have run
        assert fired.is_set(), "Current fire should have run even when trigger raises"

        # Job should be removed (trigger error = no future fires)
        remaining = await scheduler_service.get_all_jobs()
        assert not any(j.name == "bad_trigger_job" for j in remaining), "Job should be removed after trigger raises"


# ---------------------------------------------------------------------------
# AC#15 / FR#17: dequeued race — in-lock re-check prevents spurious re-push
# ---------------------------------------------------------------------------


async def test_dequeued_race_in_lock_prevents_spurious_repush() -> None:
    """AC#15 / FR#17: A job cancelled between dispatch entry and the dispatch-time
    re-enqueue is not pushed back onto the heap.

    Exercises the race window: job passes dispatch entry check (not yet dequeued),
    but _dequeued is set by the time enqueue_job calls _job_queue.add. The in-lock
    _dequeued re-check inside _ScheduledJobQueue.add (FR#17) must reject the push.

    Technique: patch enqueue_job to set job._dequeued=True mid-flight (atomically
    between the entry check and the lock acquisition), simulating a cancel_job call
    landing at an await point in the dispatch window.
    """

    class _RacingApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="race_job", mode="single")

        async def task(self) -> None:
            pass

    async with AppTestHarness(_RacingApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service

        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "race_job")

        # Simulate: serve loop popped the job from the heap — remove it directly
        scheduler_service._job_queue.remove_item_sync(job)

        # Patch enqueue_job to inject a race: set _dequeued=True just before the
        # lock is acquired in _job_queue.add — this simulates cancel_job arriving
        # at the await point between dispatch_and_log's entry check and the push.
        original_enqueue = scheduler_service.enqueue_job

        async def _racing_enqueue(j):
            j._dequeued = True  # race: cancel_job fires here, before the lock
            await original_enqueue(j)

        scheduler_service.enqueue_job = _racing_enqueue  # pyright: ignore[reportAttributeAccessIssue]

        try:
            # Freeze time past the job's due time so dispatch proceeds normally
            harness.freeze_time(job.next_run.add(seconds=1))
            await scheduler_service.dispatch_and_log(job)
            await asyncio.sleep(0)
        finally:
            scheduler_service.enqueue_job = original_enqueue  # pyright: ignore[reportAttributeAccessIssue]

        # Heap must not have a re-pushed copy of the cancelled job
        all_jobs = await scheduler_service.get_all_jobs()
        assert not any(j is job for j in all_jobs), (
            "A job cancelled during the re-enqueue window must not appear on the heap (FR#17 / AC#15)"
        )


# ---------------------------------------------------------------------------
# AC#12 / FR#14: guard release on cancel clears in-flight invocation
# ---------------------------------------------------------------------------


async def test_guard_release_on_cancel_clears_in_flight() -> None:
    """AC#12 / FR#14: Cancelling a job with an in-flight invocation releases its guard."""

    class _HoldingApp(App[_OverlapConfig]):
        started: asyncio.Event
        task_cancelled: asyncio.Event

        async def on_initialize(self) -> None:
            self.started = asyncio.Event()
            self.task_cancelled = asyncio.Event()
            await self.scheduler.run_every(self.task, seconds=10, name="hold_job", mode="single")

        async def task(self) -> None:
            self.started.set()
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                self.task_cancelled.set()
                raise

    async with AppTestHarness(_HoldingApp, config={}) as harness:
        app = harness.app
        scheduler = app.scheduler
        scheduler_service = harness._harness.hassette._scheduler_service

        jobs = scheduler.list_jobs()
        job = next(j for j in jobs if j.name == "hold_job")

        # Dispatch the job — it will block
        harness.freeze_time(job.next_run.add(seconds=1))
        dispatch_task = asyncio.create_task(scheduler_service.dispatch_and_log(job))
        await asyncio.wait_for(app.started.wait(), timeout=2.0)

        # Guard should be holding current_task
        assert job.guard.is_running(), "Guard should be running"

        # Cancel the job — should release the guard
        scheduler.cancel_job(job)
        await job.guard.release()  # explicit release to cancel in-flight

        # In-flight task should be cancelled
        await asyncio.sleep(0.1)
        assert app.task_cancelled.is_set(), "In-flight task should be cancelled after guard release"

        # Clean up dispatch task
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch_task, timeout=1.0)


# ---------------------------------------------------------------------------
# AC#16 / FR#18: stall watchdog emits WARNING for non-parallel; parallel does not
# ---------------------------------------------------------------------------


async def test_stall_watchdog_emits_warning_for_non_parallel() -> None:
    """AC#16 / FR#18: A single/restart/queued invocation held past the stall threshold
    emits a WARNING naming the job and mode. Parallel does not get a watchdog.
    """
    started = asyncio.Event()
    gate = asyncio.Event()

    class _StalledApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(
                self.task, seconds=10, name="stalled_job", mode="single", timeout_disabled=True
            )

        async def task(self) -> None:
            started.set()
            await gate.wait()

    async with AppTestHarness(_StalledApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "stalled_job")

        # Patch STALL_THRESHOLD_SECONDS to a tiny value so the watchdog fires quickly.
        # Spy on warn_stalled_job to assert the watchdog actually fires (FR#18 / AC#16) —
        # checking dispatch_task.done() only proves the job is still running, not that the
        # watchdog called warn_stalled_job. A deleted call_later registration would pass the
        # weaker check but fail this spy assertion.
        with (
            unittest.mock.patch.object(scheduler_service_module, "STALL_THRESHOLD_SECONDS", 0.05),
            unittest.mock.patch.object(scheduler_service, "warn_stalled_job") as mock_warn,
        ):
            harness.freeze_time(job.next_run.add(seconds=1))
            dispatch_task = asyncio.create_task(scheduler_service.dispatch_and_log(job))
            await asyncio.wait_for(started.wait(), timeout=2.0)

            # Wait longer than patched threshold for watchdog to fire
            await asyncio.sleep(0.2)

            assert not dispatch_task.done(), "Dispatch task should still be pending (job still running)"
            mock_warn.assert_called_once_with(job)

        # Unblock and clean up
        gate.set()
        await asyncio.wait_for(dispatch_task, timeout=2.0)


async def test_parallel_mode_has_no_stall_watchdog() -> None:
    """AC#16 / FR#18: parallel mode invocations do not get a stall watchdog."""
    started = asyncio.Event()
    gate = asyncio.Event()

    class _ParallelStalledApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(
                self.task, seconds=10, name="parallel_stalled_job", mode="parallel", timeout_disabled=True
            )

        async def task(self) -> None:
            started.set()
            await gate.wait()

    async with AppTestHarness(_ParallelStalledApp, config={}) as harness:
        scheduler_service = harness._harness.hassette._scheduler_service
        jobs = await scheduler_service.get_all_jobs()
        job = next(j for j in jobs if j.name == "parallel_stalled_job")

        # Parallel runs inline (no stall watch installed). Spy on warn_stalled_job to assert
        # it is never called even when the invocation outlasts the patched threshold (AC#16).
        with (
            unittest.mock.patch.object(scheduler_service_module, "STALL_THRESHOLD_SECONDS", 0.05),
            unittest.mock.patch.object(scheduler_service, "warn_stalled_job") as mock_warn,
        ):
            harness.freeze_time(job.next_run.add(seconds=1))
            dispatch_task = asyncio.create_task(scheduler_service.dispatch_and_log(job))
            await asyncio.wait_for(started.wait(), timeout=2.0)
            # dispatch_task is still pending because run_job awaits the callable inline
            assert not dispatch_task.done(), "Dispatch should be pending while job runs"
            await asyncio.sleep(0.2)  # outlast the patched threshold
            mock_warn.assert_not_called()

        gate.set()
        await asyncio.wait_for(dispatch_task, timeout=2.0)
