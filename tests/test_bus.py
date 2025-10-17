# pyright: reportInvalidTypeArguments=none, reportArgumentType=none


import asyncio
import typing
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.core.resources.bus.listeners import Subscription
from hassette.core.resources.bus.predicates import AllOf, AttrChanged, EntityMatches, Guard, StateChanged
from hassette.core.resources.bus.predicates.event import CallServiceEventWrapper, KeyValueMatches
from hassette.events.base import Event

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette
    from hassette.core.resources.bus.bus import Bus


@pytest.fixture
def bus_instance(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource for the running Hassette harness."""
    return hassette_with_bus._bus


async def test_on_registers_listener_and_supports_unsubscribe(bus_instance: "Bus") -> None:
    """Bus.on wraps handlers, normalises predicates, and wires subscription cleanup."""

    async def handler(event):  # noqa
        await asyncio.sleep(0)

    add_listener_mock = Mock()
    remove_listener_mock = Mock()
    original_service = bus_instance.bus_service
    original_remove = bus_instance.remove_listener
    bus_instance.bus_service = Mock(add_listener=add_listener_mock)  # type: ignore[assignment]
    bus_instance.remove_listener = remove_listener_mock  # type: ignore[assignment]

    try:
        subscription = bus_instance.on(
            topic="demo.topic",
            handler=handler,
            where=[lambda _: True],
            args=("prefix",),
            kwargs={"suffix": "!"},
            once=True,
            debounce=0.1,
            throttle=0.2,
        )

        assert isinstance(subscription, Subscription)
        add_listener_mock.assert_called_once()
        listener = add_listener_mock.call_args.args[0]

        assert listener.topic == "demo.topic"
        assert listener.orig_handler is handler
        assert asyncio.iscoroutinefunction(listener.handler)
        assert listener.args == ("prefix",)
        assert listener.kwargs == {"suffix": "!"}
        assert listener.once is True
        assert listener.debounce == 0.1
        assert listener.throttle == 0.2
        assert isinstance(listener.predicate, AllOf)

        subscription.unsubscribe()
        remove_listener_mock.assert_called_once_with(listener)
    finally:
        bus_instance.bus_service = original_service  # type: ignore[assignment]
        bus_instance.remove_listener = original_remove  # type: ignore[assignment]


async def test_on_state_change_builds_predicates(bus_instance: "Bus") -> None:
    """on_state_change composes entity, state, and extra predicates."""
    extra_guard = Guard(lambda event: event.payload.topic == "any")

    subscription = bus_instance.on_state_change(
        "sensor.kitchen",
        handler=AsyncMock(),
        changed_from="off",
        changed_to="on",
        where=extra_guard,
        args=(),
        kwargs=None,
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)
    predicate_types = {type(pred) for pred in listener.predicate.predicates}
    assert EntityMatches in predicate_types
    assert StateChanged in predicate_types
    assert extra_guard in listener.predicate.predicates


async def test_on_attribute_change_targets_attribute(bus_instance: "Bus") -> None:
    """on_attribute_change adds AttrChanged predicate for the supplied attribute."""
    subscription = bus_instance.on_attribute_change(
        "light.office",
        "brightness",
        handler=AsyncMock(),
        changed_from=100,
        changed_to=200,
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)
    attr_predicates = [pred for pred in listener.predicate.predicates if isinstance(pred, AttrChanged)]
    assert attr_predicates, "Expected AttrChanged predicate to be included"
    attr_pred = attr_predicates[0]
    assert attr_pred.name == "brightness"
    assert attr_pred.from_ == 100
    assert attr_pred.to == 200


async def test_on_call_service_handles_mapping_predicates(bus_instance: "Bus") -> None:
    """on_call_service wraps mapping filters as KeyValueMatches within a CallServiceEventWrapper."""
    subscription = bus_instance.on_call_service(
        domain="light",
        service="turn_on",
        handler=AsyncMock(),
        where=[{"entity_id": "light.kitchen"}, lambda data: data.get("brightness", 0) > 150],
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)

    predicate_types = {type(pred) for pred in listener.predicate.predicates}
    assert Guard in predicate_types, "Expected domain/service guards"
    assert CallServiceEventWrapper in predicate_types, "Expected wrapper for mapping predicates"

    wrapper = next(pred for pred in listener.predicate.predicates if isinstance(pred, CallServiceEventWrapper))
    assert any(isinstance(pred, KeyValueMatches) for pred in wrapper.predicates)


async def test_once_listener_removed(hassette_with_bus) -> None:
    """Listeners registered with once=True are removed after the first invocation."""
    hassette = hassette_with_bus

    received_payloads: list[int] = []
    first_invocation = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:
        received_payloads.append(event.payload.value)
        first_invocation.set()

    hassette._bus.on(topic="custom.once", handler=handler, once=True)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=1)))

    await asyncio.wait_for(first_invocation.wait(), timeout=1)
    await asyncio.sleep(0.05)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=2)))

    await asyncio.sleep(0.1)

    assert received_payloads == [1], f"Expected handler to fire once with payload 1, got {received_payloads}"


async def test_bus_background_tasks_cleanup(hassette_with_bus) -> None:
    """Bus cleans up background tasks after a once handler completes."""
    hassette = hassette_with_bus

    event_received = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:  # noqa
        event_received.set()

    hassette._bus.on(topic="custom.cleanup", handler=handler, once=True)

    await hassette.send_event("custom.cleanup", Event(topic="custom.cleanup", payload=SimpleNamespace(value=9)))

    await asyncio.wait_for(event_received.wait(), timeout=1)
    await asyncio.sleep(0.1)

    assert len(hassette._bus.task_bucket) == 0, (
        f"Expected no leftover bus tasks, found {len(hassette._bus.task_bucket)}"
    )


async def test_bus_uses_args_kwargs(hassette_with_bus) -> None:
    """Handlers receive configured args and kwargs when invoked."""
    hassette = hassette_with_bus

    formatted_messages: list[str] = []
    event_processed = asyncio.Event()

    def handler(event: Event[SimpleNamespace], prefix: str, suffix: str) -> None:
        formatted_messages.append(f"{prefix}{event.payload.value}{suffix}")
        event_processed.set()

    hassette._bus.on(topic="custom.args", handler=handler, args=("Value: ",), kwargs={"suffix": "!"})

    await hassette.send_event("custom.args", Event(topic="custom.args", payload=SimpleNamespace(value="Test")))

    await asyncio.wait_for(event_processed.wait(), timeout=1)

    assert formatted_messages == ["Value: Test!"], (
        f"Expected handler to receive formatted value, got {formatted_messages}"
    )
