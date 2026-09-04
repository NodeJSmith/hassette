"""CommandExecutor factories for tests/unit/core/."""

import asyncio
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hassette.commands import ExecuteJob
from hassette.core.command_executor import CommandExecutor
from hassette.core.execution_record import ExecutionRecord
from tests.support.factories import make_execution_record

# Shared fixture/factory config values — named so re-tuning is a single-site edit.
COMMAND_EXECUTOR_CAPACITY_WARN_THRESHOLD = 0.75
COMMAND_EXECUTOR_CAPACITY_WARN_RATE_LIMIT_SECONDS = 30.0
TEST_SESSION_ID = 42


def make_executor(*, error_handler_timeout: float = 5.0) -> CommandExecutor:
    """Build a CommandExecutor with all dependencies mocked out."""
    hassette = MagicMock()
    hassette.config.database.telemetry_write_queue_max = 1000
    hassette.config.logging.command_executor = "DEBUG"
    hassette.config.lifecycle.error_handler_timeout_seconds = error_handler_timeout
    hassette.config.lifecycle.command_executor_capacity_warn_threshold = COMMAND_EXECUTOR_CAPACITY_WARN_THRESHOLD
    hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds = (
        COMMAND_EXECUTOR_CAPACITY_WARN_RATE_LIMIT_SECONDS
    )
    hassette.database_service = MagicMock()
    hassette.session_id = TEST_SESSION_ID
    hassette.try_session_id.return_value = TEST_SESSION_ID
    executor = CommandExecutor.__new__(CommandExecutor)
    executor._write_queue = asyncio.Queue(maxsize=1000)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._dropped_shutdown = 0
    executor._error_handler_failures = 0
    executor._last_capacity_warn_ts = 0.0
    executor._last_unowned_warn_ts = None
    executor._timeout_warn_timestamps = {}
    executor._clock = time.monotonic
    executor.repository = MagicMock()
    executor.hassette = hassette
    executor._logger = MagicMock()
    executor.logger = MagicMock()

    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    spawned_tasks: list[asyncio.Task] = []

    def spawn(coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        spawned_tasks.append(task)
        return task

    task_bucket.spawn = spawn
    executor.task_bucket = task_bucket
    executor._spawned_tasks = spawned_tasks
    return executor


def init_executor(queue_max: int = 10) -> CommandExecutor:
    """Create and minimally init a CommandExecutor for write-pipeline tests.

    Unlike ``make_executor`` above (error-handler invocation tests), this variant sets up the
    fields the write-pipeline needs directly: a bounded ``_write_queue``, capacity-warning
    config, and a real ``ready_event`` so the module-level ``mark_ready()`` (called by
    ``serve()``) can operate on this bypassed instance. Shared by
    ``test_command_executor_pipeline_queue.py``, ``test_command_executor_pipeline_persist.py``,
    and ``test_command_executor_pipeline_serve.py``.
    """
    executor = CommandExecutor.__new__(CommandExecutor)
    executor._write_queue = asyncio.Queue(maxsize=queue_max)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._dropped_shutdown = 0
    executor._error_handler_failures = 0
    executor._last_capacity_warn_ts = None
    executor._last_unowned_warn_ts = None
    executor._timeout_warn_timestamps = {}
    executor._clock = time.monotonic
    executor.repository = MagicMock()
    executor.repository.persist_batch = MagicMock()
    executor.hassette = MagicMock()
    executor.hassette.session_id = TEST_SESSION_ID
    executor.hassette.try_session_id.return_value = TEST_SESSION_ID
    executor.hassette.config.database.telemetry_write_queue_max = queue_max
    executor.hassette.config.lifecycle.command_executor_capacity_warn_threshold = (
        COMMAND_EXECUTOR_CAPACITY_WARN_THRESHOLD
    )
    executor.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds = (
        COMMAND_EXECUTOR_CAPACITY_WARN_RATE_LIMIT_SECONDS
    )
    executor.hassette.database_service = MagicMock()
    executor.hassette.database_service.submit = AsyncMock(return_value=None)
    executor.logger = MagicMock()
    executor._unique_name = "CommandExecutor.test"
    executor.ready_event = asyncio.Event()
    executor._ready_reason = None
    return executor


# Convenience alias for readability in the write-pipeline tests. Delegates to the shared
# factory but pins execution_start_ts/execution_id to this file's original values (wall-clock
# timestamp, unset execution_id) — no test here asserts on either, so this is not a
# load-bearing override, just a faithful behavior-preserving migration off the old local
# duplicate. Shared by the same three pipeline files as ``init_executor`` above.
def make_invocation(
    listener_id: int | None = 1,
    session_id: int = 1,
    source_tier: str = "app",
    is_di_failure: bool = False,
) -> ExecutionRecord:
    return make_execution_record(
        kind="handler",
        listener_id=listener_id,
        job_id=None,
        session_id=session_id,
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
        is_di_failure=is_di_failure,
        execution_start_ts=time.time(),
        duration_ms=1.0,
        execution_id=None,
    )


def make_mock_cmd_listener(
    *,
    side_effect: Any = None,
    error_handler: Callable[..., Any] | None = None,
) -> MagicMock:
    """Build a MagicMock standing in for a Listener in CommandExecutor tests."""
    listener = MagicMock()
    listener.listener_id = 1
    listener.invoker.error_handler = error_handler
    if side_effect is None:
        listener.invoker.invoke = AsyncMock(return_value=None)
    else:
        listener.invoker.invoke = AsyncMock(side_effect=side_effect)
    listener.__repr__ = lambda _self: "Listener<test>"
    return listener


def make_execute_job_cmd(
    *,
    side_effect: Any = None,
    job_error_handler: Callable[..., Any] | None = None,
    app_level_error_handler: Callable[..., Any] | None = None,
    job_id: int = 99,
) -> MagicMock:
    """Build a MagicMock spec'd to ExecuteJob for CommandExecutor tests."""
    cmd = MagicMock(spec=ExecuteJob)
    cmd.source_tier = "app"
    cmd.job_db_id = 1
    cmd.trigger_mode = None
    if side_effect is None:
        cmd.callable = AsyncMock(return_value=None)
    else:
        cmd.callable = AsyncMock(side_effect=side_effect)
    cmd.effective_timeout = None
    cmd.job = MagicMock()
    cmd.job.job_id = job_id
    cmd.job.error_handler = job_error_handler
    cmd.job.name = "test_job"
    cmd.job.group = None
    cmd.job.args = ()
    cmd.job.kwargs = {}
    cmd.app_level_error_handler = app_level_error_handler
    return cmd
