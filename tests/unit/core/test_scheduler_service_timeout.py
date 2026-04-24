"""Tests for SchedulerService.run_job() effective timeout resolution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import hassette.utils.date_utils as date_utils
from hassette.core.commands import ExecuteJob
from hassette.core.registration_tracker import RegistrationTracker
from hassette.core.scheduler_service import SchedulerService
from hassette.scheduler.classes import ScheduledJob


def _make_scheduler_service(*, config_timeout: float | None = 600.0) -> SchedulerService:
    """Create a SchedulerService with mocked internals, bypassing Resource.__init__."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.scheduler_behind_schedule_threshold_seconds = 60
    svc.hassette.config.scheduler_job_timeout_seconds = config_timeout
    svc.hassette.config.registration_await_timeout = 30
    svc._reg_tracker = RegistrationTracker()
    svc._removal_callbacks = {}
    svc.logger = MagicMock()

    # Minimal job queue mock
    svc._job_queue = MagicMock()
    svc._job_queue.add = AsyncMock(return_value=None)
    svc._job_queue.remove_job = AsyncMock(return_value=True)

    # kick() is called after enqueue/remove
    svc._wakeup_event = asyncio.Event()

    # Mock the task_bucket for make_async_adapter
    svc.task_bucket = MagicMock()
    svc.task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    # Mock the executor
    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock()

    return svc


def _make_job(
    *,
    timeout: float | None = None,
    timeout_disabled: bool = False,
    trigger=None,
) -> ScheduledJob:
    """Create a minimal ScheduledJob for testing."""
    now = date_utils.now()
    return ScheduledJob(
        owner_id="test_owner",
        next_run=now,
        job=AsyncMock(),
        trigger=trigger,
        timeout=timeout,
        timeout_disabled=timeout_disabled,
    )


class TestRunJobResolvesEffectiveTimeout:
    async def test_run_job_resolves_effective_timeout_from_job(self) -> None:
        """job.timeout=5 takes precedence over config default."""
        svc = _make_scheduler_service(config_timeout=600.0)
        job = _make_job(timeout=5.0)

        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.effective_timeout == 5.0

    async def test_run_job_resolves_effective_timeout_from_config(self) -> None:
        """job.timeout=None falls through to config default."""
        svc = _make_scheduler_service(config_timeout=600.0)
        job = _make_job(timeout=None)

        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.effective_timeout == 600.0

    async def test_run_job_resolves_timeout_disabled(self) -> None:
        """job.timeout_disabled=True sets effective_timeout=None."""
        svc = _make_scheduler_service(config_timeout=600.0)
        job = _make_job(timeout_disabled=True)

        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.effective_timeout is None

    async def test_run_job_does_not_raise_on_timeout(self) -> None:
        """Timeout is absorbed by the executor — run_job() returns normally.

        In production, TimeoutError is caught inside CommandExecutor._execute()
        by track_execution. It never escapes execute().
        """
        svc = _make_scheduler_service(config_timeout=0.001)
        job = _make_job(timeout=0.001)

        svc._executor.execute = AsyncMock()
        await svc.run_job(job)  # must not raise

        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.effective_timeout == 0.001
