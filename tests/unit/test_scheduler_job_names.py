"""Tests for Scheduler job name uniqueness validation."""

from collections.abc import Callable
from unittest.mock import Mock

import pytest

from hassette.scheduler.classes import IntervalTrigger, ScheduledJob
from hassette.scheduler.scheduler import Scheduler
from hassette.utils.date_utils import now


def _make_scheduler() -> Scheduler:
    """Create a minimal Scheduler instance with mocked internals."""
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.scheduler_service = Mock()
    scheduler._jobs_by_name = {}
    # owner_id is a property on Resource that reads parent.unique_name
    type(scheduler).owner_id = property(lambda _self: "test_owner")
    return scheduler


def _make_job(
    name: str = "",
    *,
    job: Callable[..., None] | None = None,
    trigger: IntervalTrigger | None = None,
    repeat: bool = False,
) -> ScheduledJob:
    """Create a minimal ScheduledJob."""
    return ScheduledJob(
        owner="test_owner",
        next_run=now(),
        job=job or (lambda: None),
        name=name,
        trigger=trigger,
        repeat=repeat,
    )


class TestJobNameUniqueness:
    def test_duplicate_name_raises(self) -> None:
        scheduler = _make_scheduler()
        scheduler.add_job(_make_job("daily_backup"))

        with pytest.raises(ValueError, match="daily_backup"):
            scheduler.add_job(_make_job("daily_backup"))

    def test_different_names_ok(self) -> None:
        scheduler = _make_scheduler()
        scheduler.add_job(_make_job("job_a"))
        scheduler.add_job(_make_job("job_b"))

        assert set(scheduler._jobs_by_name) == {"job_a", "job_b"}

    def test_auto_named_jobs_also_enforce_uniqueness(self) -> None:
        """Jobs with auto-derived names (from callable) are still subject to uniqueness checks."""
        scheduler = _make_scheduler()
        # Both jobs use lambda, so __post_init__ auto-names them "<lambda>".
        job1 = _make_job("")
        job2 = _make_job("")

        scheduler.add_job(job1)

        with pytest.raises(ValueError, match="<lambda>"):
            scheduler.add_job(job2)

    def test_removal_allows_reuse(self) -> None:
        scheduler = _make_scheduler()
        job = _make_job("ephemeral")
        scheduler.add_job(job)
        assert "ephemeral" in scheduler._jobs_by_name

        scheduler.remove_job(job)
        assert "ephemeral" not in scheduler._jobs_by_name

        # Re-adding with the same name should now succeed
        scheduler.add_job(_make_job("ephemeral"))
        assert "ephemeral" in scheduler._jobs_by_name

    def test_remove_all_clears_names(self) -> None:
        scheduler = _make_scheduler()
        scheduler.add_job(_make_job("a"))
        scheduler.add_job(_make_job("b"))
        assert set(scheduler._jobs_by_name) == {"a", "b"}

        scheduler.remove_all_jobs()
        assert scheduler._jobs_by_name == {}


class TestIfExistsSkip:
    def test_skip_returns_existing_when_matching(self) -> None:
        """if_exists='skip' returns the existing job when everything matches."""
        scheduler = _make_scheduler()
        fn = lambda: None  # noqa: E731
        job1 = _make_job("poll", job=fn)
        added = scheduler.add_job(job1)

        job2 = _make_job("poll", job=fn)
        result = scheduler.add_job(job2, if_exists="skip")

        assert result is added

    def test_skip_raises_when_config_differs(self) -> None:
        """if_exists='skip' still raises when the name matches but config differs."""
        scheduler = _make_scheduler()
        fn_a = lambda: None  # noqa: E731
        fn_b = lambda: None  # noqa: E731
        scheduler.add_job(_make_job("poll", job=fn_a))

        with pytest.raises(ValueError, match="poll"):
            scheduler.add_job(_make_job("poll", job=fn_b), if_exists="skip")

    def test_skip_checks_trigger_equality(self) -> None:
        """if_exists='skip' considers trigger type and value."""
        scheduler = _make_scheduler()
        fn = lambda: None  # noqa: E731
        trigger_30s = IntervalTrigger.from_arguments(seconds=30)
        trigger_60s = IntervalTrigger.from_arguments(seconds=60)

        scheduler.add_job(_make_job("poll", job=fn, trigger=trigger_30s, repeat=True))

        # Same trigger config → skip
        same_trigger = IntervalTrigger.from_arguments(seconds=30)
        result = scheduler.add_job(_make_job("poll", job=fn, trigger=same_trigger, repeat=True), if_exists="skip")
        assert result is scheduler._jobs_by_name["poll"]

        # Different trigger config → error
        with pytest.raises(ValueError, match="poll"):
            scheduler.add_job(_make_job("poll", job=fn, trigger=trigger_60s, repeat=True), if_exists="skip")

    def test_error_mode_always_raises_on_duplicate(self) -> None:
        """Default if_exists='error' raises even when config matches."""
        scheduler = _make_scheduler()
        fn = lambda: None  # noqa: E731
        scheduler.add_job(_make_job("poll", job=fn))

        with pytest.raises(ValueError, match="poll"):
            scheduler.add_job(_make_job("poll", job=fn))
