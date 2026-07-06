"""Unit tests for trigger_mode threading through the scheduler execution pipeline.

Tests cover:
- run_job() passes trigger_mode through to the ExecuteJob command
- run_job() defaults trigger_mode to None (existing call sites unaffected)
- run_job_with_guard() threads trigger_mode through for PARALLEL mode (direct call)
- run_job_with_guard() threads trigger_mode through for non-parallel modes (invoke lambda)
- run_job_with_guard() defaults trigger_mode to None (existing call sites unaffected)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import hassette.utils.date_utils as date_utils
from hassette.commands import ExecuteJob
from hassette.core.scheduler_service import SchedulerService
from hassette.scheduler.classes import ScheduledJob
from hassette.types.enums import ExecutionMode


def make_scheduler_service() -> SchedulerService:
    """Create a SchedulerService with mocked internals, bypassing Resource.__init__."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.scheduler.behind_schedule_threshold_seconds = 60
    svc.hassette.config.scheduler.job_timeout_seconds = 30.0
    svc._removal_callbacks = {}
    svc.logger = MagicMock()
    svc._wakeup_event = asyncio.Event()

    svc._executor = MagicMock()
    svc._executor.execute = AsyncMock(return_value=None)

    svc.task_bucket = MagicMock()
    svc.task_bucket.make_async_adapter = MagicMock(return_value=AsyncMock())

    def _spawn(coro, **_kwargs):
        return asyncio.get_event_loop().create_task(coro)

    svc.task_bucket.spawn = _spawn

    return svc


def make_job(mode: ExecutionMode = ExecutionMode.SINGLE) -> ScheduledJob:
    """Create a minimal ScheduledJob for testing."""
    now = date_utils.now()
    return ScheduledJob(
        owner_id="test_owner",
        next_run=now,
        job=lambda: None,
        mode=mode,
    )


class TestRunJobTriggerMode:
    async def test_run_job_passes_trigger_mode_to_execute_job(self) -> None:
        """run_job(trigger_mode='manual') threads through to ExecuteJob.trigger_mode."""
        svc = make_scheduler_service()
        job = make_job()

        await svc.run_job(job, trigger_mode="manual")

        svc._executor.execute.assert_called_once()
        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.trigger_mode == "manual"

    async def test_run_job_defaults_trigger_mode_to_none(self) -> None:
        """run_job() called without trigger_mode produces ExecuteJob.trigger_mode=None."""
        svc = make_scheduler_service()
        job = make_job()

        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert cmd.trigger_mode is None


class TestRunJobWithGuardTriggerModeParallel:
    async def test_parallel_mode_threads_trigger_mode_directly(self) -> None:
        """PARALLEL mode: run_job_with_guard calls run_job(job, trigger_mode=trigger_mode) directly."""
        svc = make_scheduler_service()
        job = make_job(mode=ExecutionMode.PARALLEL)
        svc.run_job = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await svc.run_job_with_guard(job, trigger_mode="manual")

        svc.run_job.assert_called_once_with(job, trigger_mode="manual")

    async def test_parallel_mode_defaults_trigger_mode_to_none(self) -> None:
        """PARALLEL mode: run_job_with_guard() without trigger_mode passes None through."""
        svc = make_scheduler_service()
        job = make_job(mode=ExecutionMode.PARALLEL)
        svc.run_job = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await svc.run_job_with_guard(job)

        svc.run_job.assert_called_once_with(job, trigger_mode=None)


class TestRunJobWithGuardTriggerModeNonParallel:
    async def test_single_mode_threads_trigger_mode_via_invoke_lambda(self) -> None:
        """SINGLE mode: trigger_mode is captured in the invoke lambda passed to run_through_guard."""
        svc = make_scheduler_service()
        job = make_job(mode=ExecutionMode.SINGLE)
        svc.run_job = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await svc.run_job_with_guard(job, trigger_mode="manual")

        svc.run_job.assert_called_once_with(job, trigger_mode="manual")

    async def test_single_mode_defaults_trigger_mode_to_none(self) -> None:
        """SINGLE mode: run_job_with_guard() without trigger_mode passes None through."""
        svc = make_scheduler_service()
        job = make_job(mode=ExecutionMode.SINGLE)
        svc.run_job = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]

        await svc.run_job_with_guard(job)

        svc.run_job.assert_called_once_with(job, trigger_mode=None)
