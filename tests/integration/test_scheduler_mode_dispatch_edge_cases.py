"""Integration tests for scheduler dispatch edge cases.

Verifies:
- current fire always runs on trigger error
- dequeued race: in-lock re-check prevents spurious re-push
- guard release on cancel
- stall watchdog

These tests use HassetteHarness (framework-tier scheduler) via the hassette_with_scheduler fixture.
App-tier tests use AppTestHarness.
"""

import asyncio
import contextlib
import logging
import unittest.mock
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from hassette_wire import ScheduleStatus, ScheduleStatusReason
from whenever import ZonedDateTime

import hassette.core.scheduler_dispatch as scheduler_dispatch_module
import hassette.execution_mode as execution_mode_module
import hassette.utils.date_utils as date_utils
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.scheduler import Job
from hassette.testing import AppTestHarness, wait_for
from tests.support.helpers import HANG_GUARD_TIMEOUT_SECONDS
from tests.support.scheduler_dispatch_helpers import (
    freeze_and_dispatch,
    get_job_by_name,
    scheduler_service_for,
    start_overrun,
)


class _OverlapConfig(AppConfig):
    """Minimal config for overlap mode tests."""


def make_gated_app(
    job_name: str, **registration: Any
) -> tuple[type[App[_OverlapConfig]], asyncio.Event, asyncio.Event]:
    """Build an app whose ``job_name`` job signals the first event on start, then waits on the second."""
    started = asyncio.Event()
    gate = asyncio.Event()

    class _GatedApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name=job_name, **registration)

        async def task(self) -> None:
            started.set()
            await gate.wait()

    return _GatedApp, started, gate


@contextlib.contextmanager
def patched_stall_watch(scheduler_service: Any, default_threshold: float) -> Iterator[unittest.mock.MagicMock]:
    """Shrink the default stall threshold and spy on ``warn_stalled_job`` for the duration."""
    with (
        unittest.mock.patch.object(execution_mode_module, "STALL_THRESHOLD_SECONDS", default_threshold),
        unittest.mock.patch.object(scheduler_service, "warn_stalled_job") as mock_warn,
    ):
        yield mock_warn


# Trigger error: current fire runs, then job completes (stays live, no future fires)


async def test_trigger_error_runs_current_fire_then_completes_job() -> None:
    """A recurring job whose trigger raises on a given cycle still runs the current
    due fire, then completes with TRIGGER_ERROR — no future fires, but the job stays
    live and submit-capable.
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
            job = Job(
                owner_id=self.scheduler.owner_id,
                next_run=date_utils.now().add(seconds=10),
                job=self.task,
                trigger=trigger,  # pyright: ignore[reportArgumentType]
                name="bad_trigger_job",
            )
            await self.scheduler.add_job(job)

        async def task(self) -> None:
            fired.set()

    async with AppTestHarness(_BadTriggerApp, config={"instance_name": "bad_trigger_app"}) as harness:
        job = await get_job_by_name(harness, "bad_trigger_job")
        assert job.next_run is not None

        # Freeze past job's due time and dispatch
        harness.freeze_time(job.next_run.add(seconds=1))
        await scheduler_service_for(harness).dispatch_and_log(job)
        await asyncio.sleep(0)

        # Current fire should have run
        assert fired.is_set(), "Current fire should have run even when trigger raises"

        # Job completes (no future fires) but stays live in the per-app registry.
        assert job.schedule_status is ScheduleStatus.COMPLETED
        assert job.schedule_status_reason is ScheduleStatusReason.TRIGGER_ERROR
        assert job.next_run is None

        still_registered = harness.app.scheduler.list_jobs()
        assert any(j is job for j in still_registered), "Job should remain registered after a trigger error"


# Dequeued race: in-lock re-check prevents spurious re-push


async def test_dequeued_race_in_lock_prevents_spurious_repush() -> None:
    """A job cancelled between dispatch entry and the dispatch-time re-enqueue is not
    pushed back onto the heap.

    Exercises the race window: job passes dispatch entry check (not yet dequeued),
    but _dequeued is set by the time enqueue_job calls _job_queue.add. The in-lock
    _dequeued re-check inside _ScheduledJobQueue.add must reject the push.

    Technique: patch enqueue_job to set job._dequeued=True mid-flight (atomically
    between the entry check and the lock acquisition), simulating a cancel_job call
    landing at an await point in the dispatch window.
    """

    class _RacingApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="race_job", mode="single")

        async def task(self) -> None:
            pass

    async with AppTestHarness(_RacingApp, config={"instance_name": "racing_app"}) as harness:
        scheduler_service = scheduler_service_for(harness)
        job = await get_job_by_name(harness, "race_job")

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
            assert job.next_run is not None
            harness.freeze_time(job.next_run.add(seconds=1))
            await scheduler_service.dispatch_and_log(job)
            await asyncio.sleep(0)
        finally:
            scheduler_service.enqueue_job = original_enqueue  # pyright: ignore[reportAttributeAccessIssue]

        # Heap must not have a re-pushed copy of the cancelled job. get_all_jobs() now
        # sources from the live registry (not the heap), so it still finds the job here
        # (its registration was never removed, only its heap occurrence) — check the heap
        # queue directly instead.
        heap_jobs = await scheduler_service._job_queue.get_all()
        assert not any(j is job for j in heap_jobs), (
            "A job cancelled during the re-enqueue window must not appear on the heap"
        )


# Guard release on removal clears in-flight invocation


async def test_guard_release_on_remove_clears_in_flight() -> None:
    """Removing a job with an in-flight invocation releases its guard."""

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

    async with AppTestHarness(_HoldingApp, config={"instance_name": "holding_app"}) as harness:
        app = harness.app
        scheduler = app.scheduler
        job = await get_job_by_name(harness, "hold_job")

        # Dispatch the job — it will block
        dispatch_task = await freeze_and_dispatch(harness, job)
        await asyncio.wait_for(app.started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

        # Guard should be holding current_task
        assert job.guard.is_running(), "Guard should be running"

        # Remove the job — should release the guard
        scheduler.remove_job(job)
        await job.guard.release()  # explicit release to cancel in-flight

        # In-flight task should be cancelled
        await asyncio.sleep(0.1)
        assert app.task_cancelled.is_set(), "In-flight task should be cancelled after guard release"

        # Clean up dispatch task
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(dispatch_task, timeout=1.0)


# Stall watchdog emits WARNING for non-parallel modes; parallel mode has no watchdog


async def test_stall_watchdog_emits_warning_for_non_parallel() -> None:
    """A single/restart/queued invocation held past the stall threshold emits a WARNING
    naming the job and mode. Parallel mode does not get a stall watchdog.
    """
    stalled_app, started, gate = make_gated_app("stalled_job", mode="single", timeout_disabled=True)

    async with AppTestHarness(stalled_app, config={"instance_name": "stalled_app"}) as harness:
        scheduler_service = scheduler_service_for(harness)
        job = await get_job_by_name(harness, "stalled_job")

        # Patch STALL_THRESHOLD_SECONDS to a tiny value so the watchdog fires quickly.
        # Spy on warn_stalled_job to assert the watchdog actually fires —
        # checking dispatch_task.done() only proves the job is still running, not that the
        # watchdog called warn_stalled_job. A deleted call_later registration would pass the
        # weaker check but fail this spy assertion.
        with patched_stall_watch(scheduler_service, 0.05) as mock_warn:
            dispatch_task = await freeze_and_dispatch(harness, job)
            await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

            # Wait longer than patched threshold for watchdog to fire
            await asyncio.sleep(0.2)

            assert not dispatch_task.done(), "Dispatch task should still be pending (job still running)"
            mock_warn.assert_called_once_with(job, 0.05, None)

        # Unblock and clean up
        gate.set()
        await asyncio.wait_for(dispatch_task, timeout=HANG_GUARD_TIMEOUT_SECONDS)


async def test_stall_threshold_derives_from_job_timeout() -> None:
    """A job with its own timeout stays quiet past the default threshold and warns at 80% of the timeout."""
    slow_app, started, gate = make_gated_app("slow_job", mode="single", timeout=0.5)

    async with AppTestHarness(slow_app, config={"instance_name": "slow_app"}) as harness:
        scheduler_service = scheduler_service_for(harness)
        job = await get_job_by_name(harness, "slow_job")

        # The patched default stands in for 60s, and timeout=0.5 stands in for a declared-slow job.
        with patched_stall_watch(scheduler_service, 0.01) as mock_warn:
            dispatch_task = await freeze_and_dispatch(harness, job)
            await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)

            await asyncio.sleep(0.1)  # well past the default threshold, short of the derived one
            mock_warn.assert_not_called()

            await wait_for(lambda: mock_warn.call_count >= 1)
            mock_warn.assert_called_once_with(job, 0.4, 0.5)

        gate.set()
        await asyncio.wait_for(dispatch_task, timeout=HANG_GUARD_TIMEOUT_SECONDS)


@pytest.mark.parametrize(
    ("registration", "expected_timeout"),
    [
        pytest.param({"timeout": 300.0}, lambda _config: 300.0, id="per_job_timeout"),
        pytest.param({"timeout_disabled": True}, lambda _config: None, id="timeout_disabled"),
        pytest.param({}, lambda config: config.scheduler.job_timeout_seconds, id="global_default"),
    ],
)
async def test_stall_threshold_passed_to_guard(
    registration: dict[str, Any], expected_timeout: Callable[[Any], float | None]
) -> None:
    """Dispatch arms the watchdog at the threshold derived from the job's effective timeout."""

    class _ThresholdApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="threshold_job", mode="single", **registration)

        async def task(self) -> None:
            pass

    async with AppTestHarness(_ThresholdApp, config={"instance_name": "threshold_app"}) as harness:
        scheduler_service = scheduler_service_for(harness)
        job = await get_job_by_name(harness, "threshold_job")
        expected = execution_mode_module.stall_threshold(expected_timeout(scheduler_service.hassette.config))

        with unittest.mock.patch.object(
            scheduler_dispatch_module, "run_through_guard", wraps=scheduler_dispatch_module.run_through_guard
        ) as spy:
            dispatch_task = await freeze_and_dispatch(harness, job)
            await asyncio.wait_for(dispatch_task, timeout=HANG_GUARD_TIMEOUT_SECONDS)

        assert spy.call_args.kwargs["threshold"] == expected


async def test_queued_stall_threshold_uses_timeout_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """A config reload during a queue wait moves the watchdog along with the enforced timeout."""
    first_started = asyncio.Event()
    first_gate = asyncio.Event()
    starts = 0

    class _QueuedApp(App[_OverlapConfig]):
        async def on_initialize(self) -> None:
            await self.scheduler.run_every(self.task, seconds=10, name="queued_reload_job", mode="queued")

        async def task(self) -> None:
            nonlocal starts
            starts += 1
            if starts == 1:
                first_started.set()
                await first_gate.wait()
                return
            await asyncio.sleep(HANG_GUARD_TIMEOUT_SECONDS)  # outlasts the reloaded timeout, which ends it

    async with AppTestHarness(_QueuedApp, config={"instance_name": "queued_reload_app"}) as harness:
        scheduler_service = scheduler_service_for(harness)
        config = scheduler_service.hassette.config.scheduler
        monkeypatch.setattr(config, "job_timeout_seconds", 30.0)

        with patched_stall_watch(scheduler_service, 0.01) as mock_warn:
            job, first_dispatch, next_job = await start_overrun(harness, "queued_reload_job", first_started)
            second_dispatch = await freeze_and_dispatch(harness, next_job)
            await asyncio.sleep(0)  # let the second occurrence reach the queue

            # Before the reload, the queued invocation's threshold would be 24s, past any wait here.
            monkeypatch.setattr(config, "job_timeout_seconds", 0.25)
            first_gate.set()

            await wait_for(lambda: mock_warn.call_count >= 1)
            mock_warn.assert_called_once_with(job, execution_mode_module.stall_threshold(0.25), 0.25)

        await asyncio.wait_for(first_dispatch, timeout=HANG_GUARD_TIMEOUT_SECONDS)
        await asyncio.wait_for(second_dispatch, timeout=HANG_GUARD_TIMEOUT_SECONDS)


def test_warn_stalled_job_names_the_threshold_source(caplog: pytest.LogCaptureFixture) -> None:
    """The WARNING says why it fired at this threshold."""
    service = unittest.mock.MagicMock()
    job = unittest.mock.MagicMock()
    job.name = "slow_job"
    job.mode.value = "single"
    service.logger = logging.getLogger("hassette.test_stall")

    with caplog.at_level("WARNING", logger="hassette.test_stall"):
        scheduler_dispatch_module.SchedulerDispatchMixin.warn_stalled_job(service, job, 240.0, 300.0)

    assert "for over 240s (80% of its 300s timeout) and is still running" in caplog.text


async def test_parallel_mode_has_no_stall_watchdog() -> None:
    """Parallel mode invocations do not get a stall watchdog."""
    parallel_app, started, gate = make_gated_app("parallel_stalled_job", mode="parallel", timeout_disabled=True)

    async with AppTestHarness(parallel_app, config={"instance_name": "parallel_stalled_app"}) as harness:
        scheduler_service = scheduler_service_for(harness)
        job = await get_job_by_name(harness, "parallel_stalled_job")

        # Parallel runs inline (no stall watch installed). Spy on warn_stalled_job to assert
        # it is never called even when the invocation outlasts the patched threshold.
        with patched_stall_watch(scheduler_service, 0.05) as mock_warn:
            dispatch_task = await freeze_and_dispatch(harness, job)
            await asyncio.wait_for(started.wait(), timeout=HANG_GUARD_TIMEOUT_SECONDS)
            # dispatch_task is still pending because run_job awaits the callable inline
            assert not dispatch_task.done(), "Dispatch should be pending while job runs"
            await asyncio.sleep(0.2)  # outlast the patched threshold
            mock_warn.assert_not_called()

        gate.set()
        await asyncio.wait_for(dispatch_task, timeout=HANG_GUARD_TIMEOUT_SECONDS)
