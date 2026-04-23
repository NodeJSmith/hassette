"""Tests for CommandExecutor error handler invocation path (WP04)."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.error_context import BusErrorContext
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.scheduler.error_context import SchedulerErrorContext

# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _make_executor() -> CommandExecutor:
    """Build a CommandExecutor with all dependencies mocked out."""
    hassette = MagicMock()
    hassette.config.telemetry_write_queue_max = 1000
    hassette.config.command_executor_log_level = "DEBUG"
    hassette.config.error_handler_timeout_seconds = 5.0
    hassette.database_service = MagicMock()
    hassette.session_id = 42
    executor = CommandExecutor.__new__(CommandExecutor)
    executor._write_queue = asyncio.Queue(maxsize=1000)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._dropped_no_session = 0
    executor._dropped_shutdown = 0
    executor._error_handler_failures = 0
    executor._last_capacity_warn_ts = 0.0
    executor._timeout_warn_timestamps = {}
    executor.repository = MagicMock()
    executor.hassette = hassette
    executor._logger = MagicMock()
    executor.logger = MagicMock()

    # task_bucket: real spawn needed so error handler tasks actually run
    task_bucket = MagicMock()
    # Default: make_async_adapter returns handler unchanged (already async)
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    # spawn: actually creates and runs the coroutine so tests can await it
    spawned_tasks: list[asyncio.Task] = []

    def _spawn(coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        spawned_tasks.append(task)
        return task

    task_bucket.spawn = _spawn
    executor.task_bucket = task_bucket
    executor._spawned_tasks = spawned_tasks  # for test access
    return executor


def _make_listener(
    *,
    error_handler: Callable | None = None,
) -> MagicMock:
    """Build a minimal Listener-like mock."""
    listener = MagicMock()
    listener.listener_id = 1
    listener.error_handler = error_handler
    listener.invoke = AsyncMock(return_value=None)
    listener.__repr__ = lambda _self: "Listener<test>"
    return listener


def _make_invoke_handler_cmd(
    *,
    listener: MagicMock | None = None,
    app_level_error_handler: Callable | None = None,
) -> MagicMock:
    """Build a minimal InvokeHandler-like mock."""
    if listener is None:
        listener = _make_listener()
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = "app"
    cmd.listener_id = 1
    cmd.topic = "test/topic"
    cmd.listener = listener
    cmd.event = MagicMock()
    cmd.effective_timeout = None
    cmd.app_level_error_handler = app_level_error_handler
    return cmd


def _make_execute_job_cmd(
    *,
    job_error_handler: Callable | None = None,
    app_level_error_handler: Callable | None = None,
) -> MagicMock:
    """Build a minimal ExecuteJob-like mock."""
    cmd = MagicMock(spec=ExecuteJob)
    cmd.source_tier = "app"
    cmd.job_db_id = 1
    cmd.callable = AsyncMock(return_value=None)
    cmd.effective_timeout = None
    cmd.job = MagicMock()
    cmd.job.error_handler = job_error_handler
    cmd.job.name = "test_job"
    cmd.job.group = None
    cmd.job.args = ()
    cmd.job.kwargs = {}
    cmd.app_level_error_handler = app_level_error_handler
    return cmd


async def _drain_tasks(executor: CommandExecutor) -> None:
    """Allow all spawned error handler tasks to complete."""
    tasks = executor._spawned_tasks
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        tasks.clear()


# ---------------------------------------------------------------------------
# InvokeHandler (bus) error handler tests
# ---------------------------------------------------------------------------


class TestBusErrorHandlerInvocation:
    async def test_error_handler_invoked_on_exception(self) -> None:
        """When handler raises, error handler is called with a BusErrorContext."""
        executor = _make_executor()
        received_ctx: list[BusErrorContext] = []

        async def error_handler(ctx: BusErrorContext) -> None:
            received_ctx.append(ctx)

        listener = _make_listener(error_handler=error_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("boom"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert len(received_ctx) == 1
        ctx = received_ctx[0]
        assert isinstance(ctx.exception, RuntimeError)
        assert "boom" in str(ctx.exception)

    async def test_error_handler_receives_correct_context(self) -> None:
        """BusErrorContext fields are correctly populated from cmd and result."""
        executor = _make_executor()
        received_ctx: list[BusErrorContext] = []

        async def error_handler(ctx: BusErrorContext) -> None:
            received_ctx.append(ctx)

        listener = _make_listener(error_handler=error_handler)
        exc = ValueError("ctx test")
        listener.invoke = AsyncMock(side_effect=exc)
        event = MagicMock()
        cmd = _make_invoke_handler_cmd(listener=listener)
        cmd.event = event
        cmd.topic = "hass.state_changed"

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert len(received_ctx) == 1
        ctx = received_ctx[0]
        assert ctx.exception is exc
        assert isinstance(ctx.traceback, str)
        assert "ValueError" in ctx.traceback
        assert ctx.topic == "hass.state_changed"
        assert ctx.listener_name == repr(listener)
        assert ctx.event is event

    async def test_error_handler_not_invoked_on_success(self) -> None:
        """No error handler call when handler completes successfully."""
        executor = _make_executor()
        called = []

        async def error_handler(ctx: BusErrorContext) -> None:
            called.append(ctx)

        listener = _make_listener(error_handler=error_handler)
        listener.invoke = AsyncMock(return_value=None)
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert called == []

    async def test_error_handler_not_invoked_on_cancelled(self) -> None:
        """CancelledError does not invoke the error handler (re-raised from _execute)."""
        executor = _make_executor()
        called = []

        async def error_handler(ctx: BusErrorContext) -> None:
            called.append(ctx)

        listener = _make_listener(error_handler=error_handler)
        listener.invoke = AsyncMock(side_effect=asyncio.CancelledError)
        cmd = _make_invoke_handler_cmd(listener=listener)

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert called == []

    async def test_error_handler_invoked_on_timeout(self) -> None:
        """TimeoutError invokes the error handler (result.exc is populated)."""
        executor = _make_executor()
        called = []

        async def error_handler(ctx: BusErrorContext) -> None:
            called.append(ctx)

        listener = _make_listener(error_handler=error_handler)
        listener.invoke = AsyncMock(side_effect=TimeoutError("timed out"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert len(called) == 1
        assert isinstance(called[0].exception, TimeoutError)

    async def test_per_registration_handler_wins_over_app_level(self) -> None:
        """Per-registration error_handler takes priority over app_level_error_handler."""
        executor = _make_executor()
        per_reg_called = []
        app_called = []

        async def per_reg_handler(ctx: BusErrorContext) -> None:
            per_reg_called.append(ctx)

        async def app_handler(ctx: BusErrorContext) -> None:
            app_called.append(ctx)

        listener = _make_listener(error_handler=per_reg_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("oops"))
        cmd = _make_invoke_handler_cmd(listener=listener, app_level_error_handler=app_handler)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert len(per_reg_called) == 1
        assert app_called == []

    async def test_app_level_handler_used_when_no_per_registration(self) -> None:
        """App-level error handler is used when listener has no per-registration handler."""
        executor = _make_executor()
        app_called = []

        async def app_handler(ctx: BusErrorContext) -> None:
            app_called.append(ctx)

        listener = _make_listener(error_handler=None)
        listener.invoke = AsyncMock(side_effect=RuntimeError("app level"))
        cmd = _make_invoke_handler_cmd(listener=listener, app_level_error_handler=app_handler)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert len(app_called) == 1

    async def test_no_handler_existing_behavior_unchanged(self) -> None:
        """When no error handler is set, execution proceeds normally without error."""
        executor = _make_executor()
        listener = _make_listener(error_handler=None)
        listener.invoke = AsyncMock(side_effect=RuntimeError("unhandled"))
        cmd = _make_invoke_handler_cmd(listener=listener, app_level_error_handler=None)

        # Should not raise
        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        # No tasks spawned
        assert executor._error_handler_failures == 0

    async def test_error_handler_failure_caught_and_logged(self) -> None:
        """When the error handler itself raises, it is caught and logged."""
        executor = _make_executor()

        async def bad_handler(_ctx: BusErrorContext) -> None:
            raise ValueError("handler is broken")

        listener = _make_listener(error_handler=bad_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("original"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        # Should not propagate — executor._logger.error should have been called
        # (error_handler_failures incremented)
        assert executor._error_handler_failures == 1

    async def test_error_handler_failure_increments_counter(self) -> None:
        """_error_handler_failures is incremented each time a handler fails."""
        executor = _make_executor()

        async def bad_handler(_ctx: BusErrorContext) -> None:
            raise RuntimeError("fail")

        for _ in range(3):
            listener = _make_listener(error_handler=bad_handler)
            listener.invoke = AsyncMock(side_effect=RuntimeError("original"))
            cmd = _make_invoke_handler_cmd(listener=listener)
            await executor._execute_handler(cmd)

        await _drain_tasks(executor)
        assert executor._error_handler_failures == 3

    async def test_error_handler_timeout_logs_warning(self) -> None:
        """When error handler times out, _error_handler_failures is incremented."""
        executor = _make_executor()
        executor.hassette.config.error_handler_timeout_seconds = 0.01

        async def slow_handler(_ctx: BusErrorContext) -> None:
            await asyncio.sleep(10)  # will be cancelled by timeout

        listener = _make_listener(error_handler=slow_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("original"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert executor._error_handler_failures == 1

    async def test_error_handler_runs_in_separate_task(self) -> None:
        """Error handler is spawned as a separate task, not inline."""
        executor = _make_executor()

        # Track spawn calls
        spawn_calls: list[str] = []
        original_spawn = executor.task_bucket.spawn

        def tracking_spawn(coro, *, name=None):
            spawn_calls.append(name or "unnamed")
            return original_spawn(coro, name=name)

        executor.task_bucket.spawn = tracking_spawn

        async def error_handler(ctx: BusErrorContext) -> None:
            pass

        listener = _make_listener(error_handler=error_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("original"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert any("error_handler" in name for name in spawn_calls)

    async def test_framework_log_still_emitted_with_custom_handler(self) -> None:
        """Framework error logging happens inside _execute(); custom handler runs after, not instead."""
        executor = _make_executor()
        error_handler_called = []

        async def error_handler(ctx: BusErrorContext) -> None:
            error_handler_called.append(ctx)

        listener = _make_listener(error_handler=error_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("test"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        # Framework logging (via _log_error inside _execute) must have been called
        executor.logger.error.assert_called()
        # User handler also called
        assert len(error_handler_called) == 1

    async def test_get_error_handler_failures_api(self) -> None:
        """get_error_handler_failures() returns the counter value."""
        executor = _make_executor()
        assert executor.get_error_handler_failures() == 0

        async def bad_handler(_ctx: BusErrorContext) -> None:
            raise RuntimeError("oops")

        listener = _make_listener(error_handler=bad_handler)
        listener.invoke = AsyncMock(side_effect=RuntimeError("original"))
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert executor.get_error_handler_failures() == 1


# ---------------------------------------------------------------------------
# ExecuteJob (scheduler) error handler tests
# ---------------------------------------------------------------------------


class TestSchedulerErrorHandlerInvocation:
    async def test_error_handler_invoked_on_exception(self) -> None:
        """When job raises, error handler is called with a SchedulerErrorContext."""
        executor = _make_executor()
        received_ctx: list[SchedulerErrorContext] = []

        async def error_handler(ctx: SchedulerErrorContext) -> None:
            received_ctx.append(ctx)

        cmd = _make_execute_job_cmd(job_error_handler=error_handler)
        cmd.callable = AsyncMock(side_effect=RuntimeError("job boom"))

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert len(received_ctx) == 1
        ctx = received_ctx[0]
        assert isinstance(ctx.exception, RuntimeError)

    async def test_error_handler_receives_correct_context(self) -> None:
        """SchedulerErrorContext fields are correctly populated from cmd and result."""
        executor = _make_executor()
        received_ctx: list[SchedulerErrorContext] = []

        async def error_handler(ctx: SchedulerErrorContext) -> None:
            received_ctx.append(ctx)

        exc = ValueError("sched test")
        cmd = _make_execute_job_cmd(job_error_handler=error_handler)
        cmd.job.name = "my_job"
        cmd.job.group = "group_a"
        cmd.job.args = (1, 2)
        cmd.job.kwargs = {"key": "val"}
        cmd.callable = AsyncMock(side_effect=exc)

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert len(received_ctx) == 1
        ctx = received_ctx[0]
        assert ctx.exception is exc
        assert isinstance(ctx.traceback, str)
        assert "ValueError" in ctx.traceback
        assert ctx.job_name == "my_job"
        assert ctx.job_group == "group_a"
        assert ctx.args == (1, 2)
        assert ctx.kwargs == {"key": "val"}

    async def test_error_handler_not_invoked_on_success(self) -> None:
        """No error handler call when job succeeds."""
        executor = _make_executor()
        called = []

        async def error_handler(ctx: SchedulerErrorContext) -> None:
            called.append(ctx)

        cmd = _make_execute_job_cmd(job_error_handler=error_handler)
        cmd.callable = AsyncMock(return_value=None)

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert called == []

    async def test_per_registration_handler_wins_over_app_level(self) -> None:
        """Per-job error_handler takes priority over app_level_error_handler."""
        executor = _make_executor()
        per_reg_called = []
        app_called = []

        async def per_reg(ctx: SchedulerErrorContext) -> None:
            per_reg_called.append(ctx)

        async def app_handler(ctx: SchedulerErrorContext) -> None:
            app_called.append(ctx)

        cmd = _make_execute_job_cmd(job_error_handler=per_reg, app_level_error_handler=app_handler)
        cmd.callable = AsyncMock(side_effect=RuntimeError("oops"))

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert len(per_reg_called) == 1
        assert app_called == []

    async def test_app_level_handler_used_when_no_per_registration(self) -> None:
        """App-level error handler used when job has no per-registration handler."""
        executor = _make_executor()
        app_called = []

        async def app_handler(ctx: SchedulerErrorContext) -> None:
            app_called.append(ctx)

        cmd = _make_execute_job_cmd(job_error_handler=None, app_level_error_handler=app_handler)
        cmd.callable = AsyncMock(side_effect=RuntimeError("fail"))

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert len(app_called) == 1

    async def test_no_handler_existing_behavior_unchanged(self) -> None:
        """When no error handler set, execution proceeds normally."""
        executor = _make_executor()
        cmd = _make_execute_job_cmd(job_error_handler=None, app_level_error_handler=None)
        cmd.callable = AsyncMock(side_effect=RuntimeError("unhandled"))

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert executor._error_handler_failures == 0

    async def test_error_handler_failure_increments_counter(self) -> None:
        """_error_handler_failures incremented when scheduler handler raises."""
        executor = _make_executor()

        async def bad(_ctx: SchedulerErrorContext) -> None:
            raise RuntimeError("handler fail")

        cmd = _make_execute_job_cmd(job_error_handler=bad)
        cmd.callable = AsyncMock(side_effect=RuntimeError("original"))

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert executor._error_handler_failures == 1

    async def test_error_handler_timeout_increments_counter(self) -> None:
        """_error_handler_failures incremented when scheduler handler times out."""
        executor = _make_executor()
        executor.hassette.config.error_handler_timeout_seconds = 0.01

        async def slow(_ctx: SchedulerErrorContext) -> None:
            await asyncio.sleep(10)

        cmd = _make_execute_job_cmd(job_error_handler=slow)
        cmd.callable = AsyncMock(side_effect=RuntimeError("original"))

        await executor._execute_job(cmd)
        await _drain_tasks(executor)

        assert executor._error_handler_failures == 1
