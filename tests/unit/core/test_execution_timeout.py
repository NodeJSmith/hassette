"""Unit tests for timeout enforcement in track_execution and ExecutionResult."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import ExecutionStatus

from hassette.commands import ExecuteJob, InvokeHandler
from hassette.utils.execution import ExecutionResult, track_execution


def make_invoke_handler_kwargs(**overrides: object) -> dict[str, object]:
    """Shared base kwargs for constructing an InvokeHandler in the tests below — only
    `effective_timeout` (or its absence) varies per test.
    """
    kwargs: dict[str, object] = {
        "listener": MagicMock(),
        "event": MagicMock(),
        "topic": "test",
        "listener_id": 1,
        "source_tier": "app",
    }
    kwargs.update(overrides)
    return kwargs


class TestEffectiveTimeoutField:
    """effective_timeout is required on InvokeHandler and ExecuteJob (no default)."""

    def test_invoke_handler_requires_effective_timeout(self) -> None:
        """Omitting effective_timeout raises TypeError."""
        with pytest.raises(TypeError):
            InvokeHandler(**make_invoke_handler_kwargs())  # pyright: ignore[reportCallIssue]

    def test_invoke_handler_accepts_effective_timeout_none(self) -> None:
        """effective_timeout=None is valid (no timeout)."""
        cmd = InvokeHandler(**make_invoke_handler_kwargs(effective_timeout=None))
        assert cmd.effective_timeout is None

    def test_invoke_handler_accepts_effective_timeout_float(self) -> None:
        """effective_timeout=5.0 is valid."""
        cmd = InvokeHandler(**make_invoke_handler_kwargs(effective_timeout=5.0))
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


class TestTrackExecutionTimeout:
    """track_execution records 'timed_out' only when its own deadline expires."""

    async def test_track_execution_sets_timed_out_status(self) -> None:
        """An expired deadline sets status='timed_out' and propagates TimeoutError."""
        with pytest.raises(TimeoutError):
            async with track_execution(timeout=0.01) as result:
                await asyncio.sleep(10)

        assert result.status is ExecutionStatus.TIMED_OUT
        assert result.error_traceback is None

    @pytest.mark.parametrize("timeout", [None, 10.0], ids=["no_timeout", "unexpired_timeout"])
    async def test_body_raised_timeout_error_is_error(self, timeout: float | None) -> None:
        """A TimeoutError raised by the body itself is recorded as an error with a traceback."""
        with pytest.raises(TimeoutError):
            async with track_execution(timeout=timeout) as result:
                raise TimeoutError("upstream")

        assert result.status is ExecutionStatus.ERROR
        assert result.error_type == "TimeoutError"
        assert result.error_message == "upstream"
        assert result.error_traceback is not None


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
