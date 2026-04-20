"""Tests for ScheduledJob timeout fields and matches() with timeout/jitter."""

import pytest

from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import Every
from hassette.utils.date_utils import now


def _make_job(
    *,
    job=None,
    trigger=None,
    group: str | None = None,
    jitter: float | None = None,
    timeout: float | None = None,
    timeout_disabled: bool = False,
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
        timeout=timeout,
        timeout_disabled=timeout_disabled,
    )


async def _noop() -> None:
    pass


class TestScheduledJobTimeoutFields:
    def test_scheduled_job_timeout_field_default(self) -> None:
        """timeout defaults to None."""
        job = _make_job()
        assert job.timeout is None

    def test_scheduled_job_timeout_disabled_default(self) -> None:
        """timeout_disabled defaults to False."""
        job = _make_job()
        assert job.timeout_disabled is False

    def test_scheduled_job_timeout_validation_rejects_zero(self) -> None:
        """timeout=0 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            _make_job(timeout=0)

    def test_scheduled_job_timeout_validation_rejects_negative(self) -> None:
        """timeout=-1 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            _make_job(timeout=-1)


class TestMatchesTimeoutAndJitter:
    def test_matches_returns_false_when_timeout_differs(self) -> None:
        """Timeout change is detected by matches()."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1), timeout=5.0)
        job2 = _make_job(job=_noop, trigger=Every(hours=1), timeout=10.0)
        assert not job1.matches(job2)

    def test_matches_returns_false_when_jitter_differs(self) -> None:
        """Jitter change is detected by matches() — bug fix verification."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1), jitter=1.0)
        job2 = _make_job(job=_noop, trigger=Every(hours=1), jitter=5.0)
        assert not job1.matches(job2)

    def test_matches_returns_false_when_timeout_disabled_differs(self) -> None:
        """timeout_disabled change is detected by matches()."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1), timeout_disabled=False)
        job2 = _make_job(job=_noop, trigger=Every(hours=1), timeout_disabled=True)
        assert not job1.matches(job2)

    def test_matches_returns_true_when_all_fields_match(self) -> None:
        """All fields including timeout and jitter match → True."""
        job1 = _make_job(job=_noop, trigger=Every(hours=1), timeout=5.0, jitter=2.0, timeout_disabled=False)
        job2 = _make_job(job=_noop, trigger=Every(hours=1), timeout=5.0, jitter=2.0, timeout_disabled=False)
        assert job1.matches(job2)
