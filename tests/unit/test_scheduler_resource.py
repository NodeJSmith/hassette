"""Unit tests for Scheduler resource: new schedule() entry point, job groups, convenience wrappers."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from whenever import ZonedDateTime

from hassette.resources.base import Resource
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import After, Cron, Daily, Every, Once
from hassette.utils.date_utils import now


def make_mock_parent(*, app_key: str = "test_app", index: int = 0, source_tier: str = "app") -> Mock:
    """Create a mock parent Resource with telemetry identity fields."""
    parent = Mock()
    parent.app_key = app_key
    parent.index = index
    parent.source_tier = source_tier
    parent.class_name = "TestParent"
    return parent


def make_scheduler(removal_callback_supported: bool = True) -> Scheduler:
    """Create a minimal Scheduler instance with mocked internals.

    Uses a unique per-call subclass so that property overrides for owner_id and
    parent do NOT mutate the shared Scheduler class — which would break parallel
    test workers that create real Scheduler instances concurrently.
    """
    # Fresh subclass per call: property assignments stay on _TestScheduler, not Scheduler.
    mock_parent = make_mock_parent()
    _TestScheduler = type("_TestScheduler", (Scheduler,), {})  # noqa: N806
    _TestScheduler.owner_id = property(lambda _self: "test_owner")  # pyright: ignore[reportAttributeAccessIssue]
    _TestScheduler.parent = property(lambda _self: mock_parent)  # pyright: ignore[reportAttributeAccessIssue]

    scheduler = _TestScheduler.__new__(_TestScheduler)
    mock_service = Mock()
    if removal_callback_supported:
        mock_service.register_removal_callback = Mock()
    else:
        del mock_service.register_removal_callback
    # dequeue_job must set job._dequeued = True (mirrors real SchedulerService behavior)
    mock_service.dequeue_job = Mock(side_effect=lambda job: setattr(job, "_dequeued", True) or True)

    # add_job is awaited inline — must be an AsyncMock; sets db_id=1 on the job
    async def _add_job(job):
        job.mark_registered(1)

    mock_service.add_job = AsyncMock(side_effect=_add_job)
    scheduler.scheduler_service = mock_service
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    return scheduler


def make_job(
    name: str = "",
    *,
    job: Callable[..., None] | None = None,
    group: str | None = None,
) -> ScheduledJob:
    """Create a minimal ScheduledJob."""
    return ScheduledJob(
        owner_id="test_owner",
        next_run=now(),
        job=job or (lambda: None),
        name=name,
        group=group,
    )


async def noop() -> None:
    pass


class TestScheduleEntryPoint:
    async def test_schedule_creates_job_with_trigger(self) -> None:
        """schedule(cb, Every(hours=1)) returns a ScheduledJob with the correct trigger."""
        scheduler = make_scheduler()
        trigger = Every(hours=1)
        job = await scheduler.schedule(noop, trigger)
        assert isinstance(job, ScheduledJob)
        assert job.trigger is trigger

    async def test_schedule_fires_first_run_time_from_trigger(self) -> None:
        """job.next_run equals trigger.first_run_time(now) — within 2 seconds."""
        scheduler = make_scheduler()
        trigger = Every(hours=1)
        before = now()
        job = await scheduler.schedule(noop, trigger)
        after = now()
        expected_min = trigger.first_run_time(before)
        expected_max = trigger.first_run_time(after)
        assert expected_min <= job.next_run <= expected_max

    async def test_schedule_group_tracked(self) -> None:
        """schedule with group= adds job to _jobs_by_group."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, Daily(at="07:00"), group="morning")
        assert "morning" in scheduler._jobs_by_group
        assert job in scheduler._jobs_by_group["morning"]

    async def test_schedule_no_group_not_in_jobs_by_group(self) -> None:
        """schedule without group= does not add to _jobs_by_group."""
        scheduler = make_scheduler()
        await scheduler.schedule(noop, Every(seconds=30))
        assert scheduler._jobs_by_group == {}


class TestCancelGroup:
    async def test_cancel_group_cancels_all_members(self) -> None:
        """All jobs in a group are dequeued after cancel_group()."""
        scheduler = make_scheduler()
        job1 = await scheduler.schedule(noop, Every(hours=1), name="job1", group="morning")
        job2 = await scheduler.schedule(noop, Every(hours=2), name="job2", group="morning")
        scheduler.cancel_group("morning")
        # Verify dequeue_job was called for each member
        calls = scheduler.scheduler_service.dequeue_job.call_args_list
        dequeued_jobs = {c.args[0] for c in calls}
        assert job1 in dequeued_jobs
        assert job2 in dequeued_jobs

    def test_cancel_group_nonexistent_noop(self) -> None:
        """cancel_group('ghost') does not raise."""
        scheduler = make_scheduler()
        scheduler.cancel_group("ghost")  # should not raise

    async def test_cancel_group_clears_group_key(self) -> None:
        """After cancellation, the group key is removed from _jobs_by_group via _on_job_removed callback."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, Every(hours=1), group="morning")
        assert "morning" in scheduler._jobs_by_group

        # Simulate callback-based removal (as fired by scheduler_service.dequeue_job)
        scheduler._on_job_removed(job)
        assert "morning" not in scheduler._jobs_by_group

    async def test_cancel_group_calls_dequeue_job_on_service(self) -> None:
        """cancel_group calls scheduler_service.dequeue_job for each member."""
        scheduler = make_scheduler()
        await scheduler.schedule(noop, Every(hours=1), name="job1", group="morning")
        await scheduler.schedule(noop, Every(hours=2), name="job2", group="morning")
        scheduler.cancel_group("morning")
        # dequeue_job called twice
        assert scheduler.scheduler_service.dequeue_job.call_count == 2

    async def test_cancel_group_persists_cancelled_at_for_registered_jobs(self) -> None:
        """cancel_group spawns mark_job_cancelled for each job with a db_id set.

        With async registration, jobs always have db_id set after schedule() returns,
        so mark_job_cancelled is always spawned for jobs in the group.
        """
        scheduler = make_scheduler()
        # Add a task_bucket mock. Close any coroutine passed to spawn to avoid
        # "coroutine never awaited" warnings when mark_job_cancelled returns a real coro.
        spawned_coroutines: list = []

        def _spawn_and_close(coro, *, name=""):
            spawned_coroutines.append((coro, name))
            if asyncio.iscoroutine(coro):
                coro.close()  # clean up to avoid "never awaited" warnings

        scheduler.scheduler_service.task_bucket = MagicMock()
        scheduler.scheduler_service.task_bucket.spawn.side_effect = _spawn_and_close

        # With async registration, db_id is set by add_job (mock sets it to 1)
        await scheduler.schedule(noop, Every(hours=1), name="job1", group="morning")
        await scheduler.schedule(noop, Every(hours=2), name="job2", group="morning")

        scheduler.cancel_group("morning")

        # task_bucket.spawn must have been called once per job with a db_id
        assert scheduler.scheduler_service.task_bucket.spawn.call_count == 2
        # Verify the spawn calls used the correct task name
        for _coro, name in spawned_coroutines:
            assert name == "scheduler:mark_job_cancelled"

    async def test_cancel_group_skips_mark_job_cancelled_when_db_id_none(self) -> None:
        """cancel_group does not spawn mark_job_cancelled for jobs without db_id.

        This is a defensive test: with async registration, db_id is normally always set.
        We override add_job to NOT set the db_id to test the guard still works.
        """
        scheduler = make_scheduler()
        scheduler.scheduler_service.task_bucket = MagicMock()

        # Override add_job to skip mark_registered so db_id stays None
        scheduler.scheduler_service.add_job = AsyncMock()

        await scheduler.schedule(noop, Every(hours=1), name="job1", group="morning")
        await scheduler.schedule(noop, Every(hours=2), name="job2", group="morning")

        scheduler.cancel_group("morning")

        # task_bucket.spawn must NOT be called (no db_ids set)
        scheduler.scheduler_service.task_bucket.spawn.assert_not_called()


class TestListJobs:
    async def test_list_jobs_no_filter(self) -> None:
        """list_jobs() returns all 3 jobs across 2 groups."""
        scheduler = make_scheduler()
        job1 = await scheduler.schedule(noop, Every(hours=1), name="a", group="g1")
        job2 = await scheduler.schedule(noop, Every(hours=2), name="b", group="g1")
        job3 = await scheduler.schedule(noop, Every(hours=3), name="c", group="g2")
        result = scheduler.list_jobs()
        assert sorted(result, key=lambda j: j.name) == sorted([job1, job2, job3], key=lambda j: j.name)

    async def test_list_jobs_group_filter(self) -> None:
        """list_jobs(group=) returns only group-matched jobs."""
        scheduler = make_scheduler()
        job1 = await scheduler.schedule(noop, Every(hours=1), name="a", group="g1")
        await scheduler.schedule(noop, Every(hours=2), name="b", group="g2")
        result = scheduler.list_jobs(group="g1")
        assert result == [job1]

    async def test_list_jobs_empty_group_returns_empty(self) -> None:
        """list_jobs(group='ghost') returns empty list for unknown group."""
        scheduler = make_scheduler()
        await scheduler.schedule(noop, Every(hours=1), name="a", group="g1")
        assert scheduler.list_jobs(group="ghost") == []


class TestJobsByGroupMaintenance:
    async def test_dequeue_job_removes_from_group(self) -> None:
        """dequeue_job() fires callback which removes the job from _jobs_by_group."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, Every(hours=1), group="morning")
        assert job in scheduler._jobs_by_group["morning"]
        # Simulate callback-based removal (as if scheduler_service called _on_job_removed)
        scheduler._on_job_removed(job)
        assert "morning" not in scheduler._jobs_by_group

    async def test_dequeue_job_leaves_other_group_members(self) -> None:
        """Callback removal for one job doesn't remove sibling from _jobs_by_group."""
        scheduler = make_scheduler()
        job1 = await scheduler.schedule(noop, Every(hours=1), name="a", group="g")
        job2 = await scheduler.schedule(noop, Every(hours=2), name="b", group="g")
        scheduler._on_job_removed(job1)
        assert "g" in scheduler._jobs_by_group
        assert job2 in scheduler._jobs_by_group["g"]

    async def test_remove_all_jobs_clears_groups(self) -> None:
        """_remove_all_jobs() empties _jobs_by_group."""
        scheduler = make_scheduler()
        await scheduler.schedule(noop, Every(hours=1), name="a", group="g1")
        await scheduler.schedule(noop, Every(hours=2), name="b", group="g2")
        scheduler._remove_all_jobs()
        assert scheduler._jobs_by_group == {}

    async def test_removal_callback_called_on_exhaustion(self) -> None:
        """Simulated SchedulerService exhaustion notification triggers group removal."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, After(seconds=30), group="once_group")
        assert job in scheduler._jobs_by_group["once_group"]

        # Directly invoke the callback as SchedulerService would after a one-shot job fires
        scheduler._on_job_removed(job)

        assert "once_group" not in scheduler._jobs_by_group
        assert job.name not in scheduler._jobs_by_name


class TestConvenienceWrappers:
    async def test_run_daily_delegates_to_daily_trigger(self) -> None:
        """run_daily(cb, at='07:00') schedules with Daily(at='07:00')."""
        scheduler = make_scheduler()
        job = await scheduler.run_daily(noop, at="07:00")
        assert isinstance(job.trigger, Daily)
        assert job.trigger.trigger_id() == "cron:0 7 * * *"

    async def test_run_in_delegates_to_after_trigger(self) -> None:
        """run_in(cb, 30) schedules with After(seconds=30)."""
        scheduler = make_scheduler()
        job = await scheduler.run_in(noop, 30)
        assert isinstance(job.trigger, After)
        assert job.trigger._delay.in_seconds() == 30

    async def test_run_in_accepts_float_seconds(self) -> None:
        """run_in accepts a float number of seconds."""
        scheduler = make_scheduler()
        job = await scheduler.run_in(noop, 60.0)
        assert isinstance(job.trigger, After)

    async def test_run_cron_string_form_accepted(self) -> None:
        """run_cron(cb, '0 9 * * 1-5') works with a cron expression string."""
        scheduler = make_scheduler()
        job = await scheduler.run_cron(noop, "0 9 * * 1-5")
        assert isinstance(job.trigger, Cron)

    async def test_run_every_keywords_accepted(self) -> None:
        """run_every(cb, hours=1) works."""
        scheduler = make_scheduler()
        job = await scheduler.run_every(noop, hours=1)
        assert isinstance(job.trigger, Every)

    async def test_run_every_minutes_keywords_accepted(self) -> None:
        """run_every(cb, minutes=5) works."""
        scheduler = make_scheduler()
        job = await scheduler.run_every(noop, minutes=5)
        assert isinstance(job.trigger, Every)

    async def test_run_every_seconds_keywords_accepted(self) -> None:
        """run_every(cb, seconds=30) works."""
        scheduler = make_scheduler()
        job = await scheduler.run_every(noop, seconds=30)
        assert isinstance(job.trigger, Every)

    async def test_run_minutely_delegates_to_every_trigger(self) -> None:
        """run_minutely(cb, minutes=5) schedules with Every(minutes=5)."""
        scheduler = make_scheduler()
        job = await scheduler.run_minutely(noop, minutes=5)
        assert isinstance(job.trigger, Every)
        assert job.trigger.interval_seconds == 300.0

    async def test_run_hourly_delegates_to_every_trigger(self) -> None:
        """run_hourly(cb, hours=2) schedules with Every(hours=2)."""
        scheduler = make_scheduler()
        job = await scheduler.run_hourly(noop, hours=2)
        assert isinstance(job.trigger, Every)
        assert job.trigger.interval_seconds == 7200.0

    async def test_run_once_string_form_accepted(self) -> None:
        """run_once(cb, at='23:59') works with str."""
        scheduler = make_scheduler()
        job = await scheduler.run_once(noop, at="23:59")
        assert isinstance(job.trigger, Once)

    async def test_run_once_zoned_datetime_accepted(self) -> None:
        """run_once(cb, at=ZonedDateTime) works with ZonedDateTime."""
        scheduler = make_scheduler()
        future = now().add(hours=1)
        job = await scheduler.run_once(noop, at=future)
        assert isinstance(job.trigger, Once)

    async def test_run_in_jitter_forwarded(self) -> None:
        """run_in with jitter=60 creates a job with jitter=60."""
        scheduler = make_scheduler()
        job = await scheduler.run_in(noop, 30, jitter=60)
        assert job.jitter == 60

    async def test_run_once_jitter_forwarded(self) -> None:
        """run_once with jitter=30 creates a job with jitter=30."""
        scheduler = make_scheduler()
        job = await scheduler.run_once(noop, at="23:59", jitter=30)
        assert job.jitter == 30

    async def test_run_every_jitter_forwarded(self) -> None:
        """run_every with jitter=10 creates a job with jitter=10."""
        scheduler = make_scheduler()
        job = await scheduler.run_every(noop, seconds=30, jitter=10)
        assert job.jitter == 10

    async def test_run_minutely_jitter_forwarded(self) -> None:
        """run_minutely with jitter=5 creates a job with jitter=5."""
        scheduler = make_scheduler()
        job = await scheduler.run_minutely(noop, jitter=5)
        assert job.jitter == 5

    async def test_run_hourly_jitter_forwarded(self) -> None:
        """run_hourly with jitter=120 creates a job with jitter=120."""
        scheduler = make_scheduler()
        job = await scheduler.run_hourly(noop, jitter=120)
        assert job.jitter == 120

    async def test_run_daily_jitter_forwarded(self) -> None:
        """run_daily with jitter=60 creates a job with jitter=60."""
        scheduler = make_scheduler()
        job = await scheduler.run_daily(noop, at="07:00", jitter=60)
        assert job.jitter == 60

    async def test_run_cron_jitter_forwarded(self) -> None:
        """run_cron with jitter=15 creates a job with jitter=15."""
        scheduler = make_scheduler()
        job = await scheduler.run_cron(noop, "0 9 * * 1-5", jitter=15)
        assert job.jitter == 15

    async def test_run_once_if_past_error_raises(self) -> None:
        """run_once(..., if_past='error') raises ValueError when target time is in the past."""
        # Fix "now" to a known future time so "00:00" is in the past
        fake_now = ZonedDateTime(2025, 8, 18, 8, 0, 0, tz="America/Chicago")
        with patch("hassette.utils.date_utils.now", return_value=fake_now):
            scheduler = make_scheduler()
            with pytest.raises(ValueError, match="constructed after the target time"):
                await scheduler.run_once(noop, at="00:00", if_past="error")

    async def test_run_daily_group_forwarded(self) -> None:
        """run_daily with group= adds job to _jobs_by_group."""
        scheduler = make_scheduler()
        job = await scheduler.run_daily(noop, at="06:00", group="morning")
        assert job in scheduler._jobs_by_group["morning"]

    async def test_run_in_group_forwarded(self) -> None:
        """run_in with group= adds job to _jobs_by_group."""
        scheduler = make_scheduler()
        job = await scheduler.run_in(noop, 30, group="once")
        assert job in scheduler._jobs_by_group["once"]


class TestScheduleTypeError:
    async def test_schedule_raises_typeerror_for_non_protocol_trigger(self) -> None:
        """schedule() with a non-TriggerProtocol trigger raises TypeError immediately."""

        class NotATrigger:
            pass

        scheduler = make_scheduler()
        with pytest.raises(TypeError, match="trigger must implement TriggerProtocol"):
            await scheduler.schedule(noop, NotATrigger())


class TestCallbackRegistration:
    """Verify register_removal_callback is called during Scheduler.__init__."""

    def test_register_removal_callback_called_during_init(self) -> None:
        """Scheduler.__init__ directly registers the removal callback on the service.

        Exercises the real __init__ by stubbing Resource.__init__ so the Scheduler
        construction runs its post-super() body (which includes the direct
        register_removal_callback call) without requiring a full Hassette harness.
        Regression guard for the removal of the legacy getattr/iscoroutinefunction guard.
        """
        mock_hassette = Mock()
        mock_hassette._scheduler_service = Mock()
        mock_hassette._scheduler_service.register_removal_callback = Mock()

        # Build a subclass that overrides owner_id/parent to avoid touching Resource state.
        mock_parent = make_mock_parent()
        _TestScheduler = type("_TestScheduler", (Scheduler,), {})  # noqa: N806
        _TestScheduler.owner_id = property(  # pyright: ignore[reportAttributeAccessIssue]
            lambda _self: "test_owner"
        )
        _TestScheduler.parent = property(  # pyright: ignore[reportAttributeAccessIssue]
            lambda _self: mock_parent
        )

        # Stub Resource.__init__ so super().__init__() is a no-op; the rest of
        # Scheduler.__init__ still runs and must call register_removal_callback directly.
        # add_child is also stubbed — with Resource.__init__ skipped there is no
        # `children` list for the sync-facade wiring to append to, and this test only
        # cares about the removal-callback registration.
        with (
            patch.object(Resource, "__init__", return_value=None),
            patch.object(Resource, "add_child", return_value=Mock()),
        ):

            def _hassette(_self: object) -> object:
                return mock_hassette

            _TestScheduler.hassette = property(_hassette)  # pyright: ignore[reportAttributeAccessIssue]
            _TestScheduler(mock_hassette)

        mock_hassette._scheduler_service.register_removal_callback.assert_called_once()
        call_args = mock_hassette._scheduler_service.register_removal_callback.call_args
        assert call_args.args[0] == "test_owner"
        assert callable(call_args.args[1])


class TestAddJobBackReference:
    async def test_add_job_sets_scheduler_back_reference(self) -> None:
        """add_job() sets job._scheduler = self before delegating to scheduler_service."""
        scheduler = make_scheduler()
        job = make_job()

        await scheduler.add_job(job)

        assert job._scheduler is scheduler, (
            f"Expected job._scheduler to be the Scheduler instance, got {job._scheduler!r}"
        )


class TestCancelJob:
    async def test_cancel_job_idempotent(self) -> None:
        """Second cancel_job call on the same job is a silent no-op."""
        scheduler = make_scheduler()
        scheduler.scheduler_service.task_bucket = MagicMock()
        scheduler.scheduler_service.task_bucket.spawn = MagicMock(side_effect=lambda coro, **_: coro.close() or None)

        job = await scheduler.schedule(noop, Every(hours=1), name="job1")
        # db_id already set by mock add_job — no need to call mark_registered

        # First cancel
        scheduler.cancel_job(job)
        first_spawn_count = scheduler.scheduler_service.task_bucket.spawn.call_count
        first_dequeue_count = scheduler.scheduler_service.dequeue_job.call_count

        # Second cancel — must be a no-op
        scheduler.cancel_job(job)
        assert scheduler.scheduler_service.task_bucket.spawn.call_count == first_spawn_count, (
            "No additional DB write on second cancel"
        )
        assert scheduler.scheduler_service.dequeue_job.call_count == first_dequeue_count, (
            "No additional dequeue on second cancel"
        )

    async def test_cancel_job_rejects_wrong_scheduler(self) -> None:
        """cancel_job raises ValueError when job belongs to a different scheduler."""
        scheduler_a = make_scheduler()
        scheduler_b = make_scheduler()
        # Provide minimal unique_id so __repr__ doesn't crash when constructing the error message
        scheduler_a.unique_id = "sched_a"
        scheduler_b.unique_id = "sched_b"

        job = await scheduler_a.schedule(noop, Every(hours=1), name="job1")

        with pytest.raises(ValueError, match="different scheduler"):
            scheduler_b.cancel_job(job)

    async def test_cancel_group_delegates_to_cancel_job(self) -> None:
        """cancel_group calls cancel_job once per member."""
        scheduler = make_scheduler()
        await scheduler.schedule(noop, Every(hours=1), name="job1", group="morning")
        await scheduler.schedule(noop, Every(hours=2), name="job2", group="morning")

        with patch.object(scheduler, "cancel_job", wraps=scheduler.cancel_job) as mock_cancel:
            scheduler.cancel_group("morning")

        assert mock_cancel.call_count == 2

    async def test_cancel_job_calls_dequeue_job(self) -> None:
        """cancel_job delegates to scheduler_service.dequeue_job."""
        scheduler = make_scheduler()

        job = await scheduler.schedule(noop, Every(hours=1), name="job1")
        scheduler.cancel_job(job)
        scheduler.scheduler_service.dequeue_job.assert_called_once_with(job)

    async def test_cancel_job_dequeued_set_by_dequeue_job(self) -> None:
        """job._dequeued is False when dequeue_job runs (set True afterward by SchedulerService)."""
        scheduler = make_scheduler()
        scheduler.scheduler_service.task_bucket = MagicMock()

        dequeued_state_during_dequeue: list[bool] = []

        original_dequeue = scheduler.scheduler_service.dequeue_job

        def capturing_dequeue(job):
            dequeued_state_during_dequeue.append(job._dequeued)
            return original_dequeue(job)

        scheduler.scheduler_service.dequeue_job = capturing_dequeue

        job = await scheduler.schedule(noop, Every(hours=1), name="job1")
        scheduler.cancel_job(job)

        assert dequeued_state_during_dequeue == [False], (
            "_dequeued must be False when dequeue_job runs; set True afterward"
        )


class TestJobCancelDelegation:
    async def test_job_cancel_delegates_to_scheduler(self) -> None:
        """job.cancel() calls scheduler.cancel_job(self)."""
        scheduler = make_scheduler()
        scheduler.scheduler_service.task_bucket = MagicMock()

        job = await scheduler.schedule(noop, Every(hours=1), name="job1")

        with patch.object(scheduler, "cancel_job", wraps=scheduler.cancel_job) as mock_cancel:
            job.cancel()

        mock_cancel.assert_called_once_with(job)

    def test_job_cancel_raises_without_scheduler(self) -> None:
        """job.cancel() raises RuntimeError on a bare job with no _scheduler set."""
        job = make_job("bare_job")
        assert job._scheduler is None

        with pytest.raises(RuntimeError, match="not registered with a Scheduler"):
            job.cancel()


class TestIdentityPassThrough:
    async def test_job_inherits_parent_app_key(self) -> None:
        """schedule() sets job.app_key from parent.app_key, not Scheduler's own."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, Every(hours=1))
        assert job.app_key == "test_app"

    async def test_job_inherits_parent_source_tier(self) -> None:
        """schedule() sets job.source_tier from parent.source_tier."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, Every(hours=1))
        assert job.source_tier == "app"

    async def test_job_inherits_parent_instance_index(self) -> None:
        """schedule() sets job.instance_index from parent.index."""
        scheduler = make_scheduler()
        scheduler.parent.index = 5
        job = await scheduler.schedule(noop, Every(hours=1))
        assert job.instance_index == 5

    async def test_framework_scheduler_inherits_framework_tier(self) -> None:
        """A Scheduler with a framework parent produces jobs with source_tier='framework'."""
        scheduler = make_scheduler()
        scheduler.parent.source_tier = "framework"
        scheduler.parent.app_key = "__hassette__.TestComponent"
        scheduler.parent.class_name = "TestComponent"
        job = await scheduler.schedule(noop, Every(hours=1))
        assert job.source_tier == "framework"
        assert job.app_key == "__hassette__.TestComponent"

    async def test_source_tier_assertion_rejects_invalid_value(self) -> None:
        """schedule() raises AssertionError for invalid source_tier values."""
        scheduler = make_scheduler()
        scheduler.parent.source_tier = "invalid"
        with pytest.raises(AssertionError, match="Invalid source_tier"):
            await scheduler.schedule(noop, Every(hours=1))

    def test_scheduler_requires_parent(self) -> None:
        """Scheduler.__init__ raises AssertionError when parent is None."""
        mock_hassette = Mock()
        mock_hassette._scheduler_service = Mock()
        mock_hassette._scheduler_service.register_removal_callback = Mock()
        with pytest.raises(AssertionError, match="Scheduler requires a parent"):
            Scheduler(mock_hassette, parent=None)


class TestDbIdSetImmediately:
    """AC#7 analog for scheduler: job.db_id is set before run_*() returns."""

    async def test_db_id_set_immediately_after_run_in_returns(self) -> None:
        """job.db_id is a valid integer immediately after await run_in() returns.

        Under synchronous registration, the DB INSERT is awaited inline before
        returning to the caller. No background task, no deferred future to await.
        """
        scheduler = make_scheduler()
        job = await scheduler.run_in(noop, delay=30)

        assert job.db_id is not None, "db_id must be set immediately on return"
        assert isinstance(job.db_id, int), f"db_id must be int, got {type(job.db_id)}"
        assert job.db_id > 0, f"db_id must be a positive integer, got {job.db_id}"

    async def test_db_id_set_immediately_after_schedule_returns(self) -> None:
        """job.db_id is a valid integer immediately after await schedule() returns."""
        scheduler = make_scheduler()
        job = await scheduler.schedule(noop, Every(hours=1))

        assert job.db_id is not None, "db_id must be set immediately on return"
        assert isinstance(job.db_id, int), f"db_id must be int, got {type(job.db_id)}"
        assert job.db_id > 0, f"db_id must be a positive integer, got {job.db_id}"

    async def test_no_db_id_none_window_add_job_is_awaited(self) -> None:
        """scheduler_service.add_job is awaited inline — not spawned as background task.

        Verifies that after await add_job() returns, the job has db_id set.
        Regression guard against reverting to task_bucket.spawn().
        """
        scheduler = make_scheduler()
        job = make_job()

        await scheduler.add_job(job)

        assert job.db_id is not None, "db_id must be set after add_job returns (no spawn)"
        assert scheduler.scheduler_service.add_job.await_count == 1, "add_job must be awaited exactly once"
