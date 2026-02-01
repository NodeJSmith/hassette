# pyright: reportInvalidTypeArguments=none, reportArgumentType=none


import asyncio
import contextlib
import typing
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from hassette import RawStateChangeEvent
from hassette.bus.listeners import Subscription
from hassette.event_handling.conditions import IsOrContains
from hassette.event_handling.predicates import (
    AllOf,
    AttrDidChange,
    EntityMatches,
    Guard,
    ServiceDataWhere,
    StateDidChange,
)
from hassette.events.base import Event
from hassette.test_utils.helpers import create_call_service_event, create_state_change_event
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus


@pytest.fixture
def bus_instance(hassette_with_bus: "Hassette") -> "Bus":
    """Return the Bus resource for the running Hassette harness."""
    return hassette_with_bus._bus


@pytest.mark.parametrize(("debounce", "throttle"), [(0.1, None), (None, 0.1), (None, None)])
async def test_on_registers_listener_and_supports_unsubscribe(
    bus_instance: "Bus", debounce: float | None, throttle: float | None
) -> None:
    """Bus.on wraps handlers, normalises predicates, and wires subscription cleanup."""

    async def handler(event):  # noqa
        await asyncio.sleep(0)

    add_listener_mock = Mock()
    remove_listener_mock = Mock()
    original_service = bus_instance.bus_service
    original_remove = bus_instance.remove_listener
    bus_instance.bus_service = Mock(add_listener=add_listener_mock)
    bus_instance.remove_listener = remove_listener_mock

    try:
        subscription = bus_instance.on(
            topic="demo.topic",
            handler=handler,
            where=[lambda _: True],
            kwargs={"suffix": "!"},
            once=True,
            debounce=debounce,
            throttle=throttle,
        )

        assert isinstance(subscription, Subscription)
        add_listener_mock.assert_called_once()
        listener = add_listener_mock.call_args.args[0]

        assert listener.topic == "demo.topic"
        assert listener.orig_handler is handler
        assert asyncio.iscoroutinefunction(listener.adapter.handler)
        assert listener.kwargs == {"suffix": "!"}
        assert listener.once is True
        assert isinstance(listener.predicate, AllOf)

        subscription.unsubscribe()
        remove_listener_mock.assert_called_once_with(listener)
    finally:
        bus_instance.bus_service = original_service
        bus_instance.remove_listener = original_remove


async def test_on_state_change_builds_predicates(bus_instance: "Bus") -> None:
    """on_state_change composes entity, state, and extra predicates."""

    def handler(event: Event) -> None:
        pass

    subscription = bus_instance.on_state_change(
        "sensor.kitchen",
        handler=handler,
        changed_from="off",
        changed_to="on",
        kwargs=None,
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)
    preds = listener.predicate.predicates
    assert any(isinstance(pred, EntityMatches) for pred in preds)
    assert any(isinstance(pred, StateDidChange) for pred in preds)

    matching_event = create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on")
    assert listener.predicate(matching_event) is True

    non_matching_event = create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="off")
    assert listener.predicate(non_matching_event) is False


async def test_on_attribute_change_targets_attribute(bus_instance: "Bus") -> None:
    """on_attribute_change adds AttrDidChange predicate for the supplied attribute."""

    def handler(event: Event) -> None:
        pass

    subscription = bus_instance.on_attribute_change(
        "light.office",
        "brightness",
        handler=handler,
        changed_from=100,
        changed_to=200,
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)
    attr_predicates = [pred for pred in listener.predicate.predicates if isinstance(pred, AttrDidChange)]
    assert attr_predicates, "Expected AttrDidChange predicate to be included"
    attr_pred = attr_predicates[0]
    assert attr_pred.attr_name == "brightness"

    matching_event = create_state_change_event(
        entity_id="light.office",
        old_value=0,
        new_value=0,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )
    assert listener.predicate(matching_event) is True

    non_matching_event = create_state_change_event(
        entity_id="light.office",
        old_value=0,
        new_value=0,
        old_attrs={"brightness": 90},
        new_attrs={"brightness": 200},
    )
    assert listener.predicate(non_matching_event) is False


async def test_on_call_service_handles_mapping_predicates(bus_instance: "Bus") -> None:
    """on_call_service composes domain/service guards with ServiceDataWhere and extra predicates."""

    def handler(event: Event) -> None:
        pass

    extra_guard = Guard(lambda event: event.payload.data.service_data.get("brightness", 0) > 150)
    subscription = bus_instance.on_call_service(
        domain="light",
        service="turn_on",
        handler=handler,
        where=[{"entity_id": IsOrContains("light.kitchen")}, extra_guard],
    )

    listener = subscription.listener
    assert isinstance(listener.predicate, AllOf)

    assert any(isinstance(pred, ServiceDataWhere) for pred in listener.predicate.predicates)

    matching_event = create_call_service_event(
        domain="light",
        service="turn_on",
        service_data={"entity_id": ["light.kitchen"], "brightness": 255},
    )
    assert listener.predicate(matching_event) is True

    wrong_entity_event = create_call_service_event(
        domain="light",
        service="turn_on",
        service_data={"entity_id": ["light.other"], "brightness": 255},
    )
    assert listener.predicate(wrong_entity_event) is False

    wrong_service_event = create_call_service_event(
        domain="light",
        service="turn_off",
        service_data={"entity_id": ["light.kitchen"], "brightness": 255},
    )
    assert listener.predicate(wrong_service_event) is False


async def test_once_listener_removed(hassette_with_bus: "Hassette") -> None:
    """Listeners registered with once=True are removed after the first invocation."""
    hassette = hassette_with_bus

    received_payloads: list[int] = []
    first_invocation = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:
        received_payloads.append(event.payload.value)
        hassette_with_bus.task_bucket.post_to_loop(first_invocation.set)

    hassette._bus.on(topic="custom.once", handler=handler, once=True)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=1)))

    await asyncio.wait_for(first_invocation.wait(), timeout=1)
    await asyncio.sleep(0.05)

    await hassette.send_event("custom.once", Event(topic="custom.once", payload=SimpleNamespace(value=2)))

    await asyncio.sleep(0.1)

    assert received_payloads == [1], f"Expected handler to fire once with payload 1, got {received_payloads}"


async def test_bus_background_tasks_cleanup(hassette_with_bus: "Hassette") -> None:
    """Bus cleans up background tasks after a once handler completes."""
    hassette = hassette_with_bus

    event_received = asyncio.Event()

    async def handler(event: Event[SimpleNamespace]) -> None:  # noqa
        hassette_with_bus.task_bucket.post_to_loop(event_received.set)

    hassette._bus.on(topic="custom.cleanup", handler=handler, once=True)

    await hassette.send_event("custom.cleanup", Event(topic="custom.cleanup", payload=SimpleNamespace(value=9)))

    await asyncio.wait_for(event_received.wait(), timeout=1)
    await asyncio.sleep(0.1)

    assert len(hassette._bus.task_bucket) == 0, (
        f"Expected no leftover bus tasks, found {len(hassette._bus.task_bucket)}"
    )


async def test_bus_uses_kwargs(hassette_with_bus: "Hassette") -> None:
    """Handlers receive configured args and kwargs when invoked."""
    hassette = hassette_with_bus

    formatted_messages: list[str] = []
    event_processed = asyncio.Event()

    def handler(event: Event[SimpleNamespace], suffix: str) -> None:
        formatted_messages.append(f"Value: {event.payload.value}{suffix}")
        hassette_with_bus.task_bucket.post_to_loop(event_processed.set)

    hassette._bus.on(topic="custom.args", handler=handler, kwargs={"suffix": "!"})

    await hassette.send_event("custom.args", Event(topic="custom.args", payload=SimpleNamespace(value="Test")))

    await asyncio.wait_for(event_processed.wait(), timeout=1)

    assert formatted_messages == ["Value: Test!"], (
        f"Expected handler to receive formatted value, got {formatted_messages}"
    )


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.kitchen", "sensor.kitchen"),
        ("sensor.*", {"sensor.kitchen", "sensor.living_room"}),
        ("*.kitchen", {"sensor.kitchen", "light.kitchen"}),
        ("*kitchen*", {"sensor.kitchen", "light.kitchen"}),
        ("sensor.kitch?n", "sensor.kitchen"),
        ("senso?.kit*en", "sensor.kitchen"),
        ("*", {"sensor.kitchen", "light.living_room", "switch.garage", "light.kitchen", "sensor.living_room"}),
    ],
)
async def test_state_change_handles_globs(
    hassette_with_bus: "Hassette", entity_id: str, expected: str | set[str]
) -> None:
    """Bus matches state change with glob patterns correctly."""
    hassette = hassette_with_bus

    expected = {expected} if isinstance(expected, str) else expected

    received_entity_ids: list[str] = []
    events_processed = asyncio.Event()

    def handler(event: RawStateChangeEvent) -> None:
        received_entity_ids.append(event.payload.entity_id)
        if set(received_entity_ids) == expected:
            hassette_with_bus.task_bucket.post_to_loop(events_processed.set)

    hassette._bus.on_state_change(entity_id=entity_id, handler=handler)

    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="light.living_room", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="sensor.living_room", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="switch.garage", old_value="off", new_value="on"),
    )

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(events_processed.wait(), timeout=0.2)

    actual = set(received_entity_ids)

    assert actual == expected, f"Expected handler to receive {expected}, got {actual}"


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.kitchen", "sensor.kitchen"),
        ("sensor.*", {"sensor.kitchen", "sensor.living_room"}),
        ("*.kitchen", {"sensor.kitchen", "light.kitchen"}),
        ("*kitchen*", {"sensor.kitchen", "light.kitchen"}),
        ("sensor.kitch?n", "sensor.kitchen"),
        ("senso?.kit*en", "sensor.kitchen"),
        ("*", {"sensor.kitchen", "light.living_room", "switch.garage", "light.kitchen", "sensor.living_room"}),
    ],
)
async def test_attribute_change_handles_globs(
    hassette_with_bus: "Hassette", entity_id: str, expected: str | set[str]
) -> None:
    """Bus matches attribute change topics with glob patterns correctly."""
    hassette = hassette_with_bus

    expected = {expected} if isinstance(expected, str) else expected

    received_entity_ids: list[str] = []
    events_processed = asyncio.Event()

    def handler(event: RawStateChangeEvent) -> None:
        received_entity_ids.append(event.payload.entity_id)
        if set(received_entity_ids) == expected:
            hassette_with_bus.task_bucket.post_to_loop(events_processed.set)

    hassette._bus.on_attribute_change(entity_id=entity_id, attr="friendly_name", handler=handler)

    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="sensor.kitchen", old_value="off", new_value="on", new_attrs={"friendly_name": "Kitchen Sensor"}
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="light.kitchen", old_value="off", new_value="on", new_attrs={"friendly_name": "Kitchen Light"}
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="light.living_room",
            old_value="off",
            new_value="on",
            new_attrs={"friendly_name": "Living Room Light"},
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="sensor.living_room",
            old_value="off",
            new_value="on",
            new_attrs={"friendly_name": "Living Room Sensor"},
        ),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(
            entity_id="switch.garage", old_value="off", new_value="on", new_attrs={"friendly_name": "Garage Switch"}
        ),
    )

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(events_processed.wait(), timeout=0.2)

    actual = set(received_entity_ids)

    assert actual == expected, f"Expected handler to receive {expected}, got {actual}"


async def test_can_subscribe_to_all_state_change_events(hassette_with_bus: "Hassette") -> None:
    """Bus can subscribe to all state change events."""
    hassette = hassette_with_bus

    expected = {"sensor.kitchen", "light.living_room", "switch.garage"}
    received_entity_ids: list[str] = []
    events_processed = asyncio.Event()

    def handler(event: RawStateChangeEvent) -> None:
        received_entity_ids.append(event.payload.entity_id)
        if set(received_entity_ids) == expected:
            hassette_with_bus.task_bucket.post_to_loop(events_processed.set)

    hassette._bus.on_state_change(entity_id="*", handler=handler)

    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="light.living_room", old_value="off", new_value="on"),
    )
    await hassette.send_event(
        Topic.HASS_EVENT_STATE_CHANGED,
        create_state_change_event(entity_id="switch.garage", old_value="off", new_value="on"),
    )

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(events_processed.wait(), timeout=0.2)

    actual = set(received_entity_ids)

    assert actual == expected, f"Expected handler to receive {expected}, got {actual}"
