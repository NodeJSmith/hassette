"""Tests for timeout parameter threading through Scheduler public methods."""

from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import Every
from tests.support.helpers import noop


class TestSchedulePassesTimeout:
    async def test_schedule_passes_timeout_to_job(self, patched_scheduler: Scheduler) -> None:
        """scheduler.schedule(fn, trigger, timeout=5.0) produces job with timeout=5.0."""
        job = await patched_scheduler.schedule(
            noop, Every(hours=1), timeout=5.0, name="schedule_passes_timeout_to_job_schedule"
        )
        assert job.timeout == 5.0
        assert job.timeout_disabled is False

    async def test_run_in_passes_timeout(self, patched_scheduler: Scheduler) -> None:
        """run_in() threads timeout through to the job."""
        job = await patched_scheduler.run_in(noop, 10, timeout=3.0, name="run_in_passes_timeout_run_in")
        assert job.timeout == 3.0

    async def test_run_every_passes_timeout(self, patched_scheduler: Scheduler) -> None:
        """run_every() threads timeout through to the job."""
        job = await patched_scheduler.run_every(noop, hours=1, timeout=7.5, name="run_every_passes_timeout_run_every")
        assert job.timeout == 7.5

    async def test_run_daily_passes_timeout_disabled(self, patched_scheduler: Scheduler) -> None:
        """run_daily() threads timeout_disabled=True through to the job."""
        job = await patched_scheduler.run_daily(
            noop, at="08:00", timeout_disabled=True, name="run_daily_passes_timeout_disabled_run_daily"
        )
        assert job.timeout_disabled is True
