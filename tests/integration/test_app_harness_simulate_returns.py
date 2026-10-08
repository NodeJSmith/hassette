"""Integration tests: every ``AppTestHarness.simulate_*`` helper returns the event it dispatched.

The returned object must be the same instance the app's handlers received, and it must
only be returned after dispatch and drain complete — so no ``wait_for`` is used here.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from hassette_wire import ResourceStatus

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import (
    CallServiceEvent,
    ComponentLoadedEvent,
    Event,
    RawStateChangeEvent,
    ServiceRegisteredEvent,
)
from hassette.events.hassette import HassetteAppStateEvent, HassetteServiceEvent, HassetteSimpleEvent
from hassette.testing import AppTestHarness


class CaptureConfig(AppConfig):
    """Minimal config for the capture app."""


class CaptureAllApp(App[CaptureConfig]):
    """Records every event delivered on the bus."""

    received: list[Event[Any]]

    async def on_initialize(self) -> None:
        self.received = []
        await self.bus.on(topic="*", handler=self.capture, name="capture_all")

    async def capture(self, event: Event[Any]) -> None:
        self.received.append(event)


Simulate = Callable[[AppTestHarness[CaptureAllApp]], Awaitable[Event[Any]]]

SIMULATIONS: list[tuple[str, Simulate, type[Event[Any]]]] = [
    (
        "state_change",
        lambda h: h.simulate_state_change("sensor.temp", old_value="1", new_value="2"),
        RawStateChangeEvent,
    ),
    (
        "attribute_change",
        lambda h: h.simulate_attribute_change("light.kitchen", "brightness", old_value=1, new_value=2, state="on"),
        RawStateChangeEvent,
    ),
    ("call_service", lambda h: h.simulate_call_service("light", "turn_on", brightness=255), CallServiceEvent),
    ("component_loaded", lambda h: h.simulate_component_loaded("mqtt"), ComponentLoadedEvent),
    ("service_registered", lambda h: h.simulate_service_registered("light", "turn_on"), ServiceRegisteredEvent),
    (
        "hassette_service_status",
        lambda h: h.simulate_hassette_service_status("MyService", ResourceStatus.STOPPED),
        HassetteServiceEvent,
    ),
    ("hassette_service_ready", lambda h: h.simulate_hassette_service_ready("MyService"), HassetteServiceEvent),
    ("hassette_service_failed", lambda h: h.simulate_hassette_service_failed("MyService"), HassetteServiceEvent),
    ("hassette_service_crashed", lambda h: h.simulate_hassette_service_crashed("MyService"), HassetteServiceEvent),
    ("hassette_service_started", lambda h: h.simulate_hassette_service_started("MyService"), HassetteServiceEvent),
    ("websocket_connected", lambda h: h.simulate_websocket_connected(), HassetteSimpleEvent),
    ("websocket_disconnected", lambda h: h.simulate_websocket_disconnected(), HassetteSimpleEvent),
    (
        "app_state_changed",
        lambda h: h.simulate_app_state_changed(ResourceStatus.STOPPING),
        HassetteAppStateEvent,
    ),
    ("app_running", lambda h: h.simulate_app_running(), HassetteAppStateEvent),
    ("app_stopping", lambda h: h.simulate_app_stopping(), HassetteAppStateEvent),
    ("homeassistant_restart", lambda h: h.simulate_homeassistant_restart(), CallServiceEvent),
    ("homeassistant_start", lambda h: h.simulate_homeassistant_start(), CallServiceEvent),
    ("homeassistant_stop", lambda h: h.simulate_homeassistant_stop(), CallServiceEvent),
]


@pytest.mark.parametrize(
    ("simulate", "event_type"), [(s, t) for _, s, t in SIMULATIONS], ids=[n for n, _, _ in SIMULATIONS]
)
async def test_simulate_returns_dispatched_event(simulate: Simulate, event_type: type[Event[Any]]) -> None:
    """The returned event is the instance handlers received, delivered before the call returned."""
    async with AppTestHarness(CaptureAllApp, config={}) as harness:
        event = await simulate(harness)

        assert isinstance(event, event_type)
        assert any(received is event for received in harness.app.received)


def test_every_simulate_method_is_covered() -> None:
    """Guard: a new ``simulate_*`` method must be added to SIMULATIONS."""
    methods = {name.removeprefix("simulate_") for name in dir(AppTestHarness) if name.startswith("simulate_")}
    assert methods == {name for name, _, _ in SIMULATIONS}


async def test_convenience_wrapper_returns_delegated_event_payload() -> None:
    """Convenience wrappers return the event built by the delegated simulation, with their preset values."""
    async with AppTestHarness(CaptureAllApp, config={}) as harness:
        ready = await harness.simulate_hassette_service_ready("MyService", ready_phase="connected")
        restart = await harness.simulate_homeassistant_restart()

    assert ready.payload.data.resource_name == "MyService"
    assert ready.payload.data.status == ResourceStatus.RUNNING
    assert ready.payload.data.ready is True
    assert restart.payload.data.domain == "homeassistant"
    assert restart.payload.data.service == "restart"
