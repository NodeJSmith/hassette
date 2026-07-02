"""Shared fixtures for unit/scheduler tests."""

from unittest.mock import AsyncMock, MagicMock

from whenever import ZonedDateTime

from hassette.scheduler import Scheduler
from hassette.scheduler.classes import ScheduledJob

TZ = "America/Chicago"


def zdt(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> ZonedDateTime:
    return ZonedDateTime(year, month, day, hour, minute, second, tz=TZ)


async def noop() -> None:
    pass


def make_scheduler() -> Scheduler:
    """Create a Scheduler with a stubbed hassette and scheduler_service.

    scheduler_service.add_job is an AsyncMock that calls job.mark_registered(1)
    so tests see a valid db_id after await scheduler.schedule()/run_*() returns.
    """
    hassette = MagicMock()
    hassette.config.logging.scheduler_service = "INFO"
    scheduler = Scheduler.__new__(Scheduler)
    scheduler.hassette = hassette
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    mock_service = MagicMock()

    async def _add_job(job: ScheduledJob) -> None:
        job.mark_registered(1)

    mock_service.add_job = AsyncMock(side_effect=_add_job)
    scheduler.scheduler_service = mock_service
    scheduler._unique_name = "test_scheduler"
    scheduler._error_handler = None
    mock_parent = MagicMock()
    mock_parent.app_key = "test_app"
    mock_parent.index = 0
    mock_parent.source_tier = "app"
    mock_parent.class_name = "TestParent"
    scheduler.parent = mock_parent
    return scheduler
