"""Unit tests for trigger_mode threading through the scheduler execution pipeline.

Tests cover:
- run_job() passes trigger_mode through to the ExecuteJob command
- run_job() defaults trigger_mode to None (existing call sites unaffected)
- run_job_with_guard() threads trigger_mode through for PARALLEL mode (direct call)
- run_job_with_guard() threads trigger_mode through for non-parallel modes (invoke lambda)
- run_job_with_guard() defaults trigger_mode to None (existing call sites unaffected)
- trigger_job() finds a job on the live heap by db_id, or raises ValueError when absent
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.commands import ExecuteJob
from hassette.test_utils.web_helpers import make_real_job
from hassette.types.enums import ExecutionMode

from .conftest import make_scheduler_service


def _make_trigger_service():
    """Shared factory override: real-task spawn + AsyncMock adapter.

    Real-task spawn is needed because run_through_guard (SINGLE mode) spawns
    a task that calls invoke(), and run_job tests await spawned work.

    AsyncMock adapter is needed because make_real_job() uses a sync lambda
    (``lambda: None``); the shared factory's passthrough would fail on
    ``await sync_fn()``.
    """
    svc = make_scheduler_service()
    svc.task_bucket.spawn = lambda coro, **_kw: asyncio.get_running_loop().create_task(coro)
    svc.task_bucket.make_async_adapter = MagicMock(return_value=AsyncMock())
    return svc


class TestRunJobTriggerMode:
    async def test_run_job_passes_trigger_mode_to_execute_job(self) -> None:
        """run_job(trigger_mode='manual') threads through to ExecuteJob.trigger_mode."""
        svc = _make_trigger_service()
        job = make_real_job()

        await svc.run_job(job, trigger_mode="manual")

        svc._executor.execute.assert_called_once()
        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.trigger_mode == "manual"

    async def test_run_job_defaults_trigger_mode_to_none(self) -> None:
        """run_job() called without trigger_mode produces ExecuteJob.trigger_mode=None."""
        svc = _make_trigger_service()
        job = make_real_job()

        await svc.run_job(job)

        cmd = svc._executor.execute.call_args[0][0]
        assert cmd.trigger_mode is None


class TestRunJobWithGuardTriggerMode:
    """PARALLEL calls run_job(trigger_mode=...) directly; SINGLE captures trigger_mode in the
    invoke lambda passed to run_through_guard. Different internal paths, same observable result.
    """

    @pytest.mark.parametrize("mode", [ExecutionMode.PARALLEL, ExecutionMode.SINGLE])
    async def test_threads_trigger_mode(self, mode: ExecutionMode) -> None:
        """run_job_with_guard(trigger_mode='manual') threads through to run_job for both modes."""
        svc = _make_trigger_service()
        job = make_real_job(mode=mode)
        svc.run_job = AsyncMock()

        await svc.run_job_with_guard(job, trigger_mode="manual")

        svc.run_job.assert_called_once_with(job, trigger_mode="manual")

    @pytest.mark.parametrize("mode", [ExecutionMode.PARALLEL, ExecutionMode.SINGLE])
    async def test_defaults_trigger_mode_to_none(self, mode: ExecutionMode) -> None:
        """run_job_with_guard() without trigger_mode passes None through for both modes."""
        svc = _make_trigger_service()
        job = make_real_job(mode=mode)
        svc.run_job = AsyncMock()

        await svc.run_job_with_guard(job)

        svc.run_job.assert_called_once_with(job, trigger_mode=None)


class TestTriggerJob:
    async def test_returns_job_found_on_heap(self) -> None:
        """trigger_job() returns the ScheduledJob whose db_id matches on the live heap."""
        svc = _make_trigger_service()
        job = make_real_job(db_id=42)
        svc.get_all_jobs = AsyncMock(return_value=[job])

        result = await svc.trigger_job(42)

        assert result is job

    async def test_raises_value_error_for_missing_db_id(self) -> None:
        """trigger_job() raises ValueError when no job on the heap matches db_id."""
        svc = _make_trigger_service()
        other_job = make_real_job(db_id=1)
        svc.get_all_jobs = AsyncMock(return_value=[other_job])

        with pytest.raises(ValueError, match="not currently triggerable"):
            await svc.trigger_job(999)
