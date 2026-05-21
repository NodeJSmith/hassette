"""Tests for SchedulerService dispatch carrying app_level_error_handler on ExecuteJob (WP04)."""

from unittest.mock import AsyncMock, MagicMock

import hassette.utils.date_utils as date_utils
from hassette.core.commands import ExecuteJob
from hassette.core.scheduler_service import SchedulerService


def make_scheduler_service() -> SchedulerService:
    """Create a SchedulerService with mocked internals."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.scheduler.job_timeout_seconds = 30.0
    svc.hassette.config.logging.scheduler_service = "DEBUG"
    svc.hassette.config.scheduler.min_delay_seconds = 0.1
    svc.hassette.config.scheduler.max_delay_seconds = 60.0
    svc.hassette.config.scheduler.default_delay_seconds = 30.0
    svc.hassette.config.scheduler.behind_schedule_threshold_seconds = 30.0
    svc.logger = MagicMock()
    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    task_bucket.spawn = MagicMock(return_value=MagicMock(spec=["add_done_callback"]))
    svc.task_bucket = task_bucket

    return svc


def make_job(
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
    async def test_dispatch_carries_app_level_handler(self) -> None:
        """When job has an app_error_handler_resolver, its result is set on ExecuteJob."""
        svc = make_scheduler_service()

        async def app_handler(ctx) -> None:
            pass

        job = make_job(scheduler=MagicMock())
        job.app_error_handler_resolver = lambda: app_handler
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is app_handler

    async def test_dispatch_no_handler_when_resolver_returns_none(self) -> None:
        """When resolver returns None, app_level_error_handler is None."""
        svc = make_scheduler_service()

        job = make_job(scheduler=MagicMock())
        job.app_error_handler_resolver = lambda: None
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is None

    async def test_dispatch_no_handler_when_no_resolver(self) -> None:
        """When job has no app_error_handler_resolver, app_level_error_handler is None."""
        svc = make_scheduler_service()

        job = make_job(scheduler=None)
        job.app_error_handler_resolver = None
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is None
