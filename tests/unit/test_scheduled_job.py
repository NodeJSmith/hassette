"""Tests for ScheduledJob dataclass — group, jitter, trigger_id matching."""

from whenever import ZonedDateTime

from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import Every
from hassette.utils.date_utils import now


def _make_job(
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


async def _noop() -> None:
    pass


class TestMatchesTriggerID:
    def test_matches_same_trigger_id(self) -> None:
        """Two jobs with Every(hours=1) triggers match regardless of object identity."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1))
        job2 = _make_job(job=_noop, trigger=Every(hours=1))
        # These are different object instances, but same trigger_id
        assert job1.trigger is not job2.trigger
        assert job1.matches(job2)

    def test_matches_different_trigger_id(self) -> None:
        """Every(hours=1) vs Every(hours=2) do not match."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1))
        job2 = _make_job(job=_noop, trigger=Every(hours=2))
        assert not job1.matches(job2)

    def test_matches_different_group(self) -> None:
        """Same callable, same trigger, but different group → no match."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1), group="morning")
        job2 = _make_job(job=_noop, trigger=Every(hours=1), group="evening")
        assert not job1.matches(job2)

    def test_matches_same_group(self) -> None:
        """Same callable, same trigger, same group → match."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1), group="morning")
        job2 = _make_job(job=_noop, trigger=Every(hours=1), group="morning")
        assert job1.matches(job2)

    def test_matches_no_trigger(self) -> None:
        """Two jobs with trigger=None compare by trigger identity (both None → match)."""
        job1 = _make_job(job=_noop, trigger=None)
        job2 = _make_job(job=_noop, trigger=None)
        assert job1.matches(job2)

    def test_matches_one_trigger_none_other_not(self) -> None:
        """One job with trigger, one without → no match."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1))
        job2 = _make_job(job=_noop, trigger=None)
        assert not job1.matches(job2)


class TestNewFields:
    def test_group_field_defaults_none(self) -> None:
        """Freshly constructed job has group=None."""
        job = _make_job()
        assert job.group is None

    def test_jitter_field_defaults_none(self) -> None:
        """Freshly constructed job has jitter=None."""
        job = _make_job()
        assert job.jitter is None

    def test_no_repeat_field(self) -> None:
        """ScheduledJob must not have a repeat attribute at runtime."""
        job = _make_job()
        assert not hasattr(job, "repeat")


class TestSetNextRun:
    def test_set_next_run_sort_index(self) -> None:
        """set_next_run() updates sort_index correctly."""
        job = _make_job()
        new_time = ZonedDateTime(2030, 1, 1, 12, 0, tz="UTC")
        job.set_next_run(new_time)
        assert job.next_run == new_time.round(unit="second")
        assert job.sort_index == (new_time.round(unit="second").timestamp_nanos(), job.job_id)


class TestFireAt:
    def test_fire_at_defaults_to_next_run_without_jitter(self) -> None:
        """Without jitter, fire_at == next_run exactly."""
        job = _make_job()
        assert job.fire_at == job.next_run

    def test_fire_at_equals_next_run_after_set_next_run(self) -> None:
        """set_next_run() updates both next_run and fire_at when no jitter."""
        job = _make_job()
        new_time = ZonedDateTime(2030, 1, 1, 12, 0, tz="UTC")
        job.set_next_run(new_time)
        assert job.fire_at == job.next_run


class TestMarkRegistered:
    def test_mark_registered_once(self) -> None:
        """Second call to mark_registered() with different db_id does not raise and ignores new value."""
        job = _make_job()
        job.mark_registered(42)
        assert job.db_id == 42

        # Second call with a different db_id — no exception, but db_id must not change
        job.mark_registered(99)
        assert job.db_id == 42  # still 42, new value ignored
