"""Tests for SchedulerService.run_job() effective timeout resolution."""

from typing import Any
from unittest.mock import AsyncMock

from hassette.commands import ExecuteJob
from hassette.core.scheduler_service import SchedulerService
from hassette.testing.config import TEST_CONFIG_TIMEOUT_SECONDS
from tests.support.factories import make_scheduled_job

from .conftest import make_scheduler_service


async def run_job_and_get_cmd(svc: SchedulerService, job: Any, **run_job_kwargs: Any) -> ExecuteJob:
    """Run ``svc.run_job(job, ...)`` and return the ExecuteJob it dispatched via ``svc._executor.execute``.

    Shared across the scheduler_service test files (timeout, error_handler, trigger) that all
    assert on the same "run_job dispatched an ExecuteJob" shape. Named to match the fire-then-extract
    helpers covering the same pattern elsewhere — ``invoke_and_get_cmd`` in
    tests/unit/bus/test_invocation.py and ``execute_handler_and_get_record`` in
    test_command_executor_execution_id.py. Kept local to this file rather than promoted to
    conftest.py, which is shared write-target scope across unrelated test groups (see
    design/specs/098-dedup-core-service-tests/design.md).
    """
    await svc.run_job(job, **run_job_kwargs)

    cmd = svc._executor.execute.call_args[0][0]
    assert isinstance(cmd, ExecuteJob)
    return cmd


class TestRunJobResolvesEffectiveTimeout:
    async def test_run_job_resolves_effective_timeout_from_job(self) -> None:
        """job.timeout=5 takes precedence over config default."""
        svc = make_scheduler_service(config_timeout=TEST_CONFIG_TIMEOUT_SECONDS)
        job = make_scheduled_job(timeout=5.0)

        cmd = await run_job_and_get_cmd(svc, job)

        assert cmd.effective_timeout == 5.0

    async def test_run_job_resolves_effective_timeout_from_config(self) -> None:
        """job.timeout=None falls through to config default."""
        svc = make_scheduler_service(config_timeout=TEST_CONFIG_TIMEOUT_SECONDS)
        job = make_scheduled_job(timeout=None)

        cmd = await run_job_and_get_cmd(svc, job)

        assert cmd.effective_timeout == TEST_CONFIG_TIMEOUT_SECONDS

    async def test_run_job_resolves_timeout_disabled(self) -> None:
        """job.timeout_disabled=True sets effective_timeout=None."""
        svc = make_scheduler_service(config_timeout=TEST_CONFIG_TIMEOUT_SECONDS)
        job = make_scheduled_job(timeout_disabled=True)

        cmd = await run_job_and_get_cmd(svc, job)

        assert cmd.effective_timeout is None

    async def test_run_job_does_not_raise_on_timeout(self) -> None:
        """Timeout is absorbed by the executor — run_job() returns normally.

        In production, TimeoutError is caught inside CommandExecutor._execute()
        by track_execution. It never escapes execute().
        """
        svc = make_scheduler_service(config_timeout=0.001)
        job = make_scheduled_job(timeout=0.001)

        svc._executor.execute = AsyncMock()
        cmd = await run_job_and_get_cmd(svc, job)  # the run_job() call inside must not raise

        assert cmd.effective_timeout == 0.001
