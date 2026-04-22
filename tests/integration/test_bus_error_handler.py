"""Integration tests for bus error handler precedence and routing via HassetteHarness."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from hassette.bus.error_context import BusErrorContext
from hassette.events.base import Event
from hassette.test_utils import create_state_change_event, wait_for

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus


@pytest.fixture
def bus(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource for the running Hassette harness."""
    return hassette_with_bus._bus


async def test_app_level_error_handler_called_on_failure(hassette_with_bus: "Hassette") -> None:
    """App-level handler registered via bus.on_error() is called when a listener raises."""
    hassette = hassette_with_bus
    bus = hassette._bus

    error_contexts: list[BusErrorContext] = []
    handler_ran = asyncio.Event()

    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(handler_ran.set)

    async def bad_handler(_event: Event) -> None:
        raise ValueError("listener failed")

    bus.on_error(on_error)
    bus.on(topic="test.app_level", handler=bad_handler)

    event = create_state_change_event(entity_id="sensor.test", old_value="off", new_value="on")
    await hassette.send_event("test.app_level", event)

    await asyncio.wait_for(handler_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, ValueError)
    assert str(error_contexts[0].exception) == "listener failed"
    assert error_contexts[0].topic == "test.app_level"


async def test_per_listener_error_handler_wins(hassette_with_bus: "Hassette") -> None:
    """Per-registration on_error= takes precedence over the app-level handler."""
    hassette = hassette_with_bus
    bus = hassette._bus

    app_level_calls: list[BusErrorContext] = []
    per_listener_calls: list[BusErrorContext] = []
    per_listener_ran = asyncio.Event()

    async def app_level_handler(ctx: BusErrorContext) -> None:
        app_level_calls.append(ctx)

    async def per_listener_handler(ctx: BusErrorContext) -> None:
        per_listener_calls.append(ctx)
        hassette.task_bucket.post_to_loop(per_listener_ran.set)

    async def bad_handler(_event: Event) -> None:
        raise RuntimeError("per-listener failure")

    bus.on_error(app_level_handler)
    bus.on(topic="test.per_listener", handler=bad_handler, on_error=per_listener_handler)

    event = create_state_change_event(entity_id="sensor.test", old_value="off", new_value="on")
    await hassette.send_event("test.per_listener", event)

    await asyncio.wait_for(per_listener_ran.wait(), timeout=2.0)

    # Allow a brief window to verify app-level handler was NOT called
    await asyncio.sleep(0.05)

    assert len(per_listener_calls) == 1, f"Expected 1 per-listener call, got {len(per_listener_calls)}"
    assert len(app_level_calls) == 0, "App-level handler should not be called when per-listener wins"
    assert isinstance(per_listener_calls[0].exception, RuntimeError)


async def test_no_handler_framework_default_behavior(hassette_with_bus: "Hassette") -> None:
    """When no error handler is registered, listener failure does not crash the harness."""
    hassette = hassette_with_bus
    bus = hassette._bus

    completed = asyncio.Event()

    async def bad_handler(_event: Event) -> None:
        hassette.task_bucket.post_to_loop(completed.set)
        raise KeyError("unhandled error")

    bus.on(topic="test.no_handler", handler=bad_handler)

    event = create_state_change_event(entity_id="sensor.test", old_value="off", new_value="on")
    await hassette.send_event("test.no_handler", event)

    # Handler ran (exception was raised) and harness didn't crash
    await asyncio.wait_for(completed.wait(), timeout=2.0)
    await wait_for(lambda: len(hassette._bus.task_bucket) == 0, desc="bus tasks drained")


async def test_multiple_listeners_different_handlers(hassette_with_bus: "Hassette") -> None:
    """Multiple listeners on the same bus can have different per-registration error handlers."""
    hassette = hassette_with_bus
    bus = hassette._bus

    calls_a: list[BusErrorContext] = []
    calls_b: list[BusErrorContext] = []
    both_ran = asyncio.Event()

    call_count = 0

    async def handler_a(ctx: BusErrorContext) -> None:
        calls_a.append(ctx)
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            hassette.task_bucket.post_to_loop(both_ran.set)

    async def handler_b(ctx: BusErrorContext) -> None:
        calls_b.append(ctx)
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            hassette.task_bucket.post_to_loop(both_ran.set)

    async def fail_a(_event: Event) -> None:
        raise ValueError("fail A")

    async def fail_b(_event: Event) -> None:
        raise TypeError("fail B")

    bus.on(topic="test.multi_a", handler=fail_a, on_error=handler_a)
    bus.on(topic="test.multi_b", handler=fail_b, on_error=handler_b)

    ev = create_state_change_event(entity_id="sensor.test", old_value="off", new_value="on")
    await hassette.send_event("test.multi_a", ev)
    await hassette.send_event("test.multi_b", ev)

    await asyncio.wait_for(both_ran.wait(), timeout=2.0)

    assert len(calls_a) == 1
    assert len(calls_b) == 1
    assert isinstance(calls_a[0].exception, ValueError)
    assert isinstance(calls_b[0].exception, TypeError)


async def test_on_error_registered_after_listeners_still_works(hassette_with_bus: "Hassette") -> None:
    """on_error() registered AFTER listeners is resolved at dispatch time — it still fires (FR11)."""
    hassette = hassette_with_bus
    bus = hassette._bus

    error_contexts: list[BusErrorContext] = []
    handler_ran = asyncio.Event()

    async def bad_handler(_event: Event) -> None:
        raise AttributeError("late registration test")

    # Register the listener BEFORE calling on_error()
    bus.on(topic="test.late_registration", handler=bad_handler)

    # Register error handler AFTER the listener
    async def on_error(ctx: BusErrorContext) -> None:
        error_contexts.append(ctx)
        hassette.task_bucket.post_to_loop(handler_ran.set)

    bus.on_error(on_error)

    event = create_state_change_event(entity_id="sensor.test", old_value="off", new_value="on")
    await hassette.send_event("test.late_registration", event)

    await asyncio.wait_for(handler_ran.wait(), timeout=2.0)

    assert len(error_contexts) == 1
    assert isinstance(error_contexts[0].exception, AttributeError)
    assert "late registration test" in str(error_contexts[0].exception)
