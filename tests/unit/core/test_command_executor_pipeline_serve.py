"""Unit tests for CommandExecutor write-pipeline serve loop and completion events.

Companion files: ``test_command_executor_pipeline_queue.py`` covers the bounded queue and
retry/backoff behavior; ``test_command_executor_pipeline_persist.py`` covers ``build_record``
and flush/persist behavior. Together these three files replace the former
``test_command_executor_pipeline.py``.

Tests cover:
- serve() timer-based flush (#657)
- record_blocking_event graceful handling when database_service is uninitialized
- emit_completion_events warning for unowned (empty app_key) records
"""

import asyncio
import contextlib
import time
from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hassette.core.block_io_guard import MonkeypatchEvent
from hassette.core.command_executor import CommandExecutor
from hassette.test_utils import make_controlled_clock
from hassette.test_utils.factories import make_execution_record

from .conftest import init_executor, make_invocation


async def run_serve_until(executor: CommandExecutor, stopper_coro: Coroutine[Any, Any, Any]) -> None:
    """Run executor.serve() alongside a background task that eventually sets shutdown_event,
    then cancel and drain the stopper task cleanly. Shared by the serve() loop tests below,
    which differ only in what the stopper task waits for before signaling shutdown.
    """
    stopper = asyncio.create_task(stopper_coro)
    await executor.serve()
    stopper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stopper


def make_executor_with_send_event(queue_max: int = 10) -> CommandExecutor:
    """CommandExecutor with hassette.send_event mocked, for emit_completion_events tests."""
    executor = init_executor(queue_max=queue_max)
    executor.hassette.send_event = AsyncMock()
    return executor


async def test_serve_loops_without_blocking_when_queue_empty():
    """serve() does not block indefinitely when the queue is empty — the timer causes it to loop."""
    # dup-ignore-start: executor + recorder-stub setup (drain_calls list + fake_drain callback)
    # repeated across the serve() loop tests below. test_serve_timer_drains_items_added_during_drain
    # needs bespoke re-enqueue logic inside its callback, so a shared factory would still need
    # an escape hatch for that one case — not worth the indirection to save these lines twice.
    executor = init_executor()

    # Queue stays empty; the timer should fire and allow the loop to continue (and eventually shut down)
    drain_calls: list[str] = []

    async def fake_drain(first_item=None):
        drain_calls.append("timer" if first_item is None else "item")

    # dup-ignore-end

    shutdown_event = asyncio.Event()
    executor.shutdown_event = shutdown_event  # pyright: ignore[reportAttributeAccessIssue]

    executor.drain_and_persist = fake_drain  # pyright: ignore[reportAttributeAccessIssue]
    executor.flush_queue = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.config.database.max_flush_interval_seconds = 0.05  # very short — timer fires quickly

    # Shut down after two timer cycles; if max_flush_interval_seconds is honoured the whole
    # serve() call completes in well under 1s.  If it were ignored (infinite wait),
    # the test would hang until pytest's overall timeout killed it.
    async def stop_after_two_cycles():
        await asyncio.sleep(0.15)
        shutdown_event.set()

    await run_serve_until(executor, stop_after_two_cycles())

    # No drains expected (queue was empty), but serve() must have returned in time
    assert not drain_calls


async def test_serve_timer_drains_items_added_during_drain():
    """Items put back into the queue during drain_and_persist (e.g. deferred retries) are
    picked up on the next loop iteration, not lost.
    """
    # dup-ignore-start: executor + recorder-stub setup — see the matching comment in
    # test_serve_loops_without_blocking_when_queue_empty above. This occurrence needs its own
    # bespoke re-enqueue branch inside fake_drain, which is exactly why a shared factory isn't
    # worth it across all three serve() loop tests.
    executor = init_executor()

    # First item to seed the initial drain
    inv1 = make_invocation(listener_id=1, session_id=1)
    inv2 = make_invocation(listener_id=2, session_id=1)
    executor._write_queue.put_nowait(inv1)

    drain_calls: list[str] = []

    async def fake_drain(first_item=None):
        drain_calls.append("timer" if first_item is None else "item")
        if len(drain_calls) == 1:
            # Simulate a deferred retry being re-enqueued during the first drain
            executor._write_queue.put_nowait(inv2)

    # dup-ignore-end

    shutdown_event = asyncio.Event()
    executor.shutdown_event = shutdown_event  # pyright: ignore[reportAttributeAccessIssue]

    executor.drain_and_persist = fake_drain  # pyright: ignore[reportAttributeAccessIssue]
    executor.flush_queue = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.config.database.max_flush_interval_seconds = 5.0  # long — rely on item arrival, not timer

    async def stop_after_two_drains():
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(drain_calls) >= 2:
                break
        shutdown_event.set()

    await run_serve_until(executor, stop_after_two_drains())

    # Both drains should have been item-triggered (the re-enqueued item is picked up by queue.get)
    assert len(drain_calls) >= 2
    assert all(d == "item" for d in drain_calls)


async def test_serve_item_flush_drains_queue_on_arrival():
    """serve() drains via first_item path when a queue item arrives before timeout."""
    # dup-ignore-start: executor + recorder-stub setup — see the matching comment in
    # test_serve_loops_without_blocking_when_queue_empty above.
    executor = init_executor()

    drain_calls: list[str] = []

    async def fake_drain(first_item=None):
        drain_calls.append("timer" if first_item is None else "item")

    # dup-ignore-end

    shutdown_event = asyncio.Event()
    executor.shutdown_event = shutdown_event  # pyright: ignore[reportAttributeAccessIssue]

    executor.drain_and_persist = fake_drain  # pyright: ignore[reportAttributeAccessIssue]
    executor.flush_queue = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.config.database.max_flush_interval_seconds = 5.0  # long interval — item should arrive first

    async def enqueue_then_stop():
        await asyncio.sleep(0.01)
        executor._write_queue.put_nowait(make_invocation(listener_id=1, session_id=1))
        # wait for drain, then shut down
        for _ in range(100):
            await asyncio.sleep(0.01)
            if drain_calls:
                break
        shutdown_event.set()

    await run_serve_until(executor, enqueue_then_stop())

    assert "item" in drain_calls


def test_record_blocking_event_swallows_uninitialized_db() -> None:
    """record_blocking_event is fire-and-forget: a not-yet-initialized database_service
    (``enqueue`` raises ``RuntimeError`` before ``on_initialize``) drops the row and never propagates.

    Regression: the Tier 2 monkeypatch guard wraps ``socket.send``. When it fired while the
    DatabaseService queue was still ``None`` (early startup, shutdown, or the test harness's own
    xdist/rerunfailures socket IPC), the raised ``RuntimeError`` escaped through ``_detect`` into the
    wrapped primitive and crashed the whole caller (pytest INTERNALERROR on 3.11).
    """
    executor = init_executor()
    # Repository returns an opaque handle; the real coroutine is closed by enqueue() in production.
    executor.repository.insert_blocking_event = MagicMock(return_value=MagicMock())
    executor.hassette.database_service.enqueue = MagicMock(
        side_effect=RuntimeError("DatabaseService.enqueue() called before on_initialize()")
    )

    event = MonkeypatchEvent(
        primitive="socket.send",
        source_location="app.py:10",
        app_key="test_app",
        instance_name="default",
        instance_index=0,
        execution_id="01abc",
        tier="monkeypatch",
        detected_at=time.time(),
        reason="attributed",
    )

    # Must not raise — the observational guard path cannot crash the wrapped primitive.
    CommandExecutor.record_blocking_event(executor, event)

    executor.hassette.database_service.enqueue.assert_called_once()


async def test_emit_completion_events_no_warning_for_owned_records() -> None:
    """Normal app-tier records with a populated app_key never trigger the empty-app_key warning."""
    executor = make_executor_with_send_event()

    owned = make_execution_record(app_key="my_app", source_tier="app")
    await CommandExecutor.emit_completion_events(executor, [owned])

    assert executor._last_unowned_warn_ts is None
    executor.hassette.send_event.assert_awaited_once()


async def test_emit_completion_events_no_warning_for_framework_tier_empty_app_key() -> None:
    """Framework-tier records legitimately carry an empty app_key — not the starvation window
    this warning guards against, so it must not fire.
    """
    executor = make_executor_with_send_event()

    framework_record = make_execution_record(app_key="", source_tier="framework")
    await CommandExecutor.emit_completion_events(executor, [framework_record])

    assert executor._last_unowned_warn_ts is None


async def test_emit_completion_events_warns_on_empty_app_key() -> None:
    """An app-tier record with empty app_key (registration meta-miss, e.g. an app reload
    racing the completion event) logs a WARNING.
    """
    executor = make_executor_with_send_event()
    executor._clock = make_controlled_clock(start=1.0)

    unowned = make_execution_record(app_key="", source_tier="app")
    await CommandExecutor.emit_completion_events(executor, [unowned])

    assert executor._last_unowned_warn_ts == 1.0


async def test_emit_completion_events_unowned_warning_rate_limited() -> None:
    """Repeated empty-app_key batches within the suppression window log only once."""
    executor = make_executor_with_send_event()
    clock = make_controlled_clock(start=100.0)
    executor._clock = clock
    unowned = make_execution_record(app_key="", source_tier="app")

    await CommandExecutor.emit_completion_events(executor, [unowned])
    clock.advance_to(101.0)
    await CommandExecutor.emit_completion_events(executor, [unowned])  # suppressed
    clock.advance_to(102.0)
    await CommandExecutor.emit_completion_events(executor, [unowned])  # still suppressed

    assert executor._last_unowned_warn_ts == 100.0


async def test_emit_completion_events_unowned_warning_fires_after_rate_limit_window() -> None:
    """A second empty-app_key batch after the suppression window elapses logs again."""
    executor = make_executor_with_send_event()
    clock = make_controlled_clock(start=100.0)
    executor._clock = clock
    unowned = make_execution_record(app_key="", source_tier="app")

    await CommandExecutor.emit_completion_events(executor, [unowned])
    assert executor._last_unowned_warn_ts == 100.0

    clock.advance_to(129.999)
    await CommandExecutor.emit_completion_events(executor, [unowned])
    assert executor._last_unowned_warn_ts == 100.0

    clock.advance_to(130.0)
    await CommandExecutor.emit_completion_events(executor, [unowned])

    assert executor._last_unowned_warn_ts == 130.0
