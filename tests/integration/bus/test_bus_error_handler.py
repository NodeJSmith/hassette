"""Integration tests for bus error handler precedence and routing via HassetteHarness."""

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

from hassette.events.base import AnyEvent, Event
from hassette.testing import create_call_service_event, wait_for
from tests.support.helpers import settle

from .helpers import ErrorCollector

if TYPE_CHECKING:
    from hassette.testing import HassetteHarness


async def test_app_level_error_handler_called_on_failure(hassette_with_bus: "HassetteHarness") -> None:
    """App-level handler registered via bus.on_error() is called when a listener raises."""
    hassette = hassette_with_bus
    bus = hassette.bus

    errors = ErrorCollector()

    async def bad_handler(_event: AnyEvent) -> None:
        raise ValueError("listener failed")

    bus.on_error(errors.bound(hassette))
    await bus.on(topic="test.app_level", handler=bad_handler, name="app_level_bad_handler")

    event = Event(topic="test.app_level", payload=SimpleNamespace())
    await hassette.send_event(event)

    await errors.wait()

    ctx = errors.single(ValueError)
    assert str(ctx.exception) == "listener failed"
    assert ctx.topic == "test.app_level"


async def test_per_listener_error_handler_wins(hassette_with_bus: "HassetteHarness") -> None:
    """Per-registration on_error= takes precedence over the app-level handler."""
    hassette = hassette_with_bus
    bus = hassette.bus

    app_level = ErrorCollector()
    per_listener = ErrorCollector()

    async def bad_handler(_event: AnyEvent) -> None:
        raise RuntimeError("per-listener failure")

    bus.on_error(app_level.bound(hassette))
    await bus.on(
        topic="test.per_listener",
        handler=bad_handler,
        on_error=per_listener.bound(hassette),
        name="per_listener_bad_handler",
    )

    event = Event(topic="test.per_listener", payload=SimpleNamespace())
    await hassette.send_event(event)

    await per_listener.wait()

    await settle()

    per_listener.single(RuntimeError)
    assert not app_level.contexts, "App-level handler should not be called when per-listener wins"


async def test_no_handler_framework_default_behavior(hassette_with_bus: "HassetteHarness") -> None:
    """When no error handler is registered, listener failure does not crash the harness."""
    hassette = hassette_with_bus
    bus = hassette.bus

    completed = asyncio.Event()

    async def bad_handler(_event: AnyEvent) -> None:
        hassette.task_bucket.post_to_loop(completed.set)
        raise KeyError("unhandled error")

    await bus.on(topic="test.no_handler", handler=bad_handler, name="no_handler_bad_handler")

    event = Event(topic="test.no_handler", payload=SimpleNamespace())
    await hassette.send_event(event)

    # Handler ran (exception was raised) and harness didn't crash
    await asyncio.wait_for(completed.wait(), timeout=2.0)
    await wait_for(lambda: len(hassette.bus.task_bucket) == 0, desc="bus tasks drained")


async def test_multiple_listeners_different_handlers(hassette_with_bus: "HassetteHarness") -> None:
    """Multiple listeners on the same bus can have different per-registration error handlers."""
    hassette = hassette_with_bus
    bus = hassette.bus

    errors_a = ErrorCollector()
    errors_b = ErrorCollector()

    async def fail_a(_event: AnyEvent) -> None:
        raise ValueError("fail A")

    async def fail_b(_event: AnyEvent) -> None:
        raise TypeError("fail B")

    await bus.on(topic="test.multi_a", handler=fail_a, on_error=errors_a.bound(hassette), name="multi_fail_a")
    await bus.on(topic="test.multi_b", handler=fail_b, on_error=errors_b.bound(hassette), name="multi_fail_b")

    await hassette.send_event(Event(topic="test.multi_a", payload=SimpleNamespace()))
    await hassette.send_event(Event(topic="test.multi_b", payload=SimpleNamespace()))

    await errors_a.wait()
    await errors_b.wait()

    errors_a.single(ValueError)
    errors_b.single(TypeError)


async def test_on_error_registered_after_listeners_still_works(hassette_with_bus: "HassetteHarness") -> None:
    """on_error() registered AFTER listeners is resolved at dispatch time — it still fires."""
    hassette = hassette_with_bus
    bus = hassette.bus

    errors = ErrorCollector()

    async def bad_handler(_event: AnyEvent) -> None:
        raise AttributeError("late registration test")

    # Register the listener BEFORE calling on_error()
    await bus.on(topic="test.late_registration", handler=bad_handler, name="late_registration_bad_handler")

    # Register error handler AFTER the listener
    bus.on_error(errors.bound(hassette))

    event = Event(topic="test.late_registration", payload=SimpleNamespace())
    await hassette.send_event(event)

    await errors.wait()

    ctx = errors.single(AttributeError)
    assert "late registration test" in str(ctx.exception)


async def test_on_error_after_multiple_listeners_applies_to_all(hassette_with_bus: "HassetteHarness") -> None:
    """on_error() registered after multiple listeners applies to all of them (lazy resolution)."""
    hassette = hassette_with_bus
    bus = hassette.bus

    errors = ErrorCollector(expected=2)

    async def bad_handler_a(_event: AnyEvent) -> None:
        raise ValueError("listener A failed")

    async def bad_handler_b(_event: AnyEvent) -> None:
        raise TypeError("listener B failed")

    await bus.on(topic="test.multi_late.a", handler=bad_handler_a, name="multi_late_a")
    await bus.on(topic="test.multi_late.b", handler=bad_handler_b, name="multi_late_b")

    bus.on_error(errors.bound(hassette))

    await hassette.send_event(Event(topic="test.multi_late.a", payload=SimpleNamespace()))
    await hassette.send_event(Event(topic="test.multi_late.b", payload=SimpleNamespace()))

    await errors.wait()

    assert len(errors.contexts) == 2
    exception_types = {type(ctx.exception) for ctx in errors.contexts}
    assert exception_types == {ValueError, TypeError}


async def test_on_call_service_error_handler(hassette_with_bus: "HassetteHarness") -> None:
    """on_call_service with on_error= routes handler exceptions to the error handler."""
    hassette = hassette_with_bus
    bus = hassette.bus

    errors = ErrorCollector()

    async def bad_handler(_event: AnyEvent) -> None:
        raise ValueError("service handler failed")

    await bus.on_call_service(
        domain="light",
        service="turn_on",
        handler=bad_handler,
        on_error=errors.bound(hassette),
        name="on_call_service_error_handler",
    )

    event = create_call_service_event(domain="light", service="turn_on")
    await hassette.send_event(event)

    await errors.wait()

    ctx = errors.single(ValueError)
    assert str(ctx.exception) == "service handler failed"
    assert ctx.topic == "hass.event.call_service"
