"""Tests for timeout parameter threading through Scheduler public methods."""

from unittest.mock import patch

from hassette.scheduler.triggers import Every
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.helpers import noop

from .conftest import PATCH_TARGET, make_scheduler


class TestSchedulePassesTimeout:
    async def test_schedule_passes_timeout_to_job(self) -> None:
        """scheduler.schedule(fn, trigger, timeout=5.0) produces job with timeout=5.0."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "schedule(...)")):
            scheduler = make_scheduler()
            job = await scheduler.schedule(noop, Every(hours=1), timeout=5.0)
            assert job.timeout == 5.0
            assert job.timeout_disabled is False

    async def test_run_in_passes_timeout(self) -> None:
        """run_in() threads timeout through to the job."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "run_in(...)")):
            scheduler = make_scheduler()
            job = await scheduler.run_in(noop, 10, timeout=3.0)
            assert job.timeout == 3.0

    async def test_run_every_passes_timeout(self) -> None:
        """run_every() threads timeout through to the job."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "run_every(...)")):
            scheduler = make_scheduler()
            job = await scheduler.run_every(noop, hours=1, timeout=7.5)
            assert job.timeout == 7.5

    async def test_run_daily_passes_timeout_disabled(self) -> None:
        """run_daily() threads timeout_disabled=True through to the job."""
        with patch(PATCH_TARGET, return_value=(TEST_SOURCE_LOCATION, "run_daily(...)")):
            scheduler = make_scheduler()
            job = await scheduler.run_daily(noop, at="08:00", timeout_disabled=True)
            assert job.timeout_disabled is True
