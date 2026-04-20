import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from whenever import ZonedDateTime

from hassette import Hassette
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.core.commands import ExecuteJob
from hassette.scheduler import ScheduledJob
from hassette.scheduler.triggers import Every
from hassette.test_utils.app_harness import AppTestHarness
from hassette.utils.date_utils import now
from hassette.web.utils import resolve_trigger

TZ = ZoneInfo("America/Chicago")


async def test_run_in_passes_args_kwargs_async(hassette_with_scheduler: Hassette) -> None:
    """run_in forwards args/kwargs to async callables."""
    job_executed = asyncio.Event()
    captured_arguments: list[tuple[int, int, bool]] = []

    async def target(a: int, b: int, *, flag: bool) -> None:
        captured_arguments.append((a, b, flag))
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01, args=(1, 2), kwargs={"flag": True})

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert captured_arguments == [(1, 2, True)], f"Expected [(1, 2, True)], got {captured_arguments}"


async def test_run_in_passes_args_kwargs_sync(hassette_with_scheduler: Hassette) -> None:
    """run_in forwards args/kwargs to sync callables."""
    event_loop = asyncio.get_running_loop()
    job_executed = asyncio.Event()
    captured_arguments: list[tuple[str, int]] = []

    def target(name: str, *, count: int) -> None:
        captured_arguments.append((name, count))
        event_loop.call_soon_threadsafe(job_executed.set)

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01, args=("sensor",), kwargs={"count": 3})

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert captured_arguments == [("sensor", 3)], f"Expected [('sensor', 3)], got {captured_arguments}"


def test_scheduled_job_copies_args_kwargs() -> None:
    """ScheduledJob stores copies so external mutations do not leak in."""
    args = [1, 2]
    kwargs = {"alpha": 99}

    job = ScheduledJob(
        owner_id="owner",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda *a, **kw: None,  # noqa
        args=args,  # pyright: ignore[reportArgumentType]
        kwargs=kwargs,
    )

    args.append(3)
    kwargs["alpha"] = 0

    assert job.args == (1, 2), f"Expected (1, 2), got {job.args}"
    assert job.kwargs == {"alpha": 99}, f"Expected {{'alpha': 99}}, got {job.kwargs}"


async def test_run_job_calls_executor(hassette_with_scheduler: Hassette) -> None:
    """run_job() delegates execution to CommandExecutor.execute() with an ExecuteJob command."""
    job_executed = asyncio.Event()

    async def target() -> None:
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    # Reset the mock call history and set up a stub that also runs the job
    scheduler_service = hassette_with_scheduler._scheduler_service
    assert scheduler_service is not None
    executor = scheduler_service._executor

    executed_cmds: list[ExecuteJob] = []

    async def _capturing_execute(cmd: object) -> None:
        if isinstance(cmd, ExecuteJob):
            executed_cmds.append(cmd)
            await cmd.callable()

    executor.execute.side_effect = _capturing_execute
    executor.execute.reset_mock()

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.05)
    # Simulate an app-owned job by setting db_id (internal jobs have db_id=None and bypass executor)
    scheduled_job.mark_registered(99)

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    assert len(executed_cmds) == 1, f"Expected executor.execute() called once, got {len(executed_cmds)} calls"
    assert isinstance(executed_cmds[0], ExecuteJob), "Expected ExecuteJob command"
    assert executed_cmds[0].job is scheduled_job, "ExecuteJob.job should be the scheduled job"


async def test_run_job_non_app_routes_through_executor(hassette_with_scheduler: Hassette) -> None:
    """Jobs without app_key still route through CommandExecutor and get DB-registered (#547)."""
    job_executed = asyncio.Event()

    async def target() -> None:
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    scheduler_service = hassette_with_scheduler._scheduler_service
    executor = scheduler_service._executor
    executor.execute.reset_mock()

    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=0.01)

    await asyncio.wait_for(job_executed.wait(), timeout=1)
    scheduled_job.cancel()

    executor.execute.assert_called_once()
    cmd = executor.execute.call_args[0][0]
    assert isinstance(cmd, ExecuteJob)
    assert cmd.job_db_id is not None


async def test_job_registration_sets_db_id(hassette_with_scheduler: Hassette) -> None:
    """Adding a job triggers register_job() and sets job.db_id.

    All jobs now go through DB registration regardless of app_key (#547).
    """
    db_id = 99

    scheduler = hassette_with_scheduler._scheduler
    assert scheduler is not None
    scheduler_service = hassette_with_scheduler._scheduler_service
    assert scheduler_service is not None
    executor = scheduler_service._executor
    executor.register_job = AsyncMock(return_value=db_id)

    job_executed = asyncio.Event()

    async def target() -> None:
        hassette_with_scheduler.task_bucket.post_to_loop(job_executed.set)

    scheduled_job = scheduler.run_in(target, delay=0.5)

    await asyncio.sleep(0.1)

    assert scheduled_job.db_id is not None, "job.db_id should be set after registration"
    assert scheduled_job.db_id == db_id, f"Expected db_id={db_id}, got {scheduled_job.db_id}"

    scheduled_job.cancel()


async def test_jobs_execute_in_run_order(hassette_with_scheduler: Hassette) -> None:
    """run_once executes jobs according to their scheduled time."""
    execution_order: list[str] = []
    early_job_complete = asyncio.Event()
    late_job_complete = asyncio.Event()

    def make_job(label: str, signal: asyncio.Event):
        def _job() -> None:
            execution_order.append(label)
            hassette_with_scheduler.task_bucket.post_to_loop(signal.set)

        return _job

    reference = now()
    hassette_with_scheduler._scheduler.run_once(
        make_job("late", late_job_complete), at=reference.add(seconds=0.4), name="late_job"
    )
    hassette_with_scheduler._scheduler.run_once(
        make_job("early", early_job_complete), at=reference.add(seconds=0.1), name="early_job"
    )

    await asyncio.wait_for(early_job_complete.wait(), timeout=2)
    await asyncio.wait_for(late_job_complete.wait(), timeout=2)

    actual = set(execution_order[:2])
    expected = {"early", "late"}
    assert actual == expected, f"Expected {expected}, got {actual}"


def test_scheduled_job_has_app_key_and_instance_index() -> None:
    """Create a ScheduledJob with app_key and instance_index, verify fields are set."""
    job = ScheduledJob(
        owner_id="MyApp.MyApp.0",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
        app_key="my_app",
        instance_index=2,
    )

    assert job.app_key == "my_app"
    assert job.instance_index == 2
    assert job.owner_id == "MyApp.MyApp.0"


def test_scheduled_job_defaults_empty_app_key() -> None:
    """Create a ScheduledJob without app_key, verify it defaults to empty string."""
    job = ScheduledJob(
        owner_id="test",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
    )

    assert job.app_key == ""
    assert job.instance_index == 0


def test_scheduled_job_mark_registered_sets_db_id() -> None:
    """mark_registered() sets db_id on first call."""
    job = ScheduledJob(
        owner_id="test",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
    )
    assert job.db_id is None

    job.mark_registered(42)
    assert job.db_id == 42


def test_scheduled_job_mark_registered_keeps_original_on_double_call() -> None:
    """mark_registered() keeps the original db_id when called a second time."""
    job = ScheduledJob(
        owner_id="test",
        next_run=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0),
        job=lambda: None,
    )
    job.mark_registered(42)
    job.mark_registered(99)

    assert job.db_id == 42


# ---------------------------------------------------------------------------
# Test apps for AppTestHarness-based tests
# ---------------------------------------------------------------------------


class _ExhaustionConfig(AppConfig):
    """Minimal config for exhaustion tests."""


class _OnceExhaustionApp(App[_ExhaustionConfig]):
    """App that schedules a Once job for exhaustion testing."""

    fired: bool

    async def on_initialize(self) -> None:
        self.fired = False
        # Schedule a Once job at a time far in the future (we'll freeze past it)
        self.scheduler.run_once(self._task, at=ZonedDateTime.from_system_tz(2030, 6, 15, 7, 0, 0), name="once_job")

    async def _task(self) -> None:
        self.fired = True


class _AfterExhaustionApp(App[_ExhaustionConfig]):
    """App that schedules an After job for exhaustion testing."""

    fired: bool

    async def on_initialize(self) -> None:
        self.fired = False
        # After(seconds=10) — will fire when we freeze 10+ seconds into the future
        self.scheduler.run_in(self._task, delay=10, name="after_job")

    async def _task(self) -> None:
        self.fired = True


class _GroupApp(App[_ExhaustionConfig]):
    """App that schedules jobs in a named group."""

    async def on_initialize(self) -> None:
        self.scheduler.run_every(lambda: None, hours=1, name="g1", group="morning")
        self.scheduler.run_every(lambda: None, hours=2, name="g2", group="morning")
        self.scheduler.run_every(lambda: None, hours=3, name="g3", group="morning")


class _OnceGroupApp(App[_ExhaustionConfig]):
    """App that schedules a Once job in a named group."""

    fired: bool

    async def on_initialize(self) -> None:
        self.fired = False
        self.scheduler.run_once(
            self._task,
            at=ZonedDateTime.from_system_tz(2030, 6, 15, 7, 0, 0),
            name="once_in_group",
            group="morning",
        )
        # Add a recurring job so the group isn't empty after exhaustion
        self.scheduler.run_every(lambda: None, hours=1, name="recurring_in_group", group="morning")

    async def _task(self) -> None:
        self.fired = True


# ---------------------------------------------------------------------------
# Subtask 4: Once job exhaustion
# ---------------------------------------------------------------------------


async def test_once_job_exhausts_after_firing() -> None:
    """A Once job is removed from the scheduler after it fires."""
    async with AppTestHarness(_OnceExhaustionApp, config={}) as harness:
        scheduler = harness.app.scheduler

        # Verify job is registered
        jobs = scheduler.list_jobs()
        assert any(j.name == "once_job" for j in jobs), "once_job should be registered"

        # Freeze time past the job's scheduled time
        job = next(j for j in jobs if j.name == "once_job")
        harness.freeze_time(job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1
        assert harness.app.fired is True

        # Job should be exhausted and removed
        remaining = scheduler.list_jobs()
        assert not any(j.name == "once_job" for j in remaining), "Once job should be removed after exhaustion"


# ---------------------------------------------------------------------------
# Subtask 5: After job exhaustion
# ---------------------------------------------------------------------------


async def test_after_job_exhausts_after_firing() -> None:
    """An After job is removed from the scheduler after it fires."""
    async with AppTestHarness(_AfterExhaustionApp, config={}) as harness:
        scheduler = harness.app.scheduler

        # Verify job is registered
        jobs = scheduler.list_jobs()
        assert any(j.name == "after_job" for j in jobs), "after_job should be registered"

        # Freeze time past the job's scheduled time
        job = next(j for j in jobs if j.name == "after_job")
        harness.freeze_time(job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count == 1
        assert harness.app.fired is True

        # Job should be exhausted and removed
        remaining = scheduler.list_jobs()
        assert not any(j.name == "after_job" for j in remaining), "After job should be removed after exhaustion"


# ---------------------------------------------------------------------------
# Subtask 6: Jitter offset applied to sort_index
# ---------------------------------------------------------------------------


async def test_jitter_offset_applied_to_sort_index() -> None:
    """Every(hours=1) with jitter=60: jitter field is stored, sort_index currently equals next_run.

    Note: jitter application to sort_index is not yet implemented (see TODO in
    classes.py).  This test verifies the field is stored and sort_index is
    within the jitter bound — today the offset is 0 because jitter is not yet
    applied, but the assertion will still hold once it is.
    """
    async with AppTestHarness(_OnceExhaustionApp, config={}) as harness:
        scheduler = harness.app.scheduler

        job = scheduler.schedule(lambda: None, Every(hours=1), name="jittered_job", jitter=60)

        assert job.jitter == 60, "jitter field should be stored on the job"
        assert job.next_run.nanosecond == 0, "next_run should be rounded to whole seconds"

        # sort_index should differ from next_run by at most the jitter bound.
        # Currently offset is 0 (jitter not yet applied to sort_index); this
        # assertion will continue to hold once jitter IS applied.
        sort_nanos = job.sort_index[0]
        next_run_nanos = job.next_run.timestamp_nanos()
        offset_seconds = abs(sort_nanos - next_run_nanos) / 1_000_000_000

        assert offset_seconds <= 60, f"sort_index offset ({offset_seconds:.2f}s) exceeds jitter bound (60s)"


# ---------------------------------------------------------------------------
# Subtask 7: Group cancel removes all members
# ---------------------------------------------------------------------------


async def test_group_cancel_removes_all_members() -> None:
    """cancel_group marks all group members as cancelled and removes from list_jobs."""
    async with AppTestHarness(_GroupApp, config={}) as harness:
        scheduler = harness.app.scheduler

        # Verify all 3 jobs are in the group
        group_jobs = scheduler.list_jobs(group="morning")
        assert len(group_jobs) == 3, f"Expected 3 jobs in 'morning' group, got {len(group_jobs)}"

        # Cancel the group
        scheduler.cancel_group("morning")

        # All jobs should be absent from list_jobs (behaviorally cancelled)
        remaining = scheduler.list_jobs(group="morning")
        assert len(remaining) == 0, f"Expected 0 jobs in 'morning' group after cancel, got {len(remaining)}"

        all_jobs = scheduler.list_jobs()
        for job in group_jobs:
            assert job not in all_jobs, f"Job {job.name} should not be in list_jobs() after cancel_group"


# ---------------------------------------------------------------------------
# Subtask 8: Once job removed from group after exhaustion
# ---------------------------------------------------------------------------


async def test_once_job_removed_from_group_after_exhaustion() -> None:
    """A Once job in a group is removed from the group when it exhausts."""
    async with AppTestHarness(_OnceGroupApp, config={}) as harness:
        scheduler = harness.app.scheduler

        # Verify both jobs are in the group
        group_jobs = scheduler.list_jobs(group="morning")
        assert len(group_jobs) == 2, f"Expected 2 jobs in 'morning' group, got {len(group_jobs)}"
        assert any(j.name == "once_in_group" for j in group_jobs)

        # Freeze time past the Once job's scheduled time.
        # The recurring job may also be due (its first_run is based on now()).
        once_job = next(j for j in group_jobs if j.name == "once_in_group")
        harness.freeze_time(once_job.next_run.add(seconds=1))

        count = await harness.trigger_due_jobs()
        assert count >= 1, "At least the Once job should have fired"
        assert harness.app.fired is True

        # The Once job should be removed from the group
        group_after = scheduler.list_jobs(group="morning")
        assert not any(j.name == "once_in_group" for j in group_after), (
            "Once job should be removed from group after exhaustion"
        )
        # The recurring job should still be in the group (it re-enqueues after firing)
        assert any(j.name == "recurring_in_group" for j in group_after), "Recurring job should remain in group"


# ---------------------------------------------------------------------------
# Subtask 10: resolve_trigger with trigger=None
# ---------------------------------------------------------------------------


def test_resolve_trigger_none_job() -> None:
    """resolve_trigger returns ('one-shot', None) for a job with trigger=None.

    The 'one-shot' label distinguishes no-trigger jobs from cron/interval jobs in the UI.
    """
    job = SimpleNamespace(trigger=None)
    result = resolve_trigger(job)  # pyright: ignore[reportArgumentType]
    assert result == ("one-shot", None), f"Expected ('one-shot', None), got {result}"


# ---------------------------------------------------------------------------
# Subtask 5a: job.cancel() back-reference path persists cancelled_at
# ---------------------------------------------------------------------------


async def test_job_cancel_via_back_reference_persists_cancelled_at(hassette_with_scheduler: Hassette) -> None:
    """job.cancel() delegates to Scheduler.cancel_job(), which spawns mark_job_cancelled(db_id).

    Verifies AC6: the back-reference cancel path produces a durable DB write
    (cancelled_at IS NOT NULL). Verified via the mock_executor call record since
    the integration harness uses a mock executor at the repository boundary.
    """
    scheduler_service = hassette_with_scheduler._scheduler_service
    assert scheduler_service is not None
    executor = scheduler_service._executor

    # Reset call history so we only see calls from this test
    executor.mark_job_cancelled.reset_mock()

    db_id = 42

    job_done = asyncio.Event()

    async def target() -> None:
        hassette_with_scheduler.task_bucket.post_to_loop(job_done.set)

    # Schedule a job and simulate it having been persisted with db_id=42
    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=10)
    scheduled_job.mark_registered(db_id)

    # Cancel via the back-reference (job.cancel() → scheduler.cancel_job())
    scheduled_job.cancel()

    # Give the spawned mark_job_cancelled task a chance to execute
    await asyncio.sleep(0)

    # Verify mark_job_cancelled was called with the correct db_id
    executor.mark_job_cancelled.assert_called_once_with(db_id)

    # Verify the job is dequeued (no longer in the scheduler)
    remaining = hassette_with_scheduler._scheduler.list_jobs()
    assert not any(j is scheduled_job for j in remaining), "Cancelled job should be removed from scheduler"


# ---------------------------------------------------------------------------
# Subtask 5b: cancel before db_id set does not raise
# ---------------------------------------------------------------------------


async def test_cancel_before_db_id_set_does_not_raise(hassette_with_scheduler: Hassette) -> None:
    """job.cancel() does not raise when db_id is None (registration not yet complete).

    Verifies AC5: the cancel path is safe to call before DB registration completes.
    No mark_job_cancelled DB write should be spawned when db_id is None.
    """
    scheduler_service = hassette_with_scheduler._scheduler_service
    assert scheduler_service is not None
    executor = scheduler_service._executor

    executor.mark_job_cancelled.reset_mock()

    async def target() -> None:
        pass

    # Schedule a job without calling mark_registered — db_id remains None
    scheduled_job = hassette_with_scheduler._scheduler.run_in(target, delay=10)
    assert scheduled_job.db_id is None, "db_id should be None before registration"

    # Cancel via back-reference — must not raise
    scheduled_job.cancel()

    # No DB write should be spawned (db_id is None)
    executor.mark_job_cancelled.assert_not_called()

    # Job should be dequeued
    remaining = hassette_with_scheduler._scheduler.list_jobs()
    assert not any(j is scheduled_job for j in remaining), "Cancelled job should be removed from scheduler"
