"""Unit tests for T01: mode parameter and ScheduledJob field-level behaviour.

Tests verify:
- ScheduledJob carries mode and guard fields (both compare=False)
- guard is created from mode in __post_init__
- mode and guard do not corrupt heap ordering
- matches() and diff_fields() include mode so if_exists="skip" detects mode changes
"""

import heapq

import hassette.utils.date_utils as date_utils
from hassette.execution_mode import ExecutionModeGuard
from hassette.scheduler.classes import ScheduledJob
from hassette.types.enums import ExecutionMode

# Helpers


def _make_raw_job(**kwargs) -> ScheduledJob:
    """Create a minimal ScheduledJob, bypassing the Scheduler."""
    return ScheduledJob(
        owner_id="test_owner",
        next_run=date_utils.now(),
        job=lambda: None,
        **kwargs,
    )


# ScheduledJob field-level tests (pure unit, no async needed)


class TestScheduledJobModeAndGuard:
    def test_default_mode_is_single(self) -> None:
        """ScheduledJob defaults to ExecutionMode.SINGLE so existing constructions are unbroken."""
        job = _make_raw_job()
        assert job.mode is ExecutionMode.SINGLE

    def test_guard_created_in_post_init(self) -> None:
        """guard is an ExecutionModeGuard created in __post_init__, not None."""
        job = _make_raw_job()
        assert isinstance(job.guard, ExecutionModeGuard)

    def test_guard_reflects_mode(self) -> None:
        """guard is created from the mode field."""
        job = _make_raw_job(mode=ExecutionMode.PARALLEL)
        assert job.mode is ExecutionMode.PARALLEL
        assert isinstance(job.guard, ExecutionModeGuard)

    def test_mode_does_not_affect_heap_ordering(self) -> None:
        """mode=compare=False: two jobs differing only in mode can coexist in a heap."""
        now = date_utils.now()
        job_single = ScheduledJob(owner_id="a", next_run=now, job=lambda: None, mode=ExecutionMode.SINGLE)
        job_parallel = ScheduledJob(owner_id="b", next_run=now, job=lambda: None, mode=ExecutionMode.PARALLEL)
        heap: list[ScheduledJob] = []
        heapq.heappush(heap, job_single)
        heapq.heappush(heap, job_parallel)  # must not raise TypeError

    def test_guard_does_not_affect_heap_ordering(self) -> None:
        """guard=compare=False: two jobs can coexist in a heap without guard comparison."""
        now = date_utils.now()
        job_a = ScheduledJob(owner_id="a", next_run=now, job=lambda: None)
        job_b = ScheduledJob(owner_id="b", next_run=now, job=lambda: None)
        heap: list[ScheduledJob] = []
        heapq.heappush(heap, job_a)
        heapq.heappush(heap, job_b)  # must not raise TypeError about ExecutionModeGuard comparison

    def test_explicit_mode_stored(self) -> None:
        """An explicitly passed mode is stored as-is."""
        for mode in ExecutionMode:
            job = _make_raw_job(mode=mode)
            assert job.mode is mode

    def test_guard_is_fresh_per_job(self) -> None:
        """Each ScheduledJob gets its own distinct ExecutionModeGuard instance."""
        job_a = _make_raw_job()
        job_b = _make_raw_job()
        assert job_a.guard is not job_b.guard

    def test_matches_includes_mode(self) -> None:
        """matches() returns False when mode differs — prevents if_exists='skip' ignoring mode changes."""
        fn = lambda: None  # noqa: E731
        job_single = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.SINGLE)
        job_parallel = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.PARALLEL)
        assert not job_single.matches(job_parallel)

    def test_matches_same_mode_returns_true(self) -> None:
        """matches() returns True when all fields including mode are identical."""
        fn = lambda: None  # noqa: E731
        job_a = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.QUEUED)
        job_b = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.QUEUED)
        assert job_a.matches(job_b)

    def test_diff_fields_includes_mode(self) -> None:
        """diff_fields() includes 'mode' when mode differs."""
        fn = lambda: None  # noqa: E731
        job_single = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.SINGLE)
        job_parallel = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.PARALLEL)
        diff = job_single.diff_fields(job_parallel)
        assert "mode" in diff

    def test_diff_fields_excludes_mode_when_same(self) -> None:
        """diff_fields() does not include 'mode' when mode is identical."""
        fn = lambda: None  # noqa: E731
        job_a = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.RESTART)
        job_b = ScheduledJob(owner_id="x", next_run=date_utils.now(), job=fn, mode=ExecutionMode.RESTART)
        diff = job_a.diff_fields(job_b)
        assert "mode" not in diff
