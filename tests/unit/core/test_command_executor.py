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


class TestCommandExecutorSourceTierBranching:
    """Verify match/case on source_tier controls traceback suppression."""

    async def test_app_tier_suppresses_known_error_traceback(self) -> None:
        """App-tier execution: DependencyError produces error_traceback=None."""
        executor = make_executor()
        cmd = make_invoke_handler_cmd(source_tier="app")

        async def fn() -> None:
            raise DependencyError("missing dep")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error, "test-execution-id")

        assert result.status == "error"
        assert result.error_type == "DependencyError"
        # App tier: DependencyError is a known_error → traceback suppressed
        assert result.error_traceback is None

    async def test_app_tier_suppresses_hassette_error_traceback(self) -> None:
        """App-tier execution: HassetteError produces error_traceback=None."""
        executor = make_executor()
        cmd = make_invoke_handler_cmd(source_tier="app")

        async def fn() -> None:
            raise HassetteError("framework error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error, "test-execution-id")

        assert result.status == "error"
        assert result.error_traceback is None

    async def test_framework_tier_preserves_known_error_traceback(self) -> None:
        """Framework-tier execution: DependencyError preserves traceback."""
        executor = make_executor()
        cmd = make_invoke_handler_cmd(source_tier="framework")

        async def fn() -> None:
            raise DependencyError("framework dep error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error, "test-execution-id")

        assert result.status == "error"
        assert result.error_type == "DependencyError"
        # Framework tier: no known_errors → traceback preserved
        assert result.error_traceback is not None
        assert "DependencyError" in result.error_traceback

    async def test_framework_tier_preserves_hassette_error_traceback(self) -> None:
        """Framework-tier execution: HassetteError preserves traceback."""
        executor = make_executor()
        cmd = make_invoke_handler_cmd(source_tier="framework")

        async def fn() -> None:
            raise HassetteError("internal framework error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error, "test-execution-id")

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
        executor = make_executor()
        cmd = make_invoke_handler_cmd(source_tier="app")

        async def fn() -> None:
            raise RuntimeError("unexpected app error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error, "test-execution-id")

        assert result.status == "error"
        assert result.error_type == "RuntimeError"
        assert result.error_traceback is not None
        assert "RuntimeError" in result.error_traceback


class TestBuildRecordTriggerMode:
    """Verify build_record() reads ExecuteJob.trigger_mode onto ExecutionRecord."""

    def test_build_record_reads_trigger_mode(self) -> None:
        """build_record sets trigger_mode='manual' from cmd.trigger_mode for ExecuteJob."""
        executor = make_executor()
        cmd = make_cmd_execute_job(source_tier="app", trigger_mode="manual")
        cmd.job = MagicMock()
        cmd.job.app_key = "test_app"
        cmd.job.instance_index = 0

        result = MagicMock()
        result.duration_ms = 1.0
        result.status = "success"
        result.error_type = None
        result.error_message = None
        result.error_traceback = None
        result.is_di_failure = False
        result.thread_leaked = False

        record = CommandExecutor.build_record(executor, cmd, result, time.time(), "exec-id")

        assert isinstance(record, ExecutionRecord)
        assert record.kind == "job"
        assert record.trigger_mode == "manual"

    def test_build_record_defaults_trigger_mode_to_none(self) -> None:
        """build_record leaves trigger_mode=None when cmd.trigger_mode is None (scheduled fire)."""
        executor = make_executor()
        cmd = make_cmd_execute_job(source_tier="app", trigger_mode=None)
        cmd.job = MagicMock()
        cmd.job.app_key = "test_app"
        cmd.job.instance_index = 0

        result = MagicMock()
        result.duration_ms = 1.0
        result.status = "success"
        result.error_type = None
        result.error_message = None
        result.error_traceback = None
        result.is_di_failure = False
        result.thread_leaked = False

        record = CommandExecutor.build_record(executor, cmd, result, time.time(), "exec-id-2")

        assert record.trigger_mode is None
