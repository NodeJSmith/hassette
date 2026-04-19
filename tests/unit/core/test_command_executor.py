"""Tests for CommandExecutor._execute() source_tier branching."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.exceptions import DependencyError, HassetteError
from hassette.utils.execution import ExecutionResult


def _make_cmd_invoke_handler(source_tier: str) -> MagicMock:
    """Build a minimal InvokeHandler-like mock."""
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = source_tier
    cmd.listener_id = 1
    cmd.topic = "test/topic"
    cmd.listener = MagicMock()
    cmd.listener.invoke = AsyncMock(return_value=None)
    return cmd


def _make_cmd_execute_job(source_tier: str) -> MagicMock:
    """Build a minimal ExecuteJob-like mock."""
    cmd = MagicMock(spec=ExecuteJob)
    cmd.source_tier = source_tier
    cmd.job_db_id = 1
    cmd.callable = AsyncMock(return_value=None)
    return cmd


def _make_executor() -> CommandExecutor:
    """Build a CommandExecutor with all dependencies mocked out."""
    hassette = MagicMock()
    hassette.config.telemetry_write_queue_max = 1000
    hassette.config.command_executor_log_level = "DEBUG"
    hassette.database_service = MagicMock()
    hassette.session_id = 42
    executor = CommandExecutor.__new__(CommandExecutor)
    executor._write_queue = asyncio.Queue(maxsize=1000)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._dropped_no_session = 0
    executor._dropped_shutdown = 0
    executor._last_capacity_warn_ts = 0.0
    executor.repository = MagicMock()
    executor.hassette = hassette
    executor._logger = MagicMock()
    return executor


class TestCommandExecutorSourceTierBranching:
    """Verify match/case on source_tier controls traceback suppression."""

    async def test_app_tier_suppresses_known_error_traceback(self) -> None:
        """App-tier execution: DependencyError produces error_traceback=None."""
        executor = _make_executor()
        cmd = _make_cmd_invoke_handler(source_tier="app")

        async def fn() -> None:
            raise DependencyError("missing dep")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error)

        assert result.status == "error"
        assert result.error_type == "DependencyError"
        # App tier: DependencyError is a known_error → traceback suppressed
        assert result.error_traceback is None

    async def test_app_tier_suppresses_hassette_error_traceback(self) -> None:
        """App-tier execution: HassetteError produces error_traceback=None."""
        executor = _make_executor()
        cmd = _make_cmd_invoke_handler(source_tier="app")

        async def fn() -> None:
            raise HassetteError("framework error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error)

        assert result.status == "error"
        assert result.error_traceback is None

    async def test_framework_tier_preserves_known_error_traceback(self) -> None:
        """Framework-tier execution: DependencyError preserves traceback."""
        executor = _make_executor()
        cmd = _make_cmd_invoke_handler(source_tier="framework")

        async def fn() -> None:
            raise DependencyError("framework dep error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error)

        assert result.status == "error"
        assert result.error_type == "DependencyError"
        # Framework tier: no known_errors → traceback preserved
        assert result.error_traceback is not None
        assert "DependencyError" in result.error_traceback

    async def test_framework_tier_preserves_hassette_error_traceback(self) -> None:
        """Framework-tier execution: HassetteError preserves traceback."""
        executor = _make_executor()
        cmd = _make_cmd_invoke_handler(source_tier="framework")

        async def fn() -> None:
            raise HassetteError("internal framework error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error)

        assert result.status == "error"
        assert result.error_traceback is not None

    async def test_unexpected_source_tier_raises(self) -> None:
        """Unexpected source_tier value raises AssertionError."""
        executor = _make_executor()
        cmd = _make_cmd_invoke_handler(source_tier="unknown_tier")

        async def fn() -> None:
            pass

        def log_error(result: ExecutionResult) -> None:
            pass

        with pytest.raises(AssertionError, match="Unexpected source_tier"):
            await executor._execute(fn, cmd, log_error)

    async def test_app_tier_unknown_exception_preserves_traceback(self) -> None:
        """App-tier unknown exceptions (not DependencyError/HassetteError) still get tracebacks."""
        executor = _make_executor()
        cmd = _make_cmd_invoke_handler(source_tier="app")

        async def fn() -> None:
            raise RuntimeError("unexpected app error")

        def log_error(result: ExecutionResult) -> None:
            pass

        result = await executor._execute(fn, cmd, log_error)

        assert result.status == "error"
        assert result.error_type == "RuntimeError"
        assert result.error_traceback is not None
        assert "RuntimeError" in result.error_traceback
