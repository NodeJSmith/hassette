"""Unit tests for trigger_mode threading through the scheduler execution pipeline.

Tests cover:
- run_job() passes trigger_mode through to the ExecuteJob command
- run_job() defaults trigger_mode to None (existing call sites unaffected)
- run_job_with_guard() threads trigger_mode through for PARALLEL mode (direct call)
- run_job_with_guard() threads trigger_mode through for non-parallel modes (invoke lambda)
- run_job_with_guard() defaults trigger_mode to None (existing call sites unaffected)
- run_job_with_guard()/run_job() thread the dispatch-local fire_at fallback through
- trigger_job() finds a job in the live registry by db_id, or raises ValueError when absent
- submit_job() spawns a manual invocation for a live registered job across all execution modes
- submit_job() raises JobRemovedError for an unregistered or stale-handle job
- submit_job() bypasses the job's predicate and does not mutate its automatic schedule
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import hassette.utils.date_utils as date_utils
from hassette.commands import ExecuteJob
from hassette.exceptions import JobRemovedError
from hassette.test_utils.web_job_helpers import make_real_job
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

        svc.run_job.assert_called_once_with(job, trigger_mode="manual", fire_at=None)

    @pytest.mark.parametrize("mode", [ExecutionMode.PARALLEL, ExecutionMode.SINGLE])
    async def test_defaults_trigger_mode_to_none(self, mode: ExecutionMode) -> None:
        """run_job_with_guard() without trigger_mode passes None through for both modes."""
        svc = _make_trigger_service()
        job = make_real_job(mode=mode)
        svc.run_job = AsyncMock()

        await svc.run_job_with_guard(job)

        svc.run_job.assert_called_once_with(job, trigger_mode=None, fire_at=None)

    @pytest.mark.parametrize("mode", [ExecutionMode.PARALLEL, ExecutionMode.SINGLE])
    async def test_threads_fire_at(self, mode: ExecutionMode) -> None:
        """run_job_with_guard(fire_at=...) threads the dispatch-local fallback through to run_job."""
        svc = _make_trigger_service()
        job = make_real_job(mode=mode)
        svc.run_job = AsyncMock()
        local_fire_at = date_utils.now()

        await svc.run_job_with_guard(job, fire_at=local_fire_at)

        svc.run_job.assert_called_once_with(job, trigger_mode=None, fire_at=local_fire_at)


class TestTriggerJob:
    async def test_returns_job_found_in_registry(self) -> None:
        """trigger_job() returns the ScheduledJob whose db_id matches in the live registry."""
        svc = _make_trigger_service()
        job = make_real_job(db_id=42)
        svc.get_all_jobs = AsyncMock(return_value=[job])

        result = await svc.trigger_job(42)

        assert result is job

    async def test_raises_value_error_for_missing_db_id(self) -> None:
        """trigger_job() raises ValueError when no job in the registry matches db_id."""
        svc = _make_trigger_service()
        other_job = make_real_job(db_id=1)
        svc.get_all_jobs = AsyncMock(return_value=[other_job])

        with pytest.raises(ValueError, match="not currently triggerable"):
            await svc.trigger_job(999)


def _track_spawned_tasks(svc) -> list[asyncio.Task]:
    """Wrap ``svc.task_bucket.spawn`` to record every task it creates, in call order.

    ``run_through_guard`` (single/restart/queued) spawns a nested task through the same
    ``task_bucket``, so ``asyncio.sleep(0)`` is not enough to observe completion — the
    outer task (``run_job_with_guard``) only finishes once its nested invocation task does.
    Awaiting the first recorded task (the one ``submit_job()`` itself spawns) waits out the
    full chain deterministically, since ``run_through_guard`` awaits its own nested task
    before returning.
    """
    spawned: list[asyncio.Task] = []
    original_spawn = svc.task_bucket.spawn

    def _tracking_spawn(coro, **kwargs):
        task = original_spawn(coro, **kwargs)
        spawned.append(task)
        return task

    svc.task_bucket.spawn = _tracking_spawn
    return spawned


class TestSubmitJob:
    """submit_job() is a synchronous fire-and-observe entry point: identity-check the
    registry, spawn run_job_with_guard(trigger_mode="manual") on task_bucket, return None.
    """

    @pytest.mark.parametrize(
        "mode", [ExecutionMode.SINGLE, ExecutionMode.QUEUED, ExecutionMode.RESTART, ExecutionMode.PARALLEL]
    )
    async def test_submit_job_spawns_manual_invocation_for_every_mode(self, mode: ExecutionMode) -> None:
        """submit_job() spawns a manual invocation that reaches the executor for each mode."""
        svc = _make_trigger_service()
        job = make_real_job(mode=mode, db_id=7)
        svc._jobs_by_id[7] = job
        spawned = _track_spawned_tasks(svc)

        result = svc.submit_job(job)

        assert result is None, "submit_job() must return None synchronously"
        await asyncio.wait_for(spawned[0], timeout=1)

        svc._executor.execute.assert_called_once()
        cmd = svc._executor.execute.call_args[0][0]
        assert isinstance(cmd, ExecuteJob)
        assert cmd.trigger_mode == "manual", "manual submission must record trigger_mode='manual' telemetry"

    async def test_submit_job_raises_when_never_registered(self) -> None:
        """submit_job() raises JobRemovedError when the job has no db_id (never registered)."""
        svc = _make_trigger_service()
        job = make_real_job(db_id=None)

        with pytest.raises(JobRemovedError):
            svc.submit_job(job)

        svc._executor.execute.assert_not_called()

    async def test_submit_job_raises_for_stale_handle(self) -> None:
        """submit_job() raises JobRemovedError when the registry slot holds a different object.

        Simulates a crash-restart orphan: the caller's handle still names db_id=7, but the
        registry now maps 7 to a freshly re-registered Job with a different identity — the
        same scenario ``deregister_job()``'s identity check guards against.
        """
        svc = _make_trigger_service()
        stale_job = make_real_job(db_id=7, name="stale")
        fresh_job = make_real_job(db_id=7, name="fresh")
        svc._jobs_by_id[7] = fresh_job

        with pytest.raises(JobRemovedError):
            svc.submit_job(stale_job)

        svc._executor.execute.assert_not_called()

    async def test_submit_job_bypasses_predicate(self) -> None:
        """Manual submission never evaluates the job's predicate."""
        svc = _make_trigger_service()
        predicate = MagicMock(return_value=False)
        job = make_real_job(db_id=9, predicate=predicate)
        svc._jobs_by_id[9] = job
        spawned = _track_spawned_tasks(svc)

        svc.submit_job(job)
        await asyncio.wait_for(spawned[0], timeout=1)

        predicate.assert_not_called()
        svc._executor.execute.assert_called_once()

    async def test_submit_job_does_not_mutate_schedule(self) -> None:
        """Manual submission never changes the job's automatic schedule state."""
        svc = _make_trigger_service()
        job = make_real_job(db_id=11)
        svc._jobs_by_id[11] = job
        status_before = job.schedule_status
        next_run_before = job.next_run
        fire_at_before = job.fire_at
        spawned = _track_spawned_tasks(svc)

        svc.submit_job(job)
        await asyncio.wait_for(spawned[0], timeout=1)

        assert job.schedule_status == status_before
        assert job.next_run == next_run_before
        assert job.fire_at == fire_at_before
