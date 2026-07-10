"""Tests for ScheduledJob timeout/jitter/error_handler fields and matches()."""

import heapq
from typing import TYPE_CHECKING

import pytest

from hassette.scheduler.triggers import Every
from hassette.test_utils.factories import make_scheduled_job
from hassette.test_utils.helpers import noop

if TYPE_CHECKING:
    from hassette.scheduler.classes import ScheduledJob


class TestScheduledJobTimeoutFields:
    def test_scheduled_job_timeout_field_default(self) -> None:
        """Timeout defaults to None."""
        job = make_scheduled_job()
        assert job.timeout is None

    def test_scheduled_job_timeout_disabled_default(self) -> None:
        """timeout_disabled defaults to False."""
        job = make_scheduled_job()
        assert job.timeout_disabled is False

    def test_scheduled_job_timeout_validation_rejects_zero(self) -> None:
        """timeout=0 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            make_scheduled_job(timeout=0)

    def test_scheduled_job_timeout_validation_rejects_negative(self) -> None:
        """timeout=-1 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            make_scheduled_job(timeout=-1)


class TestMatchesTimeoutAndJitter:
    def test_matches_returns_false_when_timeout_differs(self) -> None:
        """Timeout change is detected by matches()."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), timeout=5.0)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), timeout=10.0)
        assert not job1.matches(job2)

    def test_matches_returns_false_when_jitter_differs(self) -> None:
        """Jitter change is detected by matches() — bug fix verification."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), jitter=1.0)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), jitter=5.0)
        assert not job1.matches(job2)

    def test_matches_returns_false_when_timeout_disabled_differs(self) -> None:
        """timeout_disabled change is detected by matches()."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), timeout_disabled=False)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), timeout_disabled=True)
        assert not job1.matches(job2)

    def test_matches_returns_true_when_all_fields_match(self) -> None:
        """All fields including timeout and jitter match → True."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), timeout=5.0, jitter=2.0, timeout_disabled=False)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), timeout=5.0, jitter=2.0, timeout_disabled=False)
        assert job1.matches(job2)


async def error_handler_a(ctx) -> None:
    pass


async def error_handler_b(ctx) -> None:
    pass


class TestScheduledJobErrorHandlerField:
    def test_error_handler_field_default_none(self) -> None:
        """error_handler defaults to None."""
        job = make_scheduled_job()
        assert job.error_handler is None

    def test_matches_with_same_error_handler(self) -> None:
        """matches() returns True when both jobs share the same error_handler (identity)."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_a)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_a)
        assert job1.matches(job2)

    def test_matches_with_different_error_handler(self) -> None:
        """matches() returns False when error_handler differs (identity check)."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_a)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_b)
        assert not job1.matches(job2)

    def test_diff_fields_includes_error_handler(self) -> None:
        """diff_fields() includes 'error_handler' when the handler differs."""
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_a)
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_b)
        changed = job1.diff_fields(job2)
        assert "error_handler" in changed

    def test_error_handler_compare_false_no_heap_corruption(self) -> None:
        """Heap push/pop with jobs bearing Callable error_handler does not raise TypeError.

        @dataclass(order=True) uses sort_index for ordering. error_handler must be
        compare=False to avoid trying to compare Callable objects, which raises TypeError.
        """
        job1 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_a, name="job1")
        job2 = make_scheduled_job(job=noop, trigger=Every(hours=1), error_handler=error_handler_b, name="job2")
        heap: list[ScheduledJob] = []
        # Must not raise TypeError — proves compare=False is in effect
        heapq.heappush(heap, job1)
        heapq.heappush(heap, job2)
        popped = heapq.heappop(heap)
        assert popped in (job1, job2)
