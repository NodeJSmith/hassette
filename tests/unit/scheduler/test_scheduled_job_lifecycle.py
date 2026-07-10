"""Tests for ScheduledJob lifecycle: construction, naming, cancellation, and diffing.

Covers __post_init__ (name auto-generation, timeout/timeout_disabled conflict, bool-timeout
rejection), __hash__, __repr__, cancel(), set_app_error_handler_resolver(), set_next_run(),
diff_fields(), and the matches()/trigger-None branches not covered by
test_scheduled_job_timeout.py.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from whenever import ZonedDateTime

from hassette.execution_mode import ExecutionModeGuard
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import Every
from hassette.test_utils.factories import make_scheduled_job
from hassette.test_utils.helpers import noop
from hassette.types.enums import ExecutionMode
from hassette.utils.date_utils import now

from .conftest import TZ


def make_job_with_args(*, args: Any = (), kwargs: dict | None = None, **overrides) -> ScheduledJob:
    """Build a real ScheduledJob with args/kwargs pass-through.

    ``args``/``kwargs`` aren't covered by the shared ``make_scheduled_job()`` factory
    (they're excluded from its parameter set), so tests exercising ``__post_init__``
    normalization of these fields construct directly.
    """
    defaults: dict = {"owner_id": "test_owner", "next_run": now(), "job": noop}
    defaults.update(overrides)
    return ScheduledJob(args=args, kwargs=kwargs or {}, **defaults)


class CallableWithoutName:
    """A callable object with no __name__ attribute, to exercise the str(self.job) fallback."""

    def __call__(self) -> None:
        pass


class TestNameAutoGeneration:
    def test_name_auto_generated_with_trigger(self) -> None:
        """When no name is given and a trigger is set, name is 'callable_name:trigger_id'."""
        trigger = Every(hours=1)
        job = make_scheduled_job(job=noop, name="", trigger=trigger)
        assert job.name == f"noop:{trigger.trigger_id()}"
        assert job.name_auto is True

    def test_name_auto_generated_without_trigger(self) -> None:
        """When no name is given and no trigger is set, name is just the callable name."""
        job = make_scheduled_job(job=noop, name="", trigger=None)
        assert job.name == "noop"
        assert job.name_auto is True

    def test_name_auto_generation_uses_str_fallback_for_unnamed_callable(self) -> None:
        """A callable object without __name__ falls back to str(self.job) for the name."""
        callable_obj = CallableWithoutName()
        job = make_scheduled_job(job=callable_obj, name="", trigger=None)
        assert job.name == str(callable_obj)
        assert job.name_auto is True

    def test_explicit_name_is_not_overwritten(self) -> None:
        """An explicitly provided name is kept as-is and name_auto stays False."""
        job = make_scheduled_job(name="my_explicit_name", trigger=Every(hours=1))
        assert job.name == "my_explicit_name"
        assert job.name_auto is False


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


class TestHashAndRepr:
    def test_hash_matches_object_identity(self) -> None:
        """__hash__ returns id(self), matching the documented identity-hash contract."""
        job = make_scheduled_job()
        assert hash(job) == id(job)

    def test_distinct_jobs_have_distinct_hashes(self) -> None:
        """Two distinct ScheduledJob instances hash differently (identity-based)."""
        job1 = make_scheduled_job(name="job1")
        job2 = make_scheduled_job(name="job2")
        assert hash(job1) != hash(job2)

    def test_repr_includes_name_and_owner(self) -> None:
        """__repr__ returns 'ScheduledJob(name=..., owner_id=...)'."""
        job = make_scheduled_job(name="my_job", owner_id="my_owner")
        assert repr(job) == "ScheduledJob(name='my_job', owner_id=my_owner)"


class TestCancel:
    def test_cancel_without_scheduler_raises_runtime_error(self) -> None:
        """cancel() on a job with no registered _scheduler raises RuntimeError."""
        job = make_scheduled_job()
        assert job._scheduler is None
        with pytest.raises(RuntimeError, match="not registered with a Scheduler"):
            job.cancel()

    def test_cancel_delegates_to_scheduler(self) -> None:
        """cancel() calls scheduler.cancel_job(self) when _scheduler is set."""
        job = make_scheduled_job()
        mock_scheduler = MagicMock()
        job._scheduler = mock_scheduler

        job.cancel()

        mock_scheduler.cancel_job.assert_called_once_with(job)


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
        """ScheduledJob constructed without a predicate defaults to None."""
        job = make_scheduled_job()
        assert job.predicate is None

    def test_predicate_stores_callable(self) -> None:
        """Constructing a ScheduledJob with predicate=<callable> stores it directly."""

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
