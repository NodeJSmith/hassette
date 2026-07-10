"""Tests for SchedulerService dispatch carrying app_level_error_handler on ExecuteJob."""

from unittest.mock import AsyncMock, MagicMock

import hassette.utils.date_utils as date_utils
from hassette.commands import ExecuteJob

from .conftest import make_scheduler_service


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
        svc = make_scheduler_service(behind_schedule_threshold=30)

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
        svc = make_scheduler_service(behind_schedule_threshold=30)

        job = make_job(scheduler=MagicMock())
        job.app_error_handler_resolver = lambda: None
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is None

    async def test_dispatch_no_handler_when_no_resolver(self) -> None:
        """When job has no app_error_handler_resolver, app_level_error_handler is None."""
        svc = make_scheduler_service(behind_schedule_threshold=30)

        job = make_job(scheduler=None)
        job.app_error_handler_resolver = None
        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.app_level_error_handler is None
