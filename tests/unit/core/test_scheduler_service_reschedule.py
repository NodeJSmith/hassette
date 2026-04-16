"""Unit tests for SchedulerService reschedule_job, jitter, removal callbacks,
and _enqueue_then_register protocol dispatch (WP04).

Tests cover:
- reschedule_job(): None exhaustion removes job
- reschedule_job(): exception from next_run_time() removes job and logs
- reschedule_job(): recurring trigger re-enqueues job with updated next_run
- reschedule_job(): does not branch on job.repeat (field doesn't exist)
- Jitter: sort_index offset applied; job.next_run not mutated
- Jitter: absent when job.jitter is None
- Removal callbacks: invoked on None exhaustion
- Removal callbacks: invoked on exception from next_run_time()
- Removal callbacks: NOT invoked when job is successfully rescheduled
- _enqueue_then_register: uses trigger protocol methods; no isinstance dispatch
"""

import asyncio
import inspect
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

from whenever import ZonedDateTime

import hassette.core.scheduler_service as hassette_svc_module
import hassette.utils.date_utils as date_utils
from hassette.core.scheduler_service import SchedulerService
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import Every

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler_service() -> SchedulerService:
    """Create a SchedulerService with mocked internals, bypassing Resource.__init__."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.registration_await_timeout = 30
    svc.hassette.config.scheduler_behind_schedule_threshold_seconds = 60
    svc._pending_registration_tasks = defaultdict(list)
    svc._removal_callbacks = {}
    svc.logger = MagicMock()

    # Minimal job queue mock
    svc._job_queue = MagicMock()
    svc._job_queue.add = AsyncMock(return_value=None)
    svc._job_queue.remove_job = AsyncMock(return_value=True)

    # kick() is called after enqueue/remove
    svc._wakeup_event = asyncio.Event()

    return svc


def _make_job(
    trigger=None,
    jitter: float | None = None,
    owner_id: str = "test_owner",
) -> ScheduledJob:
    """Create a minimal ScheduledJob for testing."""
    now = date_utils.now()
    return ScheduledJob(
        owner_id=owner_id,
        next_run=now,
        job=lambda: None,
        trigger=trigger,
        jitter=jitter,
    )


def _make_interval_trigger(*, next_returns=None, next_raises=None):
    """Create a mock trigger."""
    trig = MagicMock()
    trig.trigger_db_type.return_value = "interval"
    trig.trigger_label.return_value = "interval"
    trig.trigger_detail.return_value = "3600s"
    trig.trigger_id.return_value = "every:3600"
    if next_raises is not None:
        trig.next_run_time.side_effect = next_raises
    else:
        trig.next_run_time.return_value = next_returns
    return trig


def _frozen_now() -> ZonedDateTime:
    """Return a stable ZonedDateTime for use in monkeypatching."""
    return ZonedDateTime(2025, 1, 15, 12, 0, 0, tz="UTC")


# ---------------------------------------------------------------------------
# reschedule_job() — None exhaustion
# ---------------------------------------------------------------------------


class TestRescheduleNoneRemovesJob:
    async def test_reschedule_none_removes_job(self) -> None:
        """next_run_time() returning None removes the job; job not re-enqueued."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_returns=None)
        job = _make_job(trigger=trig)

        # reset call counts after construction
        svc._job_queue.add.reset_mock()

        await svc.reschedule_job(job)

        svc._job_queue.remove_job.assert_called_once_with(job)
        svc._job_queue.add.assert_not_called()

    async def test_reschedule_cancelled_removes_job(self) -> None:
        """Cancelled job is removed without calling next_run_time()."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_returns=date_utils.now().add(seconds=60))
        job = _make_job(trigger=trig)
        job.cancel()

        await svc.reschedule_job(job)

        svc._job_queue.remove_job.assert_called_once_with(job)
        trig.next_run_time.assert_not_called()


# ---------------------------------------------------------------------------
# reschedule_job() — exception handling
# ---------------------------------------------------------------------------


class TestRescheduleExceptionRemovesJob:
    async def test_reschedule_exception_removes_job_and_logs(self) -> None:
        """next_run_time() raising removes job and logs exception with job_id, callable, trigger."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_raises=RuntimeError("bad trigger"))
        job = _make_job(trigger=trig)

        await svc.reschedule_job(job)

        svc._job_queue.remove_job.assert_called_once_with(job)
        svc.logger.exception.assert_called_once()

        # Verify the log message contains job_id, callable name, trigger repr context
        call_args = svc.logger.exception.call_args
        log_msg = call_args[0][0]
        assert "job_id" in log_msg
        assert "callable" in log_msg
        assert "trigger" in log_msg

    async def test_reschedule_exception_does_not_propagate(self) -> None:
        """Exceptions from next_run_time() do NOT propagate — scheduler must not crash."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_raises=ValueError("trigger broken"))
        job = _make_job(trigger=trig)

        # Should not raise
        await svc.reschedule_job(job)


# ---------------------------------------------------------------------------
# reschedule_job() — recurring job
# ---------------------------------------------------------------------------


class TestRescheduleRecurring:
    async def test_reschedule_repeat_recurring(self) -> None:
        """Recurring trigger re-enqueues job with updated next_run."""
        svc = _make_scheduler_service()
        future_time = date_utils.now().add(seconds=60)
        trig = _make_interval_trigger(next_returns=future_time)
        job = _make_job(trigger=trig)
        original_run = job.next_run

        await svc.reschedule_job(job)

        # Job should have been re-enqueued (not removed)
        svc._job_queue.remove_job.assert_not_called()
        svc._job_queue.add.assert_called_once_with(job)

        # next_run should be updated
        assert job.next_run != original_run

    async def test_reschedule_no_repeat_flag_consulted(self) -> None:
        """reschedule_job does not reference job.repeat — the field does not exist."""
        svc = _make_scheduler_service()
        future_time = date_utils.now().add(seconds=60)
        trig = _make_interval_trigger(next_returns=future_time)
        job = _make_job(trigger=trig)

        # Confirm that ScheduledJob has no 'repeat' attribute
        assert not hasattr(job, "repeat"), "ScheduledJob must not have a 'repeat' attribute"

        # reschedule must succeed without referencing it
        await svc.reschedule_job(job)


# ---------------------------------------------------------------------------
# Jitter
# ---------------------------------------------------------------------------


class TestJitter:
    async def test_jitter_applied_to_sort_index_not_next_run(self) -> None:
        """After jitter enqueue: job.next_run unchanged; sort_index timestamp > next_run.timestamp_nanos()."""
        svc = _make_scheduler_service()
        future_time = date_utils.now().add(seconds=60)
        trig = _make_interval_trigger(next_returns=future_time)
        job = _make_job(trigger=trig, jitter=10.0)

        # Patch random.uniform to always return the max jitter
        with patch("hassette.core.scheduler_service.random.uniform", return_value=10.0):
            await svc.reschedule_job(job)

        # next_run should be the unjittered future_time
        assert job.next_run == future_time.round(unit="second")

        # sort_index[0] should be > job.next_run.timestamp_nanos() due to jitter
        expected_min_nanos = job.next_run.timestamp_nanos()
        actual_sort_nanos = job.sort_index[0]
        assert actual_sort_nanos > expected_min_nanos, (
            f"sort_index[0]={actual_sort_nanos} should be > next_run.timestamp_nanos()={expected_min_nanos}"
        )

    async def test_jitter_not_applied_when_none(self) -> None:
        """No jitter: sort_index[0] == job.next_run.timestamp_nanos()."""
        svc = _make_scheduler_service()
        future_time = date_utils.now().add(seconds=60)
        trig = _make_interval_trigger(next_returns=future_time)
        job = _make_job(trigger=trig, jitter=None)

        await svc.reschedule_job(job)

        assert job.sort_index[0] == job.next_run.timestamp_nanos()


# ---------------------------------------------------------------------------
# Removal callbacks
# ---------------------------------------------------------------------------


class TestRemovalCallbacks:
    async def test_removal_callback_called_on_none_exhaustion(self) -> None:
        """Registered callback invoked when next_run_time() returns None."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_returns=None)
        job = _make_job(trigger=trig, owner_id="owner_a")

        callback = MagicMock()
        svc.register_removal_callback("owner_a", callback)

        await svc.reschedule_job(job)

        callback.assert_called_once_with(job)

    async def test_removal_callback_called_on_exception(self) -> None:
        """Registered callback invoked when next_run_time() raises."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_raises=RuntimeError("oops"))
        job = _make_job(trigger=trig, owner_id="owner_b")

        callback = MagicMock()
        svc.register_removal_callback("owner_b", callback)

        await svc.reschedule_job(job)

        callback.assert_called_once_with(job)

    async def test_removal_callback_not_called_on_reschedule(self) -> None:
        """Callback NOT called when job is successfully rescheduled."""
        svc = _make_scheduler_service()
        future_time = date_utils.now().add(seconds=60)
        trig = _make_interval_trigger(next_returns=future_time)
        job = _make_job(trigger=trig, owner_id="owner_c")

        callback = MagicMock()
        svc.register_removal_callback("owner_c", callback)

        await svc.reschedule_job(job)

        callback.assert_not_called()

    async def test_removal_callback_registered_and_stored(self) -> None:
        """register_removal_callback stores callback by owner_id."""
        svc = _make_scheduler_service()
        callback = MagicMock()
        svc.register_removal_callback("my_owner", callback)
        assert svc._removal_callbacks.get("my_owner") is callback

    async def test_removal_callback_not_called_for_different_owner(self) -> None:
        """Callback registered for owner_A is not called when owner_B's job is removed."""
        svc = _make_scheduler_service()
        trig = _make_interval_trigger(next_returns=None)
        job = _make_job(trigger=trig, owner_id="owner_b")

        callback_a = MagicMock()
        svc.register_removal_callback("owner_a", callback_a)

        await svc.reschedule_job(job)

        callback_a.assert_not_called()

    async def test_removal_callback_fires_even_when_job_not_in_queue(self) -> None:
        """Callback fires even when _job_queue.remove_job returns False.

        In the normal dispatch path the serve loop already pops the job from the
        queue before reschedule_job is called. remove_job(job) then returns False,
        but the callback must still fire — otherwise one-shot exhaustion never
        notifies the Scheduler to clean up _jobs_by_group/_jobs_by_name.
        """
        svc = _make_scheduler_service()
        # Simulate job already popped by serve loop
        svc._job_queue.remove_job = AsyncMock(return_value=False)
        trig = _make_interval_trigger(next_returns=None)
        job = _make_job(trigger=trig, owner_id="owner_d")

        callback = MagicMock()
        svc.register_removal_callback("owner_d", callback)

        await svc.reschedule_job(job)

        callback.assert_called_once_with(job)


# ---------------------------------------------------------------------------
# _enqueue_then_register — protocol dispatch
# ---------------------------------------------------------------------------


class TestEnqueueThenRegisterUsesProtocol:
    async def test_enqueue_then_register_uses_protocol(self) -> None:
        """_enqueue_then_register uses trigger_db_type(); no isinstance dispatch.

        Verifies that trigger_type in the ScheduledJobRegistration equals
        trigger.trigger_db_type() for an Every trigger (which returns "interval").
        """
        svc = SchedulerService.__new__(SchedulerService)
        svc.hassette = MagicMock()
        svc.hassette.config.registration_await_timeout = 30
        svc._pending_registration_tasks = defaultdict(list)
        svc._removal_callbacks = {}
        svc.logger = MagicMock()
        svc._wakeup_event = asyncio.Event()

        svc._job_queue = MagicMock()
        svc._job_queue.add = AsyncMock(return_value=None)
        svc._job_queue.remove_job = AsyncMock(return_value=True)

        captured_registrations = []

        async def _fake_register_job(reg):
            captured_registrations.append(reg)
            return 42  # fake db_id

        svc._executor = MagicMock()
        svc._executor.register_job = _fake_register_job

        trigger = Every(hours=1)
        now = date_utils.now()
        job = ScheduledJob(
            owner_id="test",
            next_run=now,
            job=lambda: None,
            trigger=trigger,
            app_key="my_app",
        )

        await svc._enqueue_then_register(job)

        assert len(captured_registrations) == 1
        reg = captured_registrations[0]
        # trigger_type must come from trigger.trigger_db_type()
        assert reg.trigger_type == "interval", f"Expected 'interval', got {reg.trigger_type!r}"
        assert reg.trigger_label == "interval"
        assert reg.trigger_detail == "3600s"

    async def test_enqueue_then_register_no_isinstance_import(self) -> None:
        """IntervalTrigger and CronTrigger are not imported in scheduler_service after WP04."""
        src = inspect.getsource(hassette_svc_module)
        # The isinstance dispatch using IntervalTrigger/CronTrigger must be gone
        assert "isinstance(trigger, IntervalTrigger)" not in src, (
            "scheduler_service.py still has isinstance(trigger, IntervalTrigger) dispatch"
        )
        assert "isinstance(trigger, CronTrigger)" not in src, (
            "scheduler_service.py still has isinstance(trigger, CronTrigger) dispatch"
        )


# ---------------------------------------------------------------------------
# _remove_jobs_by_owner — removal callbacks
# ---------------------------------------------------------------------------


class TestRemoveJobsByOwnerCallbacks:
    async def test_remove_jobs_by_owner_fires_callback_for_each_job(self) -> None:
        """_remove_jobs_by_owner invokes registered callback for each removed job."""
        svc = _make_scheduler_service()

        job_a = _make_job(owner_id="owner_x")
        job_b = _make_job(owner_id="owner_x")
        # remove_owner must return the actual removed jobs
        svc._job_queue.remove_owner = AsyncMock(return_value=[job_a, job_b])

        callback = MagicMock()
        svc.register_removal_callback("owner_x", callback)

        await svc._remove_jobs_by_owner("owner_x")

        assert callback.call_count == 2
        callback.assert_any_call(job_a)
        callback.assert_any_call(job_b)

    async def test_remove_jobs_by_owner_no_callback_no_crash(self) -> None:
        """_remove_jobs_by_owner with no registered callback doesn't crash."""
        svc = _make_scheduler_service()
        job = _make_job(owner_id="owner_y")
        svc._job_queue.remove_owner = AsyncMock(return_value=[job])

        # No callback registered — must not raise
        await svc._remove_jobs_by_owner("owner_y")

    async def test_remove_jobs_by_owner_callback_not_called_for_different_owner(self) -> None:
        """Callback for owner_a is not called when owner_b's jobs are removed."""
        svc = _make_scheduler_service()
        job = _make_job(owner_id="owner_b")
        svc._job_queue.remove_owner = AsyncMock(return_value=[job])

        callback_a = MagicMock()
        svc.register_removal_callback("owner_a", callback_a)

        await svc._remove_jobs_by_owner("owner_b")

        callback_a.assert_not_called()


# ---------------------------------------------------------------------------
# reschedule_job() — non-future guard compares against now()
# ---------------------------------------------------------------------------


class TestNonFutureGuard:
    async def test_non_future_guard_compares_against_now(self) -> None:
        """Non-future guard advances job when trigger returns a past time.

        The guard must compare the new next_run against now(), not against
        the previous next_run. A trigger that returns the same time as the
        previous run (B == A) would pass the old delta-from-A check since
        delta == 0, but correctly fails the now() check when B is in the past.
        """
        svc = _make_scheduler_service()
        # Trigger returns a time 5s in the past
        past_time = date_utils.now().add(seconds=-5)
        trig = _make_interval_trigger(next_returns=past_time)
        job = _make_job(trigger=trig)

        await svc.reschedule_job(job)

        # Job should be re-enqueued (not removed — trigger didn't return None)
        svc._job_queue.remove_job.assert_not_called()
        svc._job_queue.add.assert_called_once_with(job)

        # next_run should have been advanced past now
        assert (job.next_run - date_utils.now()).in_seconds() > 0, (
            f"Expected next_run to be future, got delta={job.next_run - date_utils.now()}"
        )
        # A warning must have been logged
        svc.logger.warning.assert_called_once()
