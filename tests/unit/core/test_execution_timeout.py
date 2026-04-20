"""Unit tests for timeout enforcement in track_execution and ExecutionResult."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.utils.execution import ExecutionResult, track_execution

# ---------------------------------------------------------------------------
# Subtask 1: effective_timeout field on command dataclasses
# ---------------------------------------------------------------------------


class TestEffectiveTimeoutField:
    """effective_timeout is required on InvokeHandler and ExecuteJob (no default)."""

    def test_invoke_handler_requires_effective_timeout(self) -> None:
        """Omitting effective_timeout raises TypeError."""
        with pytest.raises(TypeError):
            InvokeHandler(  # pyright: ignore[reportCallIssue]
                listener=MagicMock(),
                event=MagicMock(),
                topic="test",
                listener_id=1,
                source_tier="app",
            )

    def test_invoke_handler_accepts_effective_timeout_none(self) -> None:
        """effective_timeout=None is valid (no timeout)."""
        cmd = InvokeHandler(
            listener=MagicMock(),
            event=MagicMock(),
            topic="test",
            listener_id=1,
            source_tier="app",
            effective_timeout=None,
        )
        assert cmd.effective_timeout is None

    def test_invoke_handler_accepts_effective_timeout_float(self) -> None:
        """effective_timeout=5.0 is valid."""
        cmd = InvokeHandler(
            listener=MagicMock(),
            event=MagicMock(),
            topic="test",
            listener_id=1,
            source_tier="app",
            effective_timeout=5.0,
        )
        assert cmd.effective_timeout == 5.0

    def test_execute_job_requires_effective_timeout(self) -> None:
        """Omitting effective_timeout raises TypeError."""
        with pytest.raises(TypeError):
            ExecuteJob(  # pyright: ignore[reportCallIssue]
                job=MagicMock(),
                callable=AsyncMock(),
                job_db_id=1,
                source_tier="app",
            )

    def test_execute_job_accepts_effective_timeout_none(self) -> None:
        """effective_timeout=None is valid (no timeout)."""
        cmd = ExecuteJob(
            job=MagicMock(),
            callable=AsyncMock(),
            job_db_id=1,
            source_tier="app",
            effective_timeout=None,
        )
        assert cmd.effective_timeout is None


# ---------------------------------------------------------------------------
# Subtask 2: track_execution TimeoutError handling and is_timed_out property
# ---------------------------------------------------------------------------


class TestTrackExecutionTimeout:
    """track_execution sets status='timed_out' on TimeoutError and re-raises."""

    @pytest.mark.asyncio
    async def test_track_execution_sets_timed_out_status(self) -> None:
        """TimeoutError sets status='timed_out' and propagates."""
        with pytest.raises(TimeoutError):
            async with track_execution() as result:
                raise TimeoutError("timed out")

        assert result.status == "timed_out"


class TestExecutionResultIsTimedOut:
    """is_timed_out property on ExecutionResult."""

    def test_execution_result_is_timed_out(self) -> None:
        """is_timed_out returns True for 'timed_out' status."""
        result = ExecutionResult()
        result.status = "timed_out"
        assert result.is_timed_out is True

    def test_execution_result_is_timed_out_false_for_error(self) -> None:
        """is_timed_out returns False for 'error' status."""
        result = ExecutionResult()
        result.status = "error"
        assert result.is_timed_out is False

    def test_execution_result_is_timed_out_false_for_success(self) -> None:
        """is_timed_out returns False for 'success' status."""
        result = ExecutionResult()
        result.status = "success"
        assert result.is_timed_out is False
