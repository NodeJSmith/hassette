"""Tests for Job lifecycle: construction, removal, and diffing.

Covers __post_init__ (timeout/timeout_disabled conflict, bool-timeout
rejection), __hash__, __repr__, remove(), set_app_error_handler_resolver(), set_next_run(),
diff_fields(), and the matches()/trigger-None branches not covered by
test_scheduled_job_timeout.py.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from whenever import ZonedDateTime

from hassette.execution_mode import ExecutionModeGuard
from hassette.scheduler.classes import Job, ScheduleStatus, ScheduleStatusReason
from hassette.scheduler.triggers import Every
from hassette.test_utils.factories import make_scheduled_job
from hassette.test_utils.helpers import noop
from hassette.types.enums import ExecutionMode
from hassette.utils.date_utils import now

from .conftest import TZ


def make_job_with_args(*, args: Any = (), kwargs: dict | None = None, **overrides) -> Job:
    """Build a real Job with args/kwargs pass-through.

    ``args``/``kwargs`` aren't covered by the shared ``make_scheduled_job()`` factory
    (they're excluded from its parameter set), so tests exercising ``__post_init__``
    normalization of these fields construct directly.
    """
    defaults: dict = {"owner_id": "test_owner", "next_run": now(), "job": noop}
    defaults.update(overrides)
    return Job(args=args, kwargs=kwargs or {}, **defaults)


class TestPostInitValidation:
    def test_timeout_and_timeout_disabled_conflict_raises(self) -> None:
        """Specifying both timeout and timeout_disabled=True raises ValueError."""
        with pytest.raises(ValueError, match="Cannot specify both 'timeout' and 'timeout_disabled=True'"):
            make_scheduled_job(timeout=5.0, timeout_disabled=True)

    def test_timeout_bool_true_rejected(self) -> None:
        """timeout=True (a bool, which is an int subclass) is explicitly rejected."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            make_scheduled_job(timeout=True)

    def test_timeout_positive_float_accepted(self) -> None:
        """A positive float timeout is accepted without error."""
        job = make_scheduled_job(timeout=5.0)
        assert job.timeout == 5.0

    def test_timeout_disabled_alone_accepted(self) -> None:
        """timeout_disabled=True with no timeout set is accepted."""
        job = make_scheduled_job(timeout_disabled=True)
        assert job.timeout_disabled is True
        assert job.timeout is None

    def test_args_and_kwargs_normalized_from_list(self) -> None:
        """Args passed as a list is normalized to a tuple; kwargs stays a dict."""
        job = make_job_with_args(args=[1, 2, 3], kwargs={"a": 1})
        assert job.args == (1, 2, 3)
        assert isinstance(job.args, tuple)
        assert job.kwargs == {"a": 1}

    def test_guard_created_from_mode(self) -> None:
        """__post_init__ builds an ExecutionModeGuard matching the job's mode."""
        job = make_scheduled_job(mode=ExecutionMode.RESTART)
        assert isinstance(job.guard, ExecutionModeGuard)

    def test_scheduled_status_without_next_run_raises(self) -> None:
        """SCHEDULED (the default) with next_run=None raises — mirrors transition_to()'s guard."""
        with pytest.raises(ValueError, match="requires a concrete next_run"):
            Job(owner_id="test_owner", next_run=None, job=noop, name="bad_job")

    def test_manual_construction_with_no_next_run_succeeds(self) -> None:
        """A manual-only job (schedule_status=MANUAL, no trigger) with next_run=None is a
        valid, non-raising construction — it never has an automatic occurrence.
        """
        job = Job(
            owner_id="test_owner",
            next_run=None,
            job=noop,
            name="manual_job",
            schedule_status=ScheduleStatus.MANUAL,
        )
        assert job.schedule_status is ScheduleStatus.MANUAL
        assert job.trigger is None
        assert job.next_run is None
        assert job.fire_at is None


class TestHashAndRepr:
    def test_hash_matches_object_identity(self) -> None:
        """__hash__ returns id(self), matching the documented identity-hash contract."""
        job = make_scheduled_job()
        assert hash(job) == id(job)

    def test_distinct_jobs_have_distinct_hashes(self) -> None:
        """Two distinct Job instances hash differently (identity-based)."""
        job1 = make_scheduled_job(name="job1")
        job2 = make_scheduled_job(name="job2")
        assert hash(job1) != hash(job2)

    def test_repr_includes_name_and_owner(self) -> None:
        """__repr__ returns 'Job(name=..., owner_id=...)'."""
        job = make_scheduled_job(name="my_job", owner_id="my_owner")
        assert repr(job) == "Job(name='my_job', owner_id=my_owner)"


class TestRemove:
    def test_remove_without_scheduler_raises_runtime_error(self) -> None:
        """remove() on a job with no registered _scheduler raises RuntimeError."""
        job = make_scheduled_job()
        assert job._scheduler is None
        with pytest.raises(RuntimeError, match="not registered with a Scheduler"):
            job.remove()

    def test_remove_delegates_to_scheduler(self) -> None:
        """remove() calls scheduler.remove_job(self) when _scheduler is set."""
        job = make_scheduled_job()
        mock_scheduler = MagicMock()
        job._scheduler = mock_scheduler

        job.remove()

        mock_scheduler.remove_job.assert_called_once_with(job)


class TestSetAppErrorHandlerResolver:
    def test_set_app_error_handler_resolver_stores_closure(self) -> None:
        """set_app_error_handler_resolver() stores the resolver for later dispatch-time lookup."""
        job = make_scheduled_job()
        assert job.app_error_handler_resolver is None

        def resolver():
            return None

        job.set_app_error_handler_resolver(resolver)
        assert job.app_error_handler_resolver is resolver


class TestSetNextRun:
    def test_set_next_run_rounds_to_second(self) -> None:
        """set_next_run() rounds the given time to the nearest second for next_run and fire_at."""
        job = make_scheduled_job()
        precise_time = ZonedDateTime(2025, 8, 18, 7, 0, 30, nanosecond=500_000_000, tz=TZ)

        job.set_next_run(precise_time)

        expected = precise_time.round("second")
        assert job.next_run == expected
        assert job.fire_at == expected

    def test_set_next_run_updates_sort_index(self) -> None:
        """set_next_run() updates sort_index to (rounded_timestamp_nanos, id(self))."""
        job = make_scheduled_job()
        new_time = ZonedDateTime(2030, 1, 1, 0, 0, 0, tz=TZ)

        job.set_next_run(new_time)

        expected_nanos = new_time.round("second").timestamp_nanos()
        assert job.sort_index == (expected_nanos, id(job))

    def test_set_next_run_changes_ordering(self) -> None:
        """Updating next_run via set_next_run changes the job's heap ordering position."""
        job = make_scheduled_job(next_run=ZonedDateTime(2025, 1, 1, tz=TZ))
        earlier_sort_index = job.sort_index

        job.set_next_run(ZonedDateTime(2020, 1, 1, tz=TZ))

        assert job.sort_index < earlier_sort_index

    def test_set_next_run_none_clears_timing_and_leaves_sort_index(self) -> None:
        """set_next_run(None) clears next_run/fire_at but leaves sort_index untouched —
        a job in this state must never be inserted into the heap, so a stale sort_index
        is never read.
        """
        job = make_scheduled_job(next_run=ZonedDateTime(2025, 1, 1, tz=TZ))
        previous_sort_index = job.sort_index

        job.set_next_run(None)

        assert job.next_run is None
        assert job.fire_at is None
        assert job.sort_index == previous_sort_index


class TestTransitionTo:
    def test_scheduled_without_next_run_raises(self) -> None:
        """transition_to(SCHEDULED, ...) with no next_run raises ValueError."""
        job = make_scheduled_job()
        with pytest.raises(ValueError, match="requires a concrete next_run"):
            job.transition_to(ScheduleStatus.SCHEDULED)

    def test_transition_to_scheduled_sets_next_run_and_fire_at(self) -> None:
        """transition_to(SCHEDULED, next_run=...) sets next_run and defaults fire_at to it."""
        job = make_scheduled_job()
        target = ZonedDateTime(2030, 1, 1, 7, 0, 0, tz=TZ)

        job.transition_to(ScheduleStatus.SCHEDULED, next_run=target)

        assert job.schedule_status is ScheduleStatus.SCHEDULED
        assert job.next_run == target.round("second")
        assert job.fire_at == target.round("second")

    def test_transition_to_scheduled_honors_explicit_fire_at_override(self) -> None:
        """An explicit fire_at overrides the default (rounded next_run) fire_at."""
        job = make_scheduled_job()
        next_run = ZonedDateTime(2030, 1, 1, 7, 0, 0, tz=TZ)
        jittered_fire_at = ZonedDateTime(2030, 1, 1, 7, 0, 5, tz=TZ)

        job.transition_to(ScheduleStatus.SCHEDULED, next_run=next_run, fire_at=jittered_fire_at)

        assert job.next_run == next_run.round("second")
        assert job.fire_at == jittered_fire_at

    def test_transition_to_non_scheduled_clears_next_run_and_fire_at(self) -> None:
        """Leaving SCHEDULED clears next_run/fire_at regardless of what a caller passes."""
        job = make_scheduled_job(next_run=ZonedDateTime(2025, 1, 1, tz=TZ))
        assert job.next_run is not None

        job.transition_to(ScheduleStatus.COMPLETED)

        assert job.schedule_status is ScheduleStatus.COMPLETED
        assert job.next_run is None
        assert job.fire_at is None

    def test_transition_to_non_scheduled_ignores_next_run_and_fire_at_args(self) -> None:
        """next_run/fire_at passed alongside a non-SCHEDULED status are ignored and cleared."""
        job = make_scheduled_job()

        job.transition_to(
            ScheduleStatus.WAITING,
            next_run=ZonedDateTime(2030, 1, 1, tz=TZ),
            fire_at=ZonedDateTime(2030, 1, 1, tz=TZ),
        )

        assert job.schedule_status is ScheduleStatus.WAITING
        assert job.next_run is None
        assert job.fire_at is None

    def test_transition_to_manual_clears_timing(self) -> None:
        """transition_to(MANUAL) clears timing like every other non-SCHEDULED status."""
        job = make_scheduled_job()

        job.transition_to(ScheduleStatus.MANUAL)

        assert job.schedule_status is ScheduleStatus.MANUAL
        assert job.next_run is None
        assert job.fire_at is None

    def test_transition_to_sets_explicit_reason(self) -> None:
        """An explicit reason is stored on schedule_status_reason."""
        job = make_scheduled_job()

        job.transition_to(ScheduleStatus.COMPLETED, reason=ScheduleStatusReason.TRIGGER_ERROR)

        assert job.schedule_status_reason is ScheduleStatusReason.TRIGGER_ERROR

    def test_transition_to_clears_reason_when_not_passed(self) -> None:
        """A prior reason does not leak into a later transition that omits reason=."""
        job = make_scheduled_job()
        job.transition_to(ScheduleStatus.COMPLETED, reason=ScheduleStatusReason.TRIGGER_ERROR)
        assert job.schedule_status_reason is ScheduleStatusReason.TRIGGER_ERROR

        job.transition_to(ScheduleStatus.SCHEDULED, next_run=ZonedDateTime(2030, 1, 1, tz=TZ))

        assert job.schedule_status_reason is None


class TestMatchesTriggerNoneBranches:
    def test_matches_true_when_both_triggers_none(self) -> None:
        """matches() is True when both jobs have trigger=None (identity comparison of None)."""
        job1 = make_scheduled_job(job=noop, trigger=None, name="j1")
        job2 = make_scheduled_job(job=noop, trigger=None, name="j2")
        assert job1.matches(job2)

    def test_matches_false_when_one_trigger_none(self) -> None:
        """matches() is False when only one job has a trigger set."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), name="j1")
        job2 = make_scheduled_job(job=noop, trigger=None, name="j2")
        assert not job1.matches(job2)
        assert not job2.matches(job1)

    def test_matches_false_when_job_callable_differs(self) -> None:
        """matches() is False when the underlying callable differs."""

        async def other_job() -> None:
            pass

        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1))
        job2 = make_scheduled_job(job=other_job, trigger=Every(hours=1))
        assert not job1.matches(job2)

    def test_matches_false_when_args_differ(self) -> None:
        """matches() is False when positional args differ."""
        job1 = make_job_with_args(job=noop, args=(1, 2))
        job2 = make_job_with_args(job=noop, args=(3, 4))
        assert not job1.matches(job2)

    def test_matches_false_when_kwargs_differ(self) -> None:
        """matches() is False when keyword args differ."""
        job1 = make_job_with_args(job=noop, kwargs={"x": 1})
        job2 = make_job_with_args(job=noop, kwargs={"x": 2})
        assert not job1.matches(job2)


class TestDiffFields:
    def test_diff_fields_empty_when_identical(self) -> None:
        """diff_fields() returns an empty list when all compared fields match."""
        job1 = make_job_with_args(job=noop, trigger=Every(hours=1), group="g", args=(1,), kwargs={"a": 1})
        job2 = make_job_with_args(job=noop, trigger=Every(hours=1), group="g", args=(1,), kwargs={"a": 1})
        assert job1.diff_fields(job2) == []

    def test_diff_fields_detects_job_change(self) -> None:
        """diff_fields() includes 'job' when the callable differs."""

        async def other_job() -> None:
            pass

        job1 = make_scheduled_job(job=noop)
        job2 = make_scheduled_job(job=other_job)
        assert "job" in job1.diff_fields(job2)

    def test_diff_fields_detects_trigger_change(self) -> None:
        """diff_fields() includes 'trigger' when trigger_id() differs."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1))
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=2))
        assert "trigger" in job1.diff_fields(job2)

    def test_diff_fields_trigger_unchanged_when_both_none(self) -> None:
        """diff_fields() does not report 'trigger' when both jobs have trigger=None."""
        job1 = make_scheduled_job(job=noop, trigger=None)
        job2 = make_scheduled_job(job=noop, trigger=None)
        assert "trigger" not in job1.diff_fields(job2)

    def test_diff_fields_detects_group_change(self) -> None:
        """diff_fields() includes 'group' when group differs."""
        job1 = make_scheduled_job(job=noop, group="a")
        job2 = make_scheduled_job(job=noop, group="b")
        assert "group" in job1.diff_fields(job2)

    def test_diff_fields_detects_jitter_change(self) -> None:
        """diff_fields() includes 'jitter' when jitter differs."""
        job1 = make_scheduled_job(job=noop, jitter=1.0)
        job2 = make_scheduled_job(job=noop, jitter=2.0)
        assert "jitter" in job1.diff_fields(job2)

    def test_diff_fields_detects_timeout_change(self) -> None:
        """diff_fields() includes 'timeout' when timeout differs."""
        job1 = make_scheduled_job(job=noop, timeout=5.0)
        job2 = make_scheduled_job(job=noop, timeout=10.0)
        assert "timeout" in job1.diff_fields(job2)

    def test_diff_fields_detects_timeout_disabled_change(self) -> None:
        """diff_fields() includes 'timeout_disabled' when it differs."""
        job1 = make_scheduled_job(job=noop, timeout_disabled=False)
        job2 = make_scheduled_job(job=noop, timeout_disabled=True)
        assert "timeout_disabled" in job1.diff_fields(job2)

    def test_diff_fields_detects_args_change(self) -> None:
        """diff_fields() includes 'args' when positional args differ."""
        job1 = make_job_with_args(job=noop, args=(1,))
        job2 = make_job_with_args(job=noop, args=(2,))
        assert "args" in job1.diff_fields(job2)

    def test_diff_fields_detects_kwargs_change(self) -> None:
        """diff_fields() includes 'kwargs' when keyword args differ."""
        job1 = make_job_with_args(job=noop, kwargs={"a": 1})
        job2 = make_job_with_args(job=noop, kwargs={"a": 2})
        assert "kwargs" in job1.diff_fields(job2)

    def test_diff_fields_detects_mode_change(self) -> None:
        """diff_fields() includes 'mode' when the execution mode differs."""
        job1 = make_scheduled_job(job=noop, mode=ExecutionMode.SINGLE)
        job2 = make_scheduled_job(job=noop, mode=ExecutionMode.RESTART)
        assert "mode" in job1.diff_fields(job2)

    def test_diff_fields_reports_multiple_changes(self) -> None:
        """diff_fields() reports every changed field, not just the first."""
        job1 = make_job_with_args(job=noop, group="a", args=(1,))
        job2 = make_job_with_args(job=noop, group="b", args=(2,))
        changed = job1.diff_fields(job2)
        assert "group" in changed
        assert "args" in changed


class TestPredicateField:
    def test_predicate_defaults_to_none(self) -> None:
        """Job constructed without a predicate defaults to None."""
        job = make_scheduled_job()
        assert job.predicate is None

    def test_predicate_stores_callable(self) -> None:
        """Constructing a Job with predicate=<callable> stores it directly."""

        def always_true() -> bool:
            return True

        job = make_scheduled_job(predicate=always_true)
        assert job.predicate is always_true

    def test_predicate_invoker_defaults_to_none(self) -> None:
        """predicate_invoker defaults to None — Scheduler.schedule() passes the built invoker
        alongside predicate; direct construction without one leaves it unset.
        """
        job = make_scheduled_job(predicate=lambda: True)
        assert job.predicate_invoker is None


class TestMatchesPredicate:
    def test_matches_true_with_same_predicate(self) -> None:
        """matches() is True when both jobs share the identical predicate object."""

        def pred() -> bool:
            return True

        job1 = make_scheduled_job(job=noop, predicate=pred)
        job2 = make_scheduled_job(job=noop, predicate=pred)
        assert job1.matches(job2)

    def test_matches_false_with_different_predicate(self) -> None:
        """matches() is False when jobs have different predicate objects (identity for lambdas)."""
        job1 = make_scheduled_job(job=noop, predicate=lambda: True)
        job2 = make_scheduled_job(job=noop, predicate=lambda: True)
        assert not job1.matches(job2)

    def test_matches_false_with_none_vs_predicate(self) -> None:
        """matches() is False when one job has a predicate and the other has None."""
        job1 = make_scheduled_job(job=noop, predicate=lambda: True)
        job2 = make_scheduled_job(job=noop, predicate=None)
        assert not job1.matches(job2)
        assert not job2.matches(job1)

    def test_matches_true_when_both_predicates_none(self) -> None:
        """matches() is True when neither job has a predicate."""
        job1 = make_scheduled_job(job=noop, predicate=None)
        job2 = make_scheduled_job(job=noop, predicate=None)
        assert job1.matches(job2)


class TestDiffFieldsPredicate:
    def test_diff_fields_detects_predicate_change(self) -> None:
        """diff_fields() includes 'predicate' when predicates differ (identity for lambdas)."""
        job1 = make_scheduled_job(job=noop, predicate=lambda: True)
        job2 = make_scheduled_job(job=noop, predicate=lambda: True)
        assert "predicate" in job1.diff_fields(job2)

    def test_diff_fields_predicate_unchanged_when_same_object(self) -> None:
        """diff_fields() does not report 'predicate' when both jobs share the same predicate object."""

        def pred() -> bool:
            return True

        job1 = make_scheduled_job(job=noop, predicate=pred)
        job2 = make_scheduled_job(job=noop, predicate=pred)
        assert "predicate" not in job1.diff_fields(job2)

    def test_diff_fields_predicate_unchanged_when_both_none(self) -> None:
        """diff_fields() does not report 'predicate' when neither job has one."""
        job1 = make_scheduled_job(job=noop, predicate=None)
        job2 = make_scheduled_job(job=noop, predicate=None)
        assert "predicate" not in job1.diff_fields(job2)
