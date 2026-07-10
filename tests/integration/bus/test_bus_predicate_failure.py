"""Integration tests for bus predicate failure → ExecutionRecord + error handler routing (#1255).

Verifies that a raising where= predicate on a bus listener:
- Creates an ExecutionRecord with status='error' and correct error details
- Invokes the per-listener or app-level error handler with a BusErrorContext
- Does not crash sibling listeners in the same fanout (isolation from #1243)
- Records exactly once for glob-registered listeners (dedup across expanded routes)
"""

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

from hassette.bus.error_context import BusErrorContext
from hassette.events.base import Event
from hassette.test_utils import create_state_change_event, wait_for

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness


async def test_predicate_failure_enqueues_error_record(hassette_with_bus: "HassetteHarness") -> None:
    """A raising predicate produces an ExecutionRecord with status='error'."""
    hassette = hassette_with_bus
    bus = hassette.bus
    executor = hassette.bus_service._executor

    executor.enqueue_record.reset_mock()

    def bad_predicate(_event: object) -> bool:
        raise ZeroDivisionError("boom")

    async def handler(_event: Event) -> None:
        pass

    await bus.on(topic="test.pred_record", handler=handler, where=bad_predicate, name="pred_record")

    event = Event(topic="test.pred_record", payload=SimpleNamespace())
    await hassette.send_event(event)
    await wait_for(lambda: executor.enqueue_record.call_count > 0, desc="record enqueued")

    record = executor.enqueue_record.call_args[0][0]
    assert record.kind == "handler"
    assert record.status == "error"
    assert record.error_type == "ZeroDivisionError"
    assert record.error_message == "boom"
    assert record.error_traceback is not None
    assert "ZeroDivisionError" in record.error_traceback
    assert record.execution_id is not None


async def test_predicate_failure_invokes_per_listener_error_handler(hassette_with_bus: "HassetteHarness") -> None:
    """A raising predicate routes to the per-listener on_error handler."""
    hassette = hassette_with_bus
    bus = hassette.bus
    executor = hassette.bus_service._executor

    executor.invoke_error_handler.reset_mock()
    executor.enqueue_record.reset_mock()

    def bad_predicate(_event: object) -> bool:
        raise ValueError("pred failed")

    async def handler(_event: Event) -> None:
        pass

    async def on_error(ctx: BusErrorContext) -> None:
        pass

    await bus.on(
        topic="test.pred_per_listener",
        handler=handler,
        where=bad_predicate,
        on_error=on_error,
        name="pred_per_listener",
    )

    event = Event(topic="test.pred_per_listener", payload=SimpleNamespace())
    await hassette.send_event(event)
    await wait_for(lambda: executor.invoke_error_handler.call_count > 0, desc="error handler invoked")

    handler_arg, ctx = executor.invoke_error_handler.call_args[0]
    assert handler_arg is on_error
    assert isinstance(ctx, BusErrorContext)
    assert isinstance(ctx.exception, ValueError)
    assert str(ctx.exception) == "pred failed"
    assert ctx.topic == "test.pred_per_listener"
    assert ctx.execution_id is not None

    record = executor.enqueue_record.call_args[0][0]
    assert ctx.execution_id == record.execution_id


async def test_predicate_failure_invokes_app_level_error_handler(hassette_with_bus: "HassetteHarness") -> None:
    """When no per-listener handler exists, predicate failure routes to the app-level handler."""
    hassette = hassette_with_bus
    bus = hassette.bus
    executor = hassette.bus_service._executor

    executor.invoke_error_handler.reset_mock()

    def bad_predicate(_event: object) -> bool:
        raise RuntimeError("app level test")

    async def handler(_event: Event) -> None:
        pass

    async def app_on_error(ctx: BusErrorContext) -> None:
        pass

    bus.on_error(app_on_error)
    await bus.on(
        topic="test.pred_app_level",
        handler=handler,
        where=bad_predicate,
        name="pred_app_level",
    )

    event = Event(topic="test.pred_app_level", payload=SimpleNamespace())
    await hassette.send_event(event)
    await wait_for(lambda: executor.invoke_error_handler.call_count > 0, desc="app-level error handler invoked")

    handler_arg, ctx = executor.invoke_error_handler.call_args[0]
    assert handler_arg is app_on_error
    assert isinstance(ctx.exception, RuntimeError)


async def test_predicate_failure_does_not_crash_sibling_listeners(hassette_with_bus: "HassetteHarness") -> None:
    """A raising predicate on one listener does not prevent sibling listeners from firing."""
    hassette = hassette_with_bus
    bus = hassette.bus

    sibling_ran = asyncio.Event()

    def bad_predicate(_event: object) -> bool:
        raise TypeError("broken predicate")

    async def bad_handler(_event: Event) -> None:
        pass

    async def good_handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(sibling_ran.set)

    await bus.on(topic="test.pred_isolation", handler=bad_handler, where=bad_predicate, name="pred_isolation_bad")
    await bus.on(topic="test.pred_isolation", handler=good_handler, name="pred_isolation_good")

    event = Event(topic="test.pred_isolation", payload=SimpleNamespace())
    await hassette.send_event(event)

    await asyncio.wait_for(sibling_ran.wait(), timeout=2.0)


async def test_predicate_failure_no_error_handler_still_records(hassette_with_bus: "HassetteHarness") -> None:
    """When no error handler is registered, predicate failure still records but doesn't crash."""
    hassette = hassette_with_bus
    bus = hassette.bus
    executor = hassette.bus_service._executor

    bus._error_handler = None
    executor.enqueue_record.reset_mock()
    executor.invoke_error_handler.reset_mock()

    def bad_predicate(_event: object) -> bool:
        raise KeyError("no handler")

    async def handler(_event: Event) -> None:
        pass

    await bus.on(topic="test.pred_no_handler", handler=handler, where=bad_predicate, name="pred_no_handler")

    event = Event(topic="test.pred_no_handler", payload=SimpleNamespace())
    await hassette.send_event(event)
    await wait_for(lambda: executor.enqueue_record.call_count > 0, desc="record enqueued without error handler")

    record = executor.enqueue_record.call_args[0][0]
    assert record.status == "error"
    assert record.error_type == "KeyError"

    executor.invoke_error_handler.assert_not_called()


async def test_glob_listener_predicate_failure_recorded_once(hassette_with_bus: "HassetteHarness") -> None:
    """A glob-registered listener's predicate failure is recorded exactly once across expanded routes.

    State-changed events expand to three routes (entity, domain-glob, base). A glob listener
    matches on multiple routes — without dedup, the predicate would raise and record once per
    matching route.
    """
    hassette = hassette_with_bus
    bus = hassette.bus
    executor = hassette.bus_service._executor

    bus._error_handler = None
    executor.enqueue_record.reset_mock()
    executor.invoke_error_handler.reset_mock()

    call_count = 0

    def counting_bad_predicate(_event: object) -> bool:
        nonlocal call_count
        call_count += 1
        raise ValueError("glob boom")

    async def handler(_event: Event) -> None:
        pass

    await bus.on_state_change(
        "light.*",
        handler=handler,
        where=counting_bad_predicate,
        name="glob_pred_failure",
    )

    event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")
    await hassette.send_event(event)
    await wait_for(lambda: executor.enqueue_record.call_count > 0, desc="record enqueued for glob listener")

    assert call_count == 1, f"Predicate evaluated {call_count} times, expected exactly 1"
    assert executor.enqueue_record.call_count == 1, (
        f"ExecutionRecord enqueued {executor.enqueue_record.call_count} times, expected exactly 1"
    )
