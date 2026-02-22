"""Tests for the track_execution() async context manager."""

import asyncio

import pytest

from hassette.utils.execution import ExecutionResult, track_execution


class TestExecutionResult:
    def test_defaults(self) -> None:
        result = ExecutionResult()
        assert result.status == "pending"
        assert result.duration_ms == 0.0
        assert result.error_message is None
        assert result.error_type is None
        assert result.monotonic_start == 0.0

    def test_is_success(self) -> None:
        result = ExecutionResult(status="success")
        assert result.is_success is True

    def test_is_error(self) -> None:
        result = ExecutionResult(status="error")
        assert result.is_error is True

    def test_is_cancelled(self) -> None:
        result = ExecutionResult(status="cancelled")
        assert result.is_cancelled is True


class TestTrackExecution:
    async def test_success_path(self) -> None:
        async with track_execution() as result:
            pass  # no error

        assert result.status == "success"
        assert result.duration_ms >= 0.0
        assert result.monotonic_start > 0.0
        assert result.error_message is None
        assert result.error_type is None

    async def test_error_path(self) -> None:
        with pytest.raises(ValueError, match="boom"):
            async with track_execution() as result:
                raise ValueError("boom")

        assert result.status == "error"
        assert result.error_message == "boom"
        assert result.error_type == "ValueError"
        assert result.duration_ms >= 0.0

    async def test_cancelled_path(self) -> None:
        with pytest.raises(asyncio.CancelledError):
            async with track_execution() as result:
                raise asyncio.CancelledError()

        assert result.status == "cancelled"
        assert result.duration_ms >= 0.0

    async def test_always_reraises(self) -> None:
        with pytest.raises(RuntimeError):
            async with track_execution() as result:
                raise RuntimeError("fail")

        assert result.status == "error"

    async def test_timing_is_reasonable(self) -> None:
        async with track_execution() as result:
            await asyncio.sleep(0.05)

        # Should be at least 50ms but less than 500ms
        assert result.duration_ms >= 40.0
        assert result.duration_ms < 500.0

    async def test_monotonic_start_is_set(self) -> None:
        async with track_execution() as result:
            pass

        assert result.monotonic_start > 0.0

    async def test_hassette_error_subclass(self) -> None:
        """Verify that HassetteError subclasses are properly tracked."""
        from hassette.exceptions import DependencyInjectionError

        with pytest.raises(DependencyInjectionError):
            async with track_execution() as result:
                raise DependencyInjectionError("bad sig")

        assert result.status == "error"
        assert result.error_type == "DependencyInjectionError"
        assert result.error_message == "bad sig"
