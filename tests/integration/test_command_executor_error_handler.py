"""Integration tests for CommandExecutor error handler invocation paths."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.error_context import BusErrorContext
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.database_service import DatabaseService
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.test_utils import wait_for

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def executor(
    db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]
) -> AsyncIterator[CommandExecutor]:
    """Create and prepare a CommandExecutor with real DB and TaskBucket wired in."""
    _db_service, _session_id = initialized_db
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


def _make_mock_listener(*, error_handler=None) -> MagicMock:
    """Return a mock Listener whose invoke() is an awaitable coroutine."""
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.invoker.invoke = AsyncMock()
    listener.error_handler = error_handler
    listener.invoker.error_handler = error_handler
    return listener


def _make_mock_job(*, error_handler=None) -> MagicMock:
    """Return a mock ScheduledJob with optional error handler."""
    job = MagicMock(spec=ScheduledJob)
    job.error_handler = error_handler
    job.name = "test_job"
    job.group = None
    job.args = ()
    job.kwargs = {}
    return job


# ---------------------------------------------------------------------------
# Bus error handler execution path tests
# ---------------------------------------------------------------------------


async def test_error_handler_runs_after_framework_log(executor: CommandExecutor) -> None:
    """Error handler is invoked after framework logging — not instead of it."""
    listener = _make_mock_listener()
    listener.invoke.side_effect = ValueError("handler error")
    listener.invoker.invoke.side_effect = ValueError("handler error")

    handler_called = asyncio.Event()
    received_ctx: list[BusErrorContext] = []

    async def error_handler(ctx: BusErrorContext) -> None:
        received_ctx.append(ctx)
        handler_called.set()

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test.topic",
        listener_id=1,
        source_tier="app",
        effective_timeout=None,
        app_level_error_handler=error_handler,
    )

    await executor.execute(cmd)

    await asyncio.wait_for(handler_called.wait(), timeout=2.0)

    assert len(received_ctx) == 1
    assert isinstance(received_ctx[0].exception, ValueError)
    assert received_ctx[0].topic == "test.topic"
    # Framework still recorded the error in the write queue
    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert record.status == "error"


async def test_sync_error_handler_wraps_in_thread(executor: CommandExecutor) -> None:
    """A sync error handler is wrapped via make_async_adapter and runs without error."""
    listener = _make_mock_listener()
    listener.invoke.side_effect = RuntimeError("sync handler test")
    listener.invoker.invoke.side_effect = RuntimeError("sync handler test")

    handler_called = asyncio.Event()
    received_ctx: list[BusErrorContext] = []
    # Capture the running loop on the async test thread so the sync handler
    # can signal it via call_soon_threadsafe (thread-safe, no loop lookup needed).
    loop = asyncio.get_running_loop()

    def sync_error_handler(ctx: BusErrorContext) -> None:
        received_ctx.append(ctx)
        loop.call_soon_threadsafe(handler_called.set)

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test.sync",
        listener_id=1,
        source_tier="app",
        effective_timeout=None,
        app_level_error_handler=sync_error_handler,
    )

    await executor.execute(cmd)

    await asyncio.wait_for(handler_called.wait(), timeout=2.0)

    assert len(received_ctx) == 1
    assert isinstance(received_ctx[0].exception, RuntimeError)


async def test_double_failure_logged_and_counted(executor: CommandExecutor) -> None:
    """When both the listener and its error handler raise, _error_handler_failures is incremented."""
    listener = _make_mock_listener()
    listener.invoke.side_effect = ValueError("original error")
    listener.invoker.invoke.side_effect = ValueError("original error")

    handler_ran = asyncio.Event()

    async def failing_error_handler(_ctx: BusErrorContext) -> None:
        handler_ran.set()
        raise RuntimeError("error handler also failed")

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test.double_fail",
        listener_id=1,
        source_tier="app",
        effective_timeout=None,
        app_level_error_handler=failing_error_handler,
    )

    await executor.execute(cmd)

    await asyncio.wait_for(handler_ran.wait(), timeout=2.0)
    await wait_for(lambda: executor.get_error_handler_failures() >= 1, desc="error handler failure recorded")

    assert executor.get_error_handler_failures() >= 1


async def test_cancelled_error_not_routed_to_handler(executor: CommandExecutor) -> None:
    """CancelledError is re-raised and never routed to the user error handler."""
    listener = _make_mock_listener()
    listener.invoke.side_effect = asyncio.CancelledError()
    listener.invoker.invoke.side_effect = asyncio.CancelledError()

    handler_called = asyncio.Event()

    async def error_handler(_ctx: BusErrorContext) -> None:
        handler_called.set()

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test.cancelled",
        listener_id=1,
        source_tier="app",
        effective_timeout=None,
        app_level_error_handler=error_handler,
    )

    with pytest.raises(asyncio.CancelledError):
        await executor.execute(cmd)

    # negative-assertion: no event-driven alternative
    await asyncio.sleep(0.05)
    assert not handler_called.is_set(), "Error handler must not be called for CancelledError"


async def test_timeout_error_routed_to_handler(executor: CommandExecutor) -> None:
    """TimeoutError is captured and routed to the user error handler."""
    listener = _make_mock_listener()

    async def slow_handler(_event) -> None:
        await asyncio.sleep(10)

    listener.invoke = slow_handler
    listener.invoker.invoke = slow_handler

    handler_called = asyncio.Event()
    received_ctx: list[BusErrorContext] = []

    async def error_handler(ctx: BusErrorContext) -> None:
        received_ctx.append(ctx)
        handler_called.set()

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test.timeout",
        listener_id=1,
        source_tier="app",
        effective_timeout=0.05,
        app_level_error_handler=error_handler,
    )

    await executor.execute(cmd)

    await asyncio.wait_for(handler_called.wait(), timeout=2.0)
    assert len(received_ctx) == 1
    assert isinstance(received_ctx[0].exception, TimeoutError)

    # Write queue should have a timed_out record
    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert record.status == "timed_out"


# ---------------------------------------------------------------------------
# Scheduler error handler execution path tests
# ---------------------------------------------------------------------------


async def test_error_handler_timeout_logs_warning(executor: CommandExecutor) -> None:
    """Error handler that sleeps > timeout logs WARNING and increments counter."""
    # Set a short timeout for testing
    executor.hassette.config.lifecycle.error_handler_timeout_seconds = 0.1

    job = _make_mock_job()
    job_ran = asyncio.Event()

    async def slow_error_handler(_ctx: SchedulerErrorContext) -> None:
        job_ran.set()
        await asyncio.sleep(10)  # Exceeds the 0.1s timeout

    async def failing_job() -> None:
        raise ValueError("job failed")

    cmd = ExecuteJob(
        job=job,
        callable=failing_job,
        job_db_id=1,
        source_tier="app",
        effective_timeout=None,
        app_level_error_handler=slow_error_handler,
    )

    await executor.execute(cmd)

    await asyncio.wait_for(job_ran.wait(), timeout=2.0)
    # Wait for timeout to trigger
    await asyncio.sleep(0.2)

    assert executor.get_error_handler_failures() >= 1
