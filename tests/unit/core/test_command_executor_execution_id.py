"""Tests for ContextVar execution_id wiring in CommandExecutor (WP02)."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import whenever

from hassette.context import CURRENT_EXECUTION_ID
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.events.base import Event, HassContext, HassettePayload, HassPayload

# ---------------------------------------------------------------------------
# Factories
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

    # task_bucket: spawn creates actual tasks so error handlers run
    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    spawned_tasks: list[asyncio.Task] = []

    def _spawn(coro, *, name=None):
        task = asyncio.create_task(coro, name=name)
        spawned_tasks.append(task)
        return task

    task_bucket.spawn = _spawn
    executor.task_bucket = task_bucket
    executor._spawned_tasks = spawned_tasks
    return executor


def _make_hass_event(origin: str = "LOCAL") -> Event:
    """Build a minimal HassPayload-based Event."""
    context = HassContext(id="ctx-abc123", parent_id=None, user_id=None)
    payload = HassPayload(
        event_type="state_changed",
        data=None,
        origin=origin,  # pyright: ignore[reportArgumentType]
        time_fired=whenever.ZonedDateTime.now("UTC"),
        context=context,
    )
    return Event(topic="hass.state_changed", payload=payload)


def _make_hassette_event() -> Event:
    """Build a minimal HassettePayload-based Event."""
    payload = HassettePayload(
        event_type="hassette.ready",
        data=None,
    )
    return Event(topic="hassette.ready", payload=payload)


def _make_listener(*, side_effect=None) -> MagicMock:
    """Build a minimal Listener-like mock."""
    listener = MagicMock()
    listener.listener_id = 1
    listener.error_handler = None
    if side_effect is None:
        listener.invoke = AsyncMock(return_value=None)
    else:
        listener.invoke = AsyncMock(side_effect=side_effect)
    listener.__repr__ = lambda _self: "Listener<test>"
    return listener


def _make_invoke_handler_cmd(
    *,
    listener: MagicMock | None = None,
    event: Event | None = None,
    app_level_error_handler=None,
) -> MagicMock:
    """Build a minimal InvokeHandler-like mock."""
    if listener is None:
        listener = _make_listener()
    if event is None:
        event = _make_hass_event()
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = "app"
    cmd.listener_id = 1
    cmd.topic = "hass.state_changed"
    cmd.listener = listener
    cmd.event = event
    cmd.effective_timeout = None
    cmd.app_level_error_handler = app_level_error_handler
    return cmd


def _make_execute_job_cmd(*, side_effect=None, job_error_handler=None) -> MagicMock:
    """Build a minimal ExecuteJob-like mock."""
    cmd = MagicMock(spec=ExecuteJob)
    cmd.source_tier = "app"
    cmd.job_db_id = 1
    if side_effect is None:
        cmd.callable = AsyncMock(return_value=None)
    else:
        cmd.callable = AsyncMock(side_effect=side_effect)
    cmd.effective_timeout = None
    cmd.job = MagicMock()
    cmd.job.job_id = 99
    cmd.job.error_handler = job_error_handler
    cmd.job.name = "test_job"
    cmd.job.group = None
    cmd.job.args = ()
    cmd.job.kwargs = {}
    cmd.app_level_error_handler = None
    return cmd


async def _drain_tasks(executor: CommandExecutor) -> None:
    """Allow all spawned error handler tasks to complete."""
    tasks = executor._spawned_tasks
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        tasks.clear()


def _is_valid_uuid4(value: str) -> bool:
    """Return True if value is a valid UUID4 string."""
    try:
        parsed = uuid.UUID(value, version=4)
        return str(parsed) == value
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# ContextVar lifecycle tests
# ---------------------------------------------------------------------------


class TestExecutionIdContextVar:
    async def test_execution_id_set_during_handler_execution(self) -> None:
        """CURRENT_EXECUTION_ID is non-None and UUID4 during handler execution."""
        executor = _make_executor()
        captured: list[str | None] = []

        async def handler_fn(*_args) -> None:
            captured.append(CURRENT_EXECUTION_ID.get())

        listener = _make_listener()
        listener.invoke = AsyncMock(side_effect=handler_fn)
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)

        assert len(captured) == 1
        value = captured[0]
        assert value is not None
        assert _is_valid_uuid4(value)

        # The enqueued record must have the same execution_id
        record = executor._write_queue.get_nowait()
        assert record.execution_id == value

    async def test_execution_id_none_after_handler_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None after _execute_handler() returns."""
        executor = _make_executor()
        listener = _make_listener()
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_execution_id_none_after_cancelled_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None even when handler raises CancelledError."""
        executor = _make_executor()

        listener = _make_listener(side_effect=asyncio.CancelledError)
        cmd = _make_invoke_handler_cmd(listener=listener)

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_handler(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_execution_id_unique_per_execution(self) -> None:
        """Two handler executions produce different execution_id values."""
        executor = _make_executor()

        ids: list[str | None] = []

        async def capture(*_args) -> None:
            ids.append(CURRENT_EXECUTION_ID.get())

        for _ in range(2):
            listener = _make_listener()
            listener.invoke = AsyncMock(side_effect=capture)
            cmd = _make_invoke_handler_cmd(listener=listener)
            await executor._execute_handler(cmd)

        assert len(ids) == 2
        assert ids[0] is not None
        assert ids[1] is not None
        assert ids[0] != ids[1]

    async def test_execution_id_set_during_job_execution(self) -> None:
        """CURRENT_EXECUTION_ID is non-None and UUID4 during job execution."""
        executor = _make_executor()
        captured: list[str | None] = []

        async def job_fn(*_args) -> None:
            captured.append(CURRENT_EXECUTION_ID.get())

        cmd = _make_execute_job_cmd()
        cmd.callable = AsyncMock(side_effect=job_fn)

        await executor._execute_job(cmd)

        assert len(captured) == 1
        value = captured[0]
        assert value is not None
        assert _is_valid_uuid4(value)

        # Enqueued record must have the same execution_id
        record = executor._write_queue.get_nowait()
        assert record.execution_id == value

    async def test_execution_id_none_after_job_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None after _execute_job() returns."""
        executor = _make_executor()
        cmd = _make_execute_job_cmd()

        await executor._execute_job(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_execution_id_none_after_cancelled_job_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None even when job raises CancelledError."""
        executor = _make_executor()
        cmd = _make_execute_job_cmd(side_effect=asyncio.CancelledError)

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_job(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_concurrent_handlers_get_independent_execution_ids(self) -> None:
        """Two handlers running concurrently each see their own execution_id."""
        executor = _make_executor()
        captured: list[str | None] = []
        barrier = asyncio.Event()

        async def capture_with_yield(*_args) -> None:
            captured.append(CURRENT_EXECUTION_ID.get())
            barrier.set()
            await asyncio.sleep(0)

        async def capture_after_barrier(*_args) -> None:
            await barrier.wait()
            captured.append(CURRENT_EXECUTION_ID.get())

        listener1 = _make_listener()
        listener1.invoke = AsyncMock(side_effect=capture_with_yield)
        cmd1 = _make_invoke_handler_cmd(listener=listener1)

        listener2 = _make_listener()
        listener2.invoke = AsyncMock(side_effect=capture_after_barrier)
        cmd2 = _make_invoke_handler_cmd(listener=listener2)

        await asyncio.gather(
            executor._execute_handler(cmd1),
            executor._execute_handler(cmd2),
        )

        assert len(captured) == 2
        assert captured[0] is not None
        assert captured[1] is not None
        assert captured[0] != captured[1]


# ---------------------------------------------------------------------------
# HandlerInvocationRecord trigger field tests
# ---------------------------------------------------------------------------


class TestHandlerRecordTriggerFields:
    async def test_handler_record_has_trigger_context_id(self) -> None:
        """trigger_context_id on the enqueued record matches the HassPayload's event_id."""
        executor = _make_executor()
        event = _make_hass_event()
        listener = _make_listener()
        cmd = _make_invoke_handler_cmd(listener=listener, event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_context_id == event.payload.event_id

    async def test_handler_record_has_trigger_origin_local(self) -> None:
        """trigger_origin is 'LOCAL' when event has origin='LOCAL'."""
        executor = _make_executor()
        event = _make_hass_event(origin="LOCAL")
        cmd = _make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == "LOCAL"

    async def test_handler_record_has_trigger_origin_remote(self) -> None:
        """trigger_origin is 'REMOTE' when event has origin='REMOTE'."""
        executor = _make_executor()
        event = _make_hass_event(origin="REMOTE")
        cmd = _make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == "REMOTE"

    async def test_handler_record_has_trigger_origin_hassette(self) -> None:
        """trigger_origin is 'HASSETTE' when event uses HassettePayload."""
        executor = _make_executor()
        event = _make_hassette_event()
        cmd = _make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == "HASSETTE"

    async def test_handler_record_has_trigger_context_id_hassette(self) -> None:
        """trigger_context_id for HassettePayload-based event is the payload's event_id."""
        executor = _make_executor()
        event = _make_hassette_event()
        cmd = _make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_context_id == event.payload.event_id
        assert _is_valid_uuid4(record.trigger_context_id)


# ---------------------------------------------------------------------------
# JobExecutionRecord trigger field tests
# ---------------------------------------------------------------------------


class TestJobRecordFields:
    async def test_job_record_has_execution_id_no_trigger(self) -> None:
        """Job execution record has execution_id and no trigger fields."""
        executor = _make_executor()
        cmd = _make_execute_job_cmd()

        await executor._execute_job(cmd)

        record = executor._write_queue.get_nowait()
        assert record.execution_id is not None
        assert _is_valid_uuid4(record.execution_id)
        assert not hasattr(record, "trigger_context_id")
        assert not hasattr(record, "trigger_origin")


# ---------------------------------------------------------------------------
# Error handler context inheritance test
# ---------------------------------------------------------------------------


class TestErrorHandlerExecutionIdInheritance:
    async def test_error_handler_inherits_execution_id(self) -> None:
        """Spawned error handler task sees the same CURRENT_EXECUTION_ID as the main execution."""
        executor = _make_executor()

        main_id: list[str | None] = []
        handler_id: list[str | None] = []

        async def capture_main(*_args) -> None:
            main_id.append(CURRENT_EXECUTION_ID.get())
            raise RuntimeError("trigger error handler")

        async def error_handler(_ctx) -> None:
            handler_id.append(CURRENT_EXECUTION_ID.get())

        listener = _make_listener(side_effect=capture_main)
        listener.error_handler = error_handler
        cmd = _make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await _drain_tasks(executor)

        assert len(main_id) == 1
        assert len(handler_id) == 1
        assert main_id[0] is not None
        assert main_id[0] == handler_id[0]
