"""Tests for SchedulerService dispatch carrying app_level_error_handler on ExecuteJob (WP04)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import hassette.utils.date_utils as date_utils
from hassette.core.commands import ExecuteJob
from hassette.core.scheduler_service import SchedulerService


def _make_scheduler_service() -> SchedulerService:
    """Create a SchedulerService with mocked internals."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.scheduler_job_timeout_seconds = 30.0
    svc.hassette.config.scheduler_service_log_level = "DEBUG"
    svc.hassette.config.scheduler_min_delay_seconds = 0.1
    svc.hassette.config.scheduler_max_delay_seconds = 60.0
    svc.hassette.config.scheduler_default_delay_seconds = 30.0
    svc.hassette.config.scheduler_behind_schedule_threshold_seconds = 30.0
    svc.logger = MagicMock()
    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    task_bucket.spawn = MagicMock(return_value=MagicMock(spec=["add_done_callback"]))
    svc.task_bucket = task_bucket

    return svc


def _make_job(
    *,
    error_handler=None,
    scheduler=None,
) -> MagicMock:
    """Build a minimal ScheduledJob-like mock."""
    job = MagicMock()
    job.name = "test_job"
    job.group = None
    job.args = ()
    job.kwargs = {}
    job.error_handler = error_handler
    job.timeout = None
    job.timeout_disabled = False
    job.db_id = 1
    job.source_tier = "app"
    job._scheduler = scheduler
    job._dequeued = False
    job.fire_at = date_utils.now()
    job.job = AsyncMock()
    return job


class TestSchedulerServiceCarriesAppLevelHandler:
    @pytest.mark.asyncio
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When job._scheduler has an _error_handler, it is set on ExecuteJob."""
        svc = _make_scheduler_service()

        async def app_handler(ctx) -> None:
            pass

        scheduler = MagicMock()
        scheduler._error_handler = app_handler

        job = _make_job(scheduler=scheduler)
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is app_handler

    @pytest.mark.asyncio
    async def test_dispatch_no_handler_when_scheduler_has_none(self) -> None:
        """When Scheduler._error_handler is None, app_level_error_handler is None."""
        svc = _make_scheduler_service()

        scheduler = MagicMock()
        scheduler._error_handler = None

        job = _make_job(scheduler=scheduler)
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is None

    @pytest.mark.asyncio
    async def test_dispatch_no_handler_when_no_scheduler_backref(self) -> None:
        """When job._scheduler is None (no back-reference), app_level_error_handler is None."""
        svc = _make_scheduler_service()

        job = _make_job(scheduler=None)
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is None
