"""Tests for ScheduledJob dataclass — group, jitter, trigger_id matching."""

from whenever import ZonedDateTime

from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import Every
from hassette.utils.date_utils import now


def make_job(
    *,
    job=None,
    trigger=None,
    group: str | None = None,
    jitter: float | None = None,
    name: str = "test_job",
) -> ScheduledJob:
    """Create a minimal ScheduledJob for testing."""
    callable_ = job if job is not None else (lambda: None)
    return ScheduledJob(
        owner_id="test_owner",
        next_run=now(),
        job=callable_,
        name=name,
        trigger=trigger,
        group=group,
        jitter=jitter,
    )


async def noop() -> None:
    pass


class TestMatchesTriggerID:
    def test_matches_same_trigger_id(self) -> None:
        """Two jobs with Every(hours=1) triggers match regardless of object identity."""
        job1 = make_job(job=noop, trigger=Every(hours=1))
        job2 = make_job(job=noop, trigger=Every(hours=1))
        # These are different object instances, but same trigger_id
        assert job1.trigger is not job2.trigger
        assert job1.matches(job2)

    def test_matches_different_trigger_id(self) -> None:
        """Every(hours=1) vs Every(hours=2) do not match."""
        job1 = make_job(job=noop, trigger=Every(hours=1))
        job2 = make_job(job=noop, trigger=Every(hours=2))
        assert not job1.matches(job2)

    def test_matches_different_group(self) -> None:
        """Same callable, same trigger, but different group → no match."""
        job1 = make_job(job=noop, trigger=Every(hours=1), group="morning")
        job2 = make_job(job=noop, trigger=Every(hours=1), group="evening")
        assert not job1.matches(job2)

    def test_matches_same_group(self) -> None:
        """Same callable, same trigger, same group → match."""
        job1 = make_job(job=noop, trigger=Every(hours=1), group="morning")
        job2 = make_job(job=noop, trigger=Every(hours=1), group="morning")
        assert job1.matches(job2)

    def test_matches_no_trigger(self) -> None:
        """Two jobs with trigger=None compare by trigger identity (both None → match)."""
        job1 = make_job(job=noop, trigger=None)
        job2 = make_job(job=noop, trigger=None)
        assert job1.matches(job2)

    def test_matches_one_trigger_none_other_not(self) -> None:
        """One job with trigger, one without → no match."""
        job1 = make_job(job=noop, trigger=Every(hours=1))
        job2 = make_job(job=noop, trigger=None)
        assert not job1.matches(job2)


class TestNewFields:
    def test_group_field_defaults_none(self) -> None:
        """Freshly constructed job has group=None."""
        job = make_job()
        assert job.group is None

    def test_jitter_field_defaults_none(self) -> None:
        """Freshly constructed job has jitter=None."""
        job = make_job()
        assert job.jitter is None

    def test_no_repeat_field(self) -> None:
        """ScheduledJob must not have a repeat attribute at runtime."""
        job = make_job()
        assert not hasattr(job, "repeat")


class TestSetNextRun:
    def test_set_next_run_sort_index(self) -> None:
        """set_next_run() updates sort_index: (timestamp_nanos, id(self))."""
        job = make_job()
        new_time = ZonedDateTime(2030, 1, 1, 12, 0, tz="UTC")
        job.set_next_run(new_time)
        assert job.next_run == new_time.round(unit="second")
        # sort_index tiebreaker is id(self), not job_id
        assert job.sort_index == (new_time.round(unit="second").timestamp_nanos(), id(job))


class TestFireAt:
    def test_fire_at_defaults_to_next_run_without_jitter(self) -> None:
        """Without jitter, fire_at == next_run exactly."""
        job = make_job()
        assert job.fire_at == job.next_run

    def test_fire_at_equals_next_run_after_set_next_run(self) -> None:
        """set_next_run() updates both next_run and fire_at when no jitter."""
        job = make_job()
        new_time = ZonedDateTime(2030, 1, 1, 12, 0, tz="UTC")
        job.set_next_run(new_time)
        assert job.fire_at == job.next_run


class TestMarkRegistered:
    def test_mark_registered_sets_db_id(self) -> None:
        """mark_registered() sets db_id to the given value."""
        job = make_job()
        assert job.db_id is None
        job.mark_registered(42)
        assert job.db_id == 42

    def test_mark_registered_keeps_original_on_double_call(self) -> None:
        """mark_registered() is first-call-wins: a second call does not overwrite the id."""
        job = make_job()
        job.mark_registered(42)
        assert job.db_id == 42

        # Second call is a no-op — the original id is kept (mirrors Listener.mark_registered)
        job.mark_registered(99)
        assert job.db_id == 42
