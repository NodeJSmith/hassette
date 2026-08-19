"""Tests for CommandExecutor._execute() source_tier branching and build_record()."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.commands import ExecuteJob
from hassette.core.command_executor import CommandExecutor
from hassette.core.execution_record import ExecutionRecord
from hassette.exceptions import DependencyError, HassetteError
from hassette.test_utils.factories import make_invoke_handler_cmd
from hassette.utils.execution import ExecutionResult

from .conftest import make_executor


def make_cmd_execute_job(source_tier: str, trigger_mode: str | None = None) -> MagicMock:
    """Build a minimal ExecuteJob-like mock."""
    cmd = MagicMock(spec=ExecuteJob)
    cmd.source_tier = source_tier
    cmd.job_db_id = 1
    cmd.callable = AsyncMock(return_value=None)
    cmd.effective_timeout = None
    cmd.trigger_mode = trigger_mode
    return cmd


async def run_execute(source_tier: str, exc: BaseException) -> ExecutionResult:
    """Run CommandExecutor._execute() against a handler that raises ``exc``, for the
    source_tier branching tests below — every occurrence shared the same executor/cmd/
    log_error/execution_id setup, differing only in source_tier and the raised exception.
    """
    executor = make_executor()
    cmd = make_invoke_handler_cmd(source_tier=source_tier)

    async def fn() -> None:
        raise exc

    def log_error(result: ExecutionResult) -> None:
        pass

    return await executor._execute(fn, cmd, log_error, "test-execution-id")


class TestCommandExecutorSourceTierBranching:
    """Verify match/case on source_tier controls traceback suppression."""

    async def test_app_tier_suppresses_known_error_traceback(self) -> None:
        """App-tier execution: DependencyError produces error_traceback=None."""
        result = await run_execute("app", DependencyError("missing dep"))

        assert result.status == "error"
        assert result.error_type == "DependencyError"
        # App tier: DependencyError is a known_error → traceback suppressed
        assert result.error_traceback is None

    async def test_app_tier_suppresses_hassette_error_traceback(self) -> None:
        """App-tier execution: HassetteError produces error_traceback=None."""
        result = await run_execute("app", HassetteError("framework error"))

        assert result.status == "error"
        assert result.error_traceback is None

    async def test_framework_tier_preserves_known_error_traceback(self) -> None:
        """Framework-tier execution: DependencyError preserves traceback."""
        result = await run_execute("framework", DependencyError("framework dep error"))

        assert result.status == "error"
        assert result.error_type == "DependencyError"
        # Framework tier: no known_errors → traceback preserved
        assert result.error_traceback is not None
        assert "DependencyError" in result.error_traceback

    async def test_framework_tier_preserves_hassette_error_traceback(self) -> None:
        """Framework-tier execution: HassetteError preserves traceback."""
        result = await run_execute("framework", HassetteError("internal framework error"))

        assert result.status == "error"
        assert result.error_traceback is not None

    async def test_unexpected_source_tier_raises(self) -> None:
        """Unexpected source_tier value raises AssertionError."""
        executor = make_executor()
        cmd = make_invoke_handler_cmd(source_tier="unknown_tier")

        async def fn() -> None:
            pass

        def log_error(result: ExecutionResult) -> None:
            pass

        with pytest.raises(AssertionError, match="Unexpected source_tier"):
            await executor._execute(fn, cmd, log_error, "test-execution-id")

    async def test_app_tier_unknown_exception_preserves_traceback(self) -> None:
        """App-tier unknown exceptions (not DependencyError/HassetteError) still get tracebacks."""
        result = await run_execute("app", RuntimeError("unexpected app error"))

        assert result.status == "error"
        assert result.error_type == "RuntimeError"
        assert result.error_traceback is not None
        assert "RuntimeError" in result.error_traceback


def make_result(
    *,
    status: str = "success",
    error_type: str | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
    is_di_failure: bool = False,
    thread_leaked: bool = False,
) -> ExecutionResult:
    """Build a minimal ExecutionResult for build_record() tests.

    Defaults describe a successful execution. Shared with test_command_executor_pipeline_persist.py's
    build_record tests via an in-group import — both files build the same result shape, differing
    only in which fields are overridden.
    """
    return ExecutionResult(
        duration_ms=1.0,
        status=status,
        error_type=error_type,
        error_message=error_message,
        error_traceback=error_traceback,
        is_di_failure=is_di_failure,
        thread_leaked=thread_leaked,
    )


class TestBuildRecordTriggerMode:
    """Verify build_record() reads ExecuteJob.trigger_mode onto ExecutionRecord."""

    @pytest.mark.parametrize(("trigger_mode", "expected"), [("manual", "manual"), (None, None)])
    def test_build_record_propagates_trigger_mode(self, trigger_mode: str | None, expected: str | None) -> None:
        """build_record reads cmd.trigger_mode onto ExecutionRecord.trigger_mode, including the
        None default for regular scheduled fires.
        """
        executor = make_executor()
        cmd = make_cmd_execute_job(source_tier="app", trigger_mode=trigger_mode)
        cmd.job = MagicMock()
        cmd.job.app_key = "test_app"
        cmd.job.instance_index = 0

        record = CommandExecutor.build_record(executor, cmd, make_result(), time.time(), "exec-id")

        assert isinstance(record, ExecutionRecord)
        assert record.kind == "job"
        assert record.trigger_mode == expected
