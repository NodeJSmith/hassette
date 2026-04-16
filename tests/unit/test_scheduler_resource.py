"""Unit tests for Scheduler resource: new schedule() entry point, job groups, convenience wrappers."""

from collections.abc import Callable
from unittest.mock import Mock, patch

import pytest
from whenever import ZonedDateTime

from hassette.resources.base import Resource
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import After, Cron, Daily, Every, Once
from hassette.utils.date_utils import now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler(removal_callback_supported: bool = True) -> Scheduler:
    """Create a minimal Scheduler instance with mocked internals.

    Uses a unique per-call subclass so that property overrides for owner_id and
    parent do NOT mutate the shared Scheduler class — which would break parallel
    test workers that create real Scheduler instances concurrently.
    """
    # Fresh subclass per call: property assignments stay on _TestScheduler, not Scheduler.
    _TestScheduler = type("_TestScheduler", (Scheduler,), {})  # noqa: N806
    _TestScheduler.owner_id = property(lambda _self: "test_owner")  # pyright: ignore[reportAttributeAccessIssue]
    _TestScheduler.parent = property(lambda _self: None)  # pyright: ignore[reportAttributeAccessIssue]

    scheduler = _TestScheduler.__new__(_TestScheduler)
    mock_service = Mock()
    if removal_callback_supported:
        mock_service.register_removal_callback = Mock()
    else:
        del mock_service.register_removal_callback
    scheduler.scheduler_service = mock_service
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    return scheduler


def _make_job(
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


async def _noop() -> None:
    pass


# ---------------------------------------------------------------------------
# schedule() entry point
# ---------------------------------------------------------------------------


class TestScheduleEntryPoint:
    def test_schedule_creates_job_with_trigger(self) -> None:
        """schedule(cb, Every(hours=1)) returns a ScheduledJob with the correct trigger."""
        scheduler = _make_scheduler()
        trigger = Every(hours=1)
        job = scheduler.schedule(_noop, trigger)
        assert isinstance(job, ScheduledJob)
        assert job.trigger is trigger

    def test_schedule_fires_first_run_time_from_trigger(self) -> None:
        """job.next_run equals trigger.first_run_time(now) — within 2 seconds."""
        scheduler = _make_scheduler()
        trigger = Every(hours=1)
        before = now()
        job = scheduler.schedule(_noop, trigger)
        after = now()
        expected_min = trigger.first_run_time(before)
        expected_max = trigger.first_run_time(after)
        assert expected_min <= job.next_run <= expected_max

    def test_schedule_group_tracked(self) -> None:
        """schedule with group= adds job to _jobs_by_group."""
        scheduler = _make_scheduler()
        job = scheduler.schedule(_noop, Daily(at="07:00"), group="morning")
        assert "morning" in scheduler._jobs_by_group
        assert job in scheduler._jobs_by_group["morning"]

    def test_schedule_no_group_not_in_jobs_by_group(self) -> None:
        """schedule without group= does not add to _jobs_by_group."""
        scheduler = _make_scheduler()
        scheduler.schedule(_noop, Every(seconds=30))
        assert scheduler._jobs_by_group == {}


# ---------------------------------------------------------------------------
# cancel_group()
# ---------------------------------------------------------------------------


class TestCancelGroup:
    def test_cancel_group_cancels_all_members(self) -> None:
        """All jobs in a group have cancelled=True after cancel_group()."""
        scheduler = _make_scheduler()
        job1 = scheduler.schedule(_noop, Every(hours=1), name="job1", group="morning")
        job2 = scheduler.schedule(_noop, Every(hours=2), name="job2", group="morning")
        scheduler.cancel_group("morning")
        assert job1.cancelled
        assert job2.cancelled

    def test_cancel_group_nonexistent_noop(self) -> None:
        """cancel_group('ghost') does not raise."""
        scheduler = _make_scheduler()
        scheduler.cancel_group("ghost")  # should not raise

    def test_cancel_group_clears_group_key(self) -> None:
        """After cancellation, the group key is removed from _jobs_by_group."""
        scheduler = _make_scheduler()
        scheduler.schedule(_noop, Every(hours=1), group="morning")
        scheduler.cancel_group("morning")
        assert "morning" not in scheduler._jobs_by_group

    def test_cancel_group_calls_remove_job_on_service(self) -> None:
        """cancel_group calls scheduler_service.remove_job for each member."""
        scheduler = _make_scheduler()
        scheduler.schedule(_noop, Every(hours=1), name="job1", group="morning")
        scheduler.schedule(_noop, Every(hours=2), name="job2", group="morning")
        scheduler.cancel_group("morning")
        # remove_job called twice
        assert scheduler.scheduler_service.remove_job.call_count == 2

    def test_cancel_group_persists_cancelled_at_for_registered_jobs(self) -> None:
        """cancel_group spawns mark_job_cancelled for each job with a db_id set."""
        import asyncio
        from unittest.mock import MagicMock

        scheduler = _make_scheduler()
        # Add a task_bucket mock. Close any coroutine passed to spawn to avoid
        # "coroutine never awaited" warnings when mark_job_cancelled returns a real coro.
        spawned_coroutines: list = []

        def _spawn_and_close(coro, *, name=""):
            spawned_coroutines.append((coro, name))
            if asyncio.iscoroutine(coro):
                coro.close()  # clean up to avoid "never awaited" warnings

        scheduler.task_bucket = MagicMock()
        scheduler.task_bucket.spawn.side_effect = _spawn_and_close

        job1 = scheduler.schedule(_noop, Every(hours=1), name="job1", group="morning")
        job2 = scheduler.schedule(_noop, Every(hours=2), name="job2", group="morning")

        # Simulate both jobs having been persisted
        job1.mark_registered(101)
        job2.mark_registered(102)

        scheduler.cancel_group("morning")

        # task_bucket.spawn must have been called once per job with a db_id
        assert scheduler.task_bucket.spawn.call_count == 2
        # Verify the spawn calls used the correct task name
        for _coro, name in spawned_coroutines:
            assert name == "scheduler:mark_job_cancelled"

    def test_cancel_group_skips_mark_job_cancelled_when_db_id_none(self) -> None:
        """cancel_group does not spawn mark_job_cancelled for jobs without db_id."""
        from unittest.mock import MagicMock

        scheduler = _make_scheduler()
        scheduler.task_bucket = MagicMock()

        # Jobs not yet persisted (db_id=None)
        scheduler.schedule(_noop, Every(hours=1), name="job1", group="morning")
        scheduler.schedule(_noop, Every(hours=2), name="job2", group="morning")

        scheduler.cancel_group("morning")

        # task_bucket.spawn must NOT be called (no db_ids set)
        scheduler.task_bucket.spawn.assert_not_called()


# ---------------------------------------------------------------------------
# list_jobs()
# ---------------------------------------------------------------------------


class TestListJobs:
    def test_list_jobs_no_filter(self) -> None:
        """list_jobs() returns all 3 jobs across 2 groups."""
        scheduler = _make_scheduler()
        job1 = scheduler.schedule(_noop, Every(hours=1), name="a", group="g1")
        job2 = scheduler.schedule(_noop, Every(hours=2), name="b", group="g1")
        job3 = scheduler.schedule(_noop, Every(hours=3), name="c", group="g2")
        result = scheduler.list_jobs()
        assert sorted(result, key=lambda j: j.name) == sorted([job1, job2, job3], key=lambda j: j.name)

    def test_list_jobs_group_filter(self) -> None:
        """list_jobs(group=) returns only group-matched jobs."""
        scheduler = _make_scheduler()
        job1 = scheduler.schedule(_noop, Every(hours=1), name="a", group="g1")
        scheduler.schedule(_noop, Every(hours=2), name="b", group="g2")
        result = scheduler.list_jobs(group="g1")
        assert result == [job1]

    def test_list_jobs_empty_group_returns_empty(self) -> None:
        """list_jobs(group='ghost') returns empty list for unknown group."""
        scheduler = _make_scheduler()
        scheduler.schedule(_noop, Every(hours=1), name="a", group="g1")
        assert scheduler.list_jobs(group="ghost") == []


# ---------------------------------------------------------------------------
# _jobs_by_group maintenance
# ---------------------------------------------------------------------------


class TestJobsByGroupMaintenance:
    def test_remove_job_removes_from_group(self) -> None:
        """remove_job() removes the job from _jobs_by_group."""
        scheduler = _make_scheduler()
        job = scheduler.schedule(_noop, Every(hours=1), group="morning")
        assert job in scheduler._jobs_by_group["morning"]
        scheduler.remove_job(job)
        assert "morning" not in scheduler._jobs_by_group

    def test_remove_job_leaves_other_group_members(self) -> None:
        """remove_job() for one job doesn't remove sibling from _jobs_by_group."""
        scheduler = _make_scheduler()
        job1 = scheduler.schedule(_noop, Every(hours=1), name="a", group="g")
        job2 = scheduler.schedule(_noop, Every(hours=2), name="b", group="g")
        scheduler.remove_job(job1)
        assert "g" in scheduler._jobs_by_group
        assert job2 in scheduler._jobs_by_group["g"]

    def test_remove_all_jobs_clears_groups(self) -> None:
        """remove_all_jobs() empties _jobs_by_group."""
        scheduler = _make_scheduler()
        scheduler.schedule(_noop, Every(hours=1), name="a", group="g1")
        scheduler.schedule(_noop, Every(hours=2), name="b", group="g2")
        scheduler.remove_all_jobs()
        assert scheduler._jobs_by_group == {}

    def test_removal_callback_called_on_exhaustion(self) -> None:
        """Simulated SchedulerService exhaustion notification triggers group removal."""
        scheduler = _make_scheduler()
        job = scheduler.schedule(_noop, After(seconds=30), group="once_group")
        assert job in scheduler._jobs_by_group["once_group"]

        # Directly invoke the callback as SchedulerService would after a one-shot job fires
        scheduler._on_job_removed(job)

        assert "once_group" not in scheduler._jobs_by_group
        assert job.name not in scheduler._jobs_by_name


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


class TestConvenienceWrappers:
    def test_run_daily_delegates_to_daily_trigger(self) -> None:
        """run_daily(cb, at='07:00') schedules with Daily(at='07:00')."""
        scheduler = _make_scheduler()
        job = scheduler.run_daily(_noop, at="07:00")
        assert isinstance(job.trigger, Daily)
        assert job.trigger.trigger_id() == "cron:0 7 * * *"

    def test_run_in_delegates_to_after_trigger(self) -> None:
        """run_in(cb, 30) schedules with After(seconds=30)."""
        scheduler = _make_scheduler()
        job = scheduler.run_in(_noop, 30)
        assert isinstance(job.trigger, After)
        assert job.trigger._delay.in_seconds() == 30

    def test_run_in_accepts_float_seconds(self) -> None:
        """run_in accepts a float number of seconds."""
        scheduler = _make_scheduler()
        job = scheduler.run_in(_noop, 60.0)
        assert isinstance(job.trigger, After)

    def test_run_cron_string_form_accepted(self) -> None:
        """run_cron(cb, '0 9 * * 1-5') works with a cron expression string."""
        scheduler = _make_scheduler()
        job = scheduler.run_cron(_noop, "0 9 * * 1-5")
        assert isinstance(job.trigger, Cron)

    def test_run_every_keywords_accepted(self) -> None:
        """run_every(cb, hours=1) works."""
        scheduler = _make_scheduler()
        job = scheduler.run_every(_noop, hours=1)
        assert isinstance(job.trigger, Every)

    def test_run_every_minutes_keywords_accepted(self) -> None:
        """run_every(cb, minutes=5) works."""
        scheduler = _make_scheduler()
        job = scheduler.run_every(_noop, minutes=5)
        assert isinstance(job.trigger, Every)

    def test_run_every_seconds_keywords_accepted(self) -> None:
        """run_every(cb, seconds=30) works."""
        scheduler = _make_scheduler()
        job = scheduler.run_every(_noop, seconds=30)
        assert isinstance(job.trigger, Every)

    def test_run_minutely_delegates_to_every_trigger(self) -> None:
        """run_minutely(cb, minutes=5) schedules with Every(minutes=5)."""
        scheduler = _make_scheduler()
        job = scheduler.run_minutely(_noop, minutes=5)
        assert isinstance(job.trigger, Every)
        assert job.trigger.interval_seconds == 300.0

    def test_run_hourly_delegates_to_every_trigger(self) -> None:
        """run_hourly(cb, hours=2) schedules with Every(hours=2)."""
        scheduler = _make_scheduler()
        job = scheduler.run_hourly(_noop, hours=2)
        assert isinstance(job.trigger, Every)
        assert job.trigger.interval_seconds == 7200.0

    def test_run_once_string_form_accepted(self) -> None:
        """run_once(cb, at='23:59') works with str."""
        scheduler = _make_scheduler()
        job = scheduler.run_once(_noop, at="23:59")
        assert isinstance(job.trigger, Once)

    def test_run_once_zoned_datetime_accepted(self) -> None:
        """run_once(cb, at=ZonedDateTime) works with ZonedDateTime."""
        scheduler = _make_scheduler()
        future = now().add(hours=1)
        job = scheduler.run_once(_noop, at=future)
        assert isinstance(job.trigger, Once)

    def test_run_in_jitter_forwarded(self) -> None:
        """run_in with jitter=60 creates a job with jitter=60."""
        scheduler = _make_scheduler()
        job = scheduler.run_in(_noop, 30, jitter=60)
        assert job.jitter == 60

    def test_run_once_jitter_forwarded(self) -> None:
        """run_once with jitter=30 creates a job with jitter=30."""
        scheduler = _make_scheduler()
        job = scheduler.run_once(_noop, at="23:59", jitter=30)
        assert job.jitter == 30

    def test_run_every_jitter_forwarded(self) -> None:
        """run_every with jitter=10 creates a job with jitter=10."""
        scheduler = _make_scheduler()
        job = scheduler.run_every(_noop, seconds=30, jitter=10)
        assert job.jitter == 10

    def test_run_minutely_jitter_forwarded(self) -> None:
        """run_minutely with jitter=5 creates a job with jitter=5."""
        scheduler = _make_scheduler()
        job = scheduler.run_minutely(_noop, jitter=5)
        assert job.jitter == 5

    def test_run_hourly_jitter_forwarded(self) -> None:
        """run_hourly with jitter=120 creates a job with jitter=120."""
        scheduler = _make_scheduler()
        job = scheduler.run_hourly(_noop, jitter=120)
        assert job.jitter == 120

    def test_run_daily_jitter_forwarded(self) -> None:
        """run_daily with jitter=60 creates a job with jitter=60."""
        scheduler = _make_scheduler()
        job = scheduler.run_daily(_noop, at="07:00", jitter=60)
        assert job.jitter == 60

    def test_run_cron_jitter_forwarded(self) -> None:
        """run_cron with jitter=15 creates a job with jitter=15."""
        scheduler = _make_scheduler()
        job = scheduler.run_cron(_noop, "0 9 * * 1-5", jitter=15)
        assert job.jitter == 15

    def test_run_once_if_past_error_raises(self) -> None:
        """run_once(..., if_past='error') raises ValueError when target time is in the past."""
        # Fix "now" to a known future time so "00:00" is in the past
        fake_now = ZonedDateTime(2025, 8, 18, 8, 0, 0, tz="America/Chicago")
        with patch("hassette.utils.date_utils.now", return_value=fake_now):
            scheduler = _make_scheduler()
            with pytest.raises(ValueError, match="constructed after the target time"):
                scheduler.run_once(_noop, at="00:00", if_past="error")

    def test_run_daily_group_forwarded(self) -> None:
        """run_daily with group= adds job to _jobs_by_group."""
        scheduler = _make_scheduler()
        job = scheduler.run_daily(_noop, at="06:00", group="morning")
        assert job in scheduler._jobs_by_group["morning"]

    def test_run_in_group_forwarded(self) -> None:
        """run_in with group= adds job to _jobs_by_group."""
        scheduler = _make_scheduler()
        job = scheduler.run_in(_noop, 30, group="once")
        assert job in scheduler._jobs_by_group["once"]


# ---------------------------------------------------------------------------
# Callback registration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# F3: TypeError fail-fast for non-protocol triggers
# ---------------------------------------------------------------------------


class TestScheduleTypeError:
    def test_schedule_raises_typeerror_for_non_protocol_trigger(self) -> None:
        """schedule() with a non-TriggerProtocol trigger raises TypeError immediately."""

        class NotATrigger:
            pass

        scheduler = _make_scheduler()
        with pytest.raises(TypeError, match="trigger must implement TriggerProtocol"):
            scheduler.schedule(_noop, NotATrigger())


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
        _TestScheduler = type("_TestScheduler", (Scheduler,), {})  # noqa: N806
        _TestScheduler.owner_id = property(  # pyright: ignore[reportAttributeAccessIssue]
            lambda _self: "test_owner"
        )
        _TestScheduler.parent = property(  # pyright: ignore[reportAttributeAccessIssue]
            lambda _self: None
        )

        # Stub Resource.__init__ so super().__init__() is a no-op; the rest of
        # Scheduler.__init__ still runs and must call register_removal_callback directly.
        with patch.object(Resource, "__init__", return_value=None):

            def _hassette(_self: object) -> object:
                return mock_hassette

            _TestScheduler.hassette = property(_hassette)  # pyright: ignore[reportAttributeAccessIssue]
            _TestScheduler(mock_hassette)

        mock_hassette._scheduler_service.register_removal_callback.assert_called_once()
        call_args = mock_hassette._scheduler_service.register_removal_callback.call_args
        assert call_args.args[0] == "test_owner"
        assert callable(call_args.args[1])
