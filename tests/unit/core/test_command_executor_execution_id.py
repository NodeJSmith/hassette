"""Tests for ContextVar execution_id wiring in CommandExecutor (WP02)."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import uuid_utils
import whenever

from hassette.context import CURRENT_EXECUTION_ID
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.execution_record import SYNTHETIC_ORIGIN
from hassette.events.base import Event, HassContext, HassettePayload, HassPayload

from .conftest import make_executor


def make_hass_event(origin: str = "LOCAL") -> Event:
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


def make_hassette_event() -> Event:
    """Build a minimal HassettePayload-based Event."""
    payload = HassettePayload(data=None)
    return Event(topic="hassette.ready", payload=payload)


def make_listener(*, side_effect=None) -> MagicMock:
    """Build a minimal Listener-like mock."""
    listener = MagicMock()
    listener.listener_id = 1
    listener.invoker.error_handler = None
    if side_effect is None:
        listener.invoker.invoke = AsyncMock(return_value=None)
    else:
        listener.invoker.invoke = AsyncMock(side_effect=side_effect)
    listener.__repr__ = lambda _self: "Listener<test>"
    return listener


def make_invoke_handler_cmd(
    *,
    listener: MagicMock | None = None,
    event: Event | None = None,
    app_level_error_handler=None,
) -> MagicMock:
    """Build a minimal InvokeHandler-like mock."""
    if listener is None:
        listener = make_listener()
    if event is None:
        event = make_hass_event()
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = "app"
    cmd.listener_id = 1
    cmd.topic = "hass.state_changed"
    cmd.listener = listener
    cmd.event = event
    cmd.effective_timeout = None
    cmd.app_level_error_handler = app_level_error_handler
    cmd.is_synthetic = False
    return cmd


def make_execute_job_cmd(*, side_effect=None, job_error_handler=None) -> MagicMock:
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


async def drain_tasks(executor: CommandExecutor) -> None:
    """Allow all spawned error handler tasks to complete."""
    tasks = executor._spawned_tasks
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        tasks.clear()


def is_valid_uuid4(value: str) -> bool:
    """Return True if value is a valid UUID4 string."""
    try:
        parsed = uuid.UUID(value, version=4)
        return str(parsed) == value
    except (ValueError, AttributeError):
        return False


def is_valid_uuid7(value: str) -> bool:
    """Return True if value is a valid UUID7 string."""
    try:
        parsed = uuid_utils.UUID(value)
        return parsed.version == 7
    except (ValueError, AttributeError):
        return False


class TestExecutionIdContextVar:
    async def test_execution_id_set_during_handler_execution(self) -> None:
        """CURRENT_EXECUTION_ID is non-None and UUIDv7 during handler execution."""
        executor = make_executor()
        captured: list[str | None] = []

        async def handler_fn(*_args) -> None:
            captured.append(CURRENT_EXECUTION_ID.get())

        listener = make_listener()
        listener.invoker.invoke = AsyncMock(side_effect=handler_fn)
        cmd = make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)

        assert len(captured) == 1
        value = captured[0]
        assert value is not None
        assert is_valid_uuid7(value)

        # The enqueued record must have the same execution_id
        record = executor._write_queue.get_nowait()
        assert record.execution_id == value

    async def test_execution_id_none_after_handler_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None after _execute_handler() returns."""
        executor = make_executor()
        listener = make_listener()
        cmd = make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_execution_id_none_after_cancelled_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None even when handler raises CancelledError."""
        executor = make_executor()

        listener = make_listener(side_effect=asyncio.CancelledError)
        cmd = make_invoke_handler_cmd(listener=listener)

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_handler(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_execution_id_unique_per_execution(self) -> None:
        """Two handler executions produce different execution_id values."""
        executor = make_executor()

        ids: list[str | None] = []

        async def capture(*_args) -> None:
            ids.append(CURRENT_EXECUTION_ID.get())

        for _ in range(2):
            listener = make_listener()
            listener.invoker.invoke = AsyncMock(side_effect=capture)
            cmd = make_invoke_handler_cmd(listener=listener)
            await executor._execute_handler(cmd)

        assert len(ids) == 2
        assert ids[0] is not None
        assert ids[1] is not None
        assert ids[0] != ids[1]

    async def test_execution_id_set_during_job_execution(self) -> None:
        """CURRENT_EXECUTION_ID is non-None and UUIDv7 during job execution."""
        executor = make_executor()
        captured: list[str | None] = []

        async def job_fn(*_args) -> None:
            captured.append(CURRENT_EXECUTION_ID.get())

        cmd = make_execute_job_cmd()
        cmd.callable = AsyncMock(side_effect=job_fn)

        await executor._execute_job(cmd)

        assert len(captured) == 1
        value = captured[0]
        assert value is not None
        assert is_valid_uuid7(value)

        # Enqueued record must have the same execution_id
        record = executor._write_queue.get_nowait()
        assert record.execution_id == value

    async def test_execution_id_none_after_job_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None after _execute_job() returns."""
        executor = make_executor()
        cmd = make_execute_job_cmd()

        await executor._execute_job(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_execution_id_none_after_cancelled_job_execution(self) -> None:
        """CURRENT_EXECUTION_ID resets to None even when job raises CancelledError."""
        executor = make_executor()
        cmd = make_execute_job_cmd(side_effect=asyncio.CancelledError)

        with pytest.raises(asyncio.CancelledError):
            await executor._execute_job(cmd)

        assert CURRENT_EXECUTION_ID.get() is None

    async def test_concurrent_handlers_get_independent_execution_ids(self) -> None:
        """Two handlers running concurrently each see their own execution_id."""
        executor = make_executor()
        captured: list[str | None] = []
        barrier = asyncio.Event()

        async def capture_with_yield(*_args) -> None:
            captured.append(CURRENT_EXECUTION_ID.get())
            barrier.set()
            await asyncio.sleep(0)

        async def capture_after_barrier(*_args) -> None:
            await barrier.wait()
            captured.append(CURRENT_EXECUTION_ID.get())

        listener1 = make_listener()
        listener1.invoke = AsyncMock(side_effect=capture_with_yield)
        listener1.invoker.invoke = AsyncMock(side_effect=capture_with_yield)
        cmd1 = make_invoke_handler_cmd(listener=listener1)

        listener2 = make_listener()
        listener2.invoke = AsyncMock(side_effect=capture_after_barrier)
        listener2.invoker.invoke = AsyncMock(side_effect=capture_after_barrier)
        cmd2 = make_invoke_handler_cmd(listener=listener2)

        await asyncio.gather(
            executor._execute_handler(cmd1),
            executor._execute_handler(cmd2),
        )

        assert len(captured) == 2
        assert captured[0] is not None
        assert captured[1] is not None
        assert captured[0] != captured[1]


class TestHandlerRecordTriggerFields:
    async def test_handler_record_has_trigger_context_id(self) -> None:
        """trigger_context_id on the enqueued record matches the HassPayload's event_id."""
        executor = make_executor()
        event = make_hass_event()
        listener = make_listener()
        cmd = make_invoke_handler_cmd(listener=listener, event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_context_id == event.payload.event_id

    async def test_handler_record_has_trigger_origin_local(self) -> None:
        """trigger_origin is 'LOCAL' when event has origin='LOCAL'."""
        executor = make_executor()
        event = make_hass_event(origin="LOCAL")
        cmd = make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == "LOCAL"

    async def test_handler_record_has_trigger_origin_remote(self) -> None:
        """trigger_origin is 'REMOTE' when event has origin='REMOTE'."""
        executor = make_executor()
        event = make_hass_event(origin="REMOTE")
        cmd = make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == "REMOTE"

    async def test_handler_record_has_trigger_origin_hassette(self) -> None:
        """trigger_origin is 'HASSETTE' when event uses HassettePayload."""
        executor = make_executor()
        event = make_hassette_event()
        cmd = make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == "HASSETTE"

    async def test_handler_record_has_trigger_context_id_hassette(self) -> None:
        """trigger_context_id for HassettePayload-based event is the payload's event_id."""
        executor = make_executor()
        event = make_hassette_event()
        cmd = make_invoke_handler_cmd(event=event)

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_context_id == event.payload.event_id
        assert is_valid_uuid4(record.trigger_context_id)

    async def test_synthetic_event_nulls_trigger_context_id(self) -> None:
        """Synthetic events (immediate=True) should have trigger_context_id=None."""
        executor = make_executor()
        event = make_hass_event()
        cmd = make_invoke_handler_cmd(event=event)
        cmd.is_synthetic = True

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_context_id is None

    async def test_synthetic_event_uses_hassette_synthetic_origin(self) -> None:
        """Synthetic events should have trigger_origin='HASSETTE_SYNTHETIC'."""
        executor = make_executor()
        event = make_hass_event(origin="LOCAL")
        cmd = make_invoke_handler_cmd(event=event)
        cmd.is_synthetic = True

        await executor._execute_handler(cmd)

        record = executor._write_queue.get_nowait()
        assert record.trigger_origin == SYNTHETIC_ORIGIN


class TestJobRecordFields:
    async def test_job_record_has_execution_id_no_trigger(self) -> None:
        """Job execution record has execution_id (UUIDv7) and no trigger fields."""
        executor = make_executor()
        cmd = make_execute_job_cmd()

        await executor._execute_job(cmd)

        record = executor._write_queue.get_nowait()
        assert record.execution_id is not None
        assert is_valid_uuid7(record.execution_id)
        # Unified ExecutionRecord carries trigger fields for all kinds; they are None for jobs.
        assert record.kind == "job"
        assert record.trigger_context_id is None
        assert record.trigger_origin is None


class TestErrorHandlerExecutionIdInheritance:
    async def test_error_handler_inherits_execution_id(self) -> None:
        """Spawned error handler task sees the same CURRENT_EXECUTION_ID as the main execution."""
        executor = make_executor()

        main_id: list[str | None] = []
        handler_id: list[str | None] = []

        async def capture_main(*_args) -> None:
            main_id.append(CURRENT_EXECUTION_ID.get())
            raise RuntimeError("trigger error handler")

        async def error_handler(_ctx) -> None:
            handler_id.append(CURRENT_EXECUTION_ID.get())

        listener = make_listener(side_effect=capture_main)
        listener.invoker.error_handler = error_handler
        cmd = make_invoke_handler_cmd(listener=listener)

        await executor._execute_handler(cmd)
        await drain_tasks(executor)

        assert len(main_id) == 1
        assert len(handler_id) == 1
        assert main_id[0] is not None
        assert main_id[0] == handler_id[0]
