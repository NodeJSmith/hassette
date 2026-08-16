"""Tests for SchedulerService.run_job() effective timeout resolution."""

from unittest.mock import AsyncMock

from hassette.commands import ExecuteJob
from hassette.test_utils.factories import make_scheduled_job

from .conftest import make_scheduler_service


def get_executed_cmd(svc) -> ExecuteJob:
    """Return the ExecuteJob command dispatched via ``svc._executor.execute``.

    Shared across the scheduler_service test files (timeout, error_handler, trigger) that all
    assert on the same "run_job dispatched an ExecuteJob" shape. Kept local to this file rather
    than promoted to conftest.py, which is shared write-target scope across unrelated test
    groups (see design/specs/098-dedup-core-service-tests/design.md).
    """
    cmd = svc._executor.execute.call_args[0][0]
    assert isinstance(cmd, ExecuteJob)
    return cmd


class TestRunJobResolvesEffectiveTimeout:
    async def test_run_job_resolves_effective_timeout_from_job(self) -> None:
        """job.timeout=5 takes precedence over config default."""
        svc = make_scheduler_service(config_timeout=600.0)
        job = make_scheduled_job(timeout=5.0)

        await svc.run_job(job)

        cmd = get_executed_cmd(svc)
        assert cmd.effective_timeout == 5.0

    async def test_run_job_resolves_effective_timeout_from_config(self) -> None:
        """job.timeout=None falls through to config default."""
        svc = make_scheduler_service(config_timeout=600.0)
        job = make_scheduled_job(timeout=None)

        await svc.run_job(job)

        cmd = get_executed_cmd(svc)
        assert cmd.effective_timeout == 600.0

    async def test_run_job_resolves_timeout_disabled(self) -> None:
        """job.timeout_disabled=True sets effective_timeout=None."""
        svc = make_scheduler_service(config_timeout=600.0)
        job = make_scheduled_job(timeout_disabled=True)

        await svc.run_job(job)

        cmd = get_executed_cmd(svc)
        assert cmd.effective_timeout is None

    async def test_run_job_does_not_raise_on_timeout(self) -> None:
        """Timeout is absorbed by the executor — run_job() returns normally.

        In production, TimeoutError is caught inside CommandExecutor._execute()
        by track_execution. It never escapes execute().
        """
        svc = make_scheduler_service(config_timeout=0.001)
        job = make_scheduled_job(timeout=0.001)

        svc._executor.execute = AsyncMock()
        await svc.run_job(job)  # must not raise

        cmd = get_executed_cmd(svc)
        assert cmd.effective_timeout == 0.001
