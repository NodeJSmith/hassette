import asyncio
import contextlib
import typing
from collections.abc import Callable, Coroutine
from logging import getLogger
from typing import Any, cast

import pytest
from anyio import create_memory_object_stream
from whenever import Instant

from hassette.core.bus.bus import Bus, _Bus
from hassette.core.bus.predicates.common import HomeAssistantRestarted
from hassette.core.core import Event, Hassette
from hassette.models.events import (
    CallServiceEvent,
    ComponentLoadedEvent,
    HassContext,
    ServiceRegisteredEvent,
    create_event_from_hass,
)

if typing.TYPE_CHECKING:
    from hassette.models.events import HassEventEnvelopeDict

EVENT: Event[Any] = cast("Event[Any]", object())

HASS_EVENT_TEMPLATE = {
    "event_type": "state_changed",
    "data": {},
    "origin": "LOCAL",
    "time_fired": Instant.now(),
    "context": HassContext(id="1", parent_id=None, user_id=None),
    "id": 1,
}

LOGGER = getLogger("hassette")


def create_hass_event(
    event_type: str, domain: str | None = None, service: str | None = None, component: str | None = None
):
    data = {}
    if event_type == "state_changed":
        data = {
            "entity_id": "light.test" if domain == "light" else "switch.test",
            "old_state": None,
            "new_state": None,
        }
    elif event_type == "call_service":
        data = {
            "domain": domain or "light",
            "service": service or "turn_on",
        }
    elif event_type == "component_loaded":
        data = {
            "component": component or "light",
        }
    elif event_type == "service_registered":
        data = {
            "domain": domain or "light",
            "service": service or "turn_on",
        }

    event_data = HASS_EVENT_TEMPLATE.copy()
    event_data["event_type"] = event_type
    event_data["data"] = data

    event_data = cast("HassEventEnvelopeDict", {"event": event_data, "type": "event", "id": 1})

    return create_event_from_hass(event_data)


@pytest.fixture
async def mock_hassette_bus():
    class MockHassette:
        task: asyncio.Task

        def __init__(self):
            self._send_stream, self._receive_stream = create_memory_object_stream[tuple[str, Event]](1000)
            self._bus = _Bus(cast("Hassette", self), self._receive_stream.clone())
            self.bus = Bus(cast("Hassette", self), self._bus)

        async def send_event(self, topic: str, event: Event[Any]) -> None:
            """Mock method to send an event to the bus."""
            await self._send_stream.send((topic, event))

    hassette = MockHassette()

    hassette.task = asyncio.create_task(hassette._bus.run_forever())
    await asyncio.sleep(0)  # Allow the task to start
    yield hassette

    hassette.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await hassette.task


def get_handler(calls: list[Event[Any]]) -> Callable[..., Coroutine[Any, Any, None]]:
    async def handler(event: Event[Any]) -> None:
        calls.append(event)

    return handler


async def test_bus_once_and_debounce(mock_hassette_bus: Hassette) -> None:
    calls = []

    # once + debounce 0.05s
    mock_hassette_bus.bus.on(topic="demo", handler=get_handler(calls), once=True, debounce=0.05)

    # Emit 5 times quickly
    for _ in range(5):
        await mock_hassette_bus.send_event("demo", EVENT)
    await asyncio.sleep(0.1)  # allow debounce window to elapse + dispatch

    # once: only one call; debounce: collapsed burst
    assert len(calls) == 1


async def test_bus_glob_and_exact(mock_hassette_bus: Hassette) -> None:
    hits = []

    mock_hassette_bus.bus.on(topic="demo.*", handler=get_handler(hits))
    mock_hassette_bus.bus.on(topic="demo.specific", handler=get_handler(hits))

    await mock_hassette_bus.send_event("demo.specific", EVENT)
    await asyncio.sleep(0.1)  # allow dispatch
    assert hits, "No handlers fired!"

    assert hits == [EVENT, EVENT], "Both handlers should have fired"


async def test_bus_throttle(mock_hassette_bus: Hassette) -> None:
    calls = []
    mock_hassette_bus.bus.on(topic="throttle", handler=get_handler(calls), throttle=0.05)

    for _ in range(5):
        await mock_hassette_bus.send_event("throttle", EVENT)
    await asyncio.sleep(0.12)

    # Implementation-dependent, but a tight burst should be 1 (maybe 2)
    assert 1 <= len(calls) <= 2


async def test_bus_subscription_remove(mock_hassette_bus: Hassette) -> None:
    calls = []
    sub = mock_hassette_bus.bus.on(topic="x", handler=get_handler(calls))
    sub.cancel()

    await mock_hassette_bus.send_event("x", EVENT)
    await asyncio.sleep(0)

    assert calls == []


@pytest.mark.parametrize(
    ("domain", "service", "expected_calls"),
    [(None, None, 2), ("light", None, 1), (None, "turn_on", 2), ("light", "turn_on", 1)],
)
async def test_bus_on_call_service(
    mock_hassette_bus: Hassette, domain: str | None, service: str | None, expected_calls: int
) -> None:
    calls: list[CallServiceEvent] = []
    mock_hassette_bus.bus.on_call_service(domain=domain, service=service, handler=get_handler(calls))

    await mock_hassette_bus.send_event(
        "hass.event.call_service",
        create_hass_event("call_service", domain="light", service="turn_on"),
    )
    await mock_hassette_bus.send_event(
        "hass.event.call_service", create_hass_event("call_service", domain="switch", service="turn_on")
    )
    await asyncio.sleep(0.1)  # allow dispatch

    assert len(calls) == expected_calls
    if domain == "light":
        assert calls[0].payload.domain == "light"
    else:
        assert {call.payload.domain for call in calls} == {"light", "switch"}


@pytest.mark.parametrize(
    ("domain", "service", "expected_calls"),
    [(None, None, 2), ("light", None, 1), (None, "turn_on", 2), ("light", "turn_on", 1)],
)
async def test_bus_on_service_registered(
    mock_hassette_bus: Hassette, domain: str | None, service: str | None, expected_calls: int
) -> None:
    calls: list[ServiceRegisteredEvent] = []

    mock_hassette_bus.bus.on_service_registered(domain=domain, service=service, handler=get_handler(calls))

    await mock_hassette_bus.send_event(
        "hass.event.service_registered",
        create_hass_event("service_registered", domain="light", service="turn_on"),
    )
    await mock_hassette_bus.send_event(
        "hass.event.service_registered", create_hass_event("service_registered", domain="switch", service="turn_on")
    )
    await asyncio.sleep(0.1)  # allow dispatch

    assert len(calls) == expected_calls
    if domain == "light":
        assert calls[0].payload.domain == "light"
    else:
        assert {call.payload.domain for call in calls} == {"light", "switch"}


@pytest.mark.parametrize(("component", "expected_calls"), [(None, 2), ("light", 1)])
async def test_bus_on_component_loaded(mock_hassette_bus: Hassette, component: str | None, expected_calls: int) -> None:
    calls: list[ComponentLoadedEvent] = []

    mock_hassette_bus.bus.on_component_loaded(component=component, handler=get_handler(calls))

    await mock_hassette_bus.send_event(
        "hass.event.component_loaded",
        create_hass_event("component_loaded", component="light"),
    )
    await mock_hassette_bus.send_event(
        "hass.event.component_loaded", create_hass_event("component_loaded", component="switch")
    )
    await asyncio.sleep(0.1)  # allow dispatch

    assert len(calls) == expected_calls
    if component == "light":
        assert calls[0].payload.data.component == "light"

    else:
        assert {call.payload.data.component for call in calls} == {"light", "switch"}


async def test_bus_on_home_assistant_restarted(mock_hassette_bus: Hassette) -> None:
    calls: list[CallServiceEvent] = []

    mock_hassette_bus.bus.on(
        topic="hass.event.call_service",
        handler=get_handler(calls),
        where=HomeAssistantRestarted,
    )

    await mock_hassette_bus.send_event(
        "hass.event.call_service",
        create_hass_event("call_service", domain="homeassistant", service="restart"),
    )
    await mock_hassette_bus.send_event(
        "hass.event.call_service", create_hass_event("call_service", domain="light", service="turn_on")
    )
    await asyncio.sleep(0.1)  # allow dispatch

    assert len(calls) == 1
    assert calls[0].payload.domain == "homeassistant"
    assert calls[0].payload.service == "restart"
