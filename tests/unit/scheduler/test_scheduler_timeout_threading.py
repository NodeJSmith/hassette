"""Tests for timeout parameter threading through Scheduler public methods."""

from unittest.mock import MagicMock, patch

from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.triggers import Every


def _make_scheduler() -> Scheduler:
    """Create a Scheduler with a stubbed hassette and scheduler_service."""

    hassette = MagicMock()
    hassette.config.scheduler_service_log_level = "INFO"
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.hassette = hassette
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    scheduler.scheduler_service = MagicMock()
    scheduler._unique_name = "test_scheduler"
    mock_parent = MagicMock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestParent"
    scheduler.parent = mock_parent
    return scheduler


async def _noop() -> None:
    pass


_PATCH_TARGET = "hassette.scheduler.scheduler.capture_registration_source"


class TestSchedulePassesTimeout:
    def test_schedule_passes_timeout_to_job(self) -> None:
        """scheduler.schedule(fn, trigger, timeout=5.0) produces job with timeout=5.0."""
        with patch(_PATCH_TARGET, return_value=("test.py:1", "schedule(...)")):
            scheduler = _make_scheduler()
            job = scheduler.schedule(_noop, Every(hours=1), timeout=5.0)
            assert job.timeout == 5.0
            assert job.timeout_disabled is False

    def test_run_in_passes_timeout(self) -> None:
        """run_in() threads timeout through to the job."""
        with patch(_PATCH_TARGET, return_value=("test.py:1", "run_in(...)")):
            scheduler = _make_scheduler()
            job = scheduler.run_in(_noop, 10, timeout=3.0)
            assert job.timeout == 3.0

    def test_run_every_passes_timeout(self) -> None:
        """run_every() threads timeout through to the job."""
        with patch(_PATCH_TARGET, return_value=("test.py:1", "run_every(...)")):
            scheduler = _make_scheduler()
            job = scheduler.run_every(_noop, hours=1, timeout=7.5)
            assert job.timeout == 7.5

    def test_run_daily_passes_timeout_disabled(self) -> None:
        """run_daily() threads timeout_disabled=True through to the job."""
        with patch(_PATCH_TARGET, return_value=("test.py:1", "run_daily(...)")):
            scheduler = _make_scheduler()
            job = scheduler.run_daily(_noop, at="08:00", timeout_disabled=True)
            assert job.timeout_disabled is True
