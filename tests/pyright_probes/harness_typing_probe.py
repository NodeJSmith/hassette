"""Pyright probe proving AppTestHarness preserves concrete app and simulated-event types."""

# ruff: noqa
# pyright: basic

from typing import assert_type

from hassette_wire import ResourceStatus

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import CallServiceEvent, ComponentLoadedEvent, RawStateChangeEvent, ServiceRegisteredEvent
from hassette.events.hassette import HassetteAppStateEvent, HassetteServiceEvent, HassetteSimpleEvent
from hassette.testing import AppTestHarness


class ProbeConfig(AppConfig):
    pass


class ProbeApp(App[ProbeConfig]):
    probe_value: int


async def probe_harness_type() -> None:
    harness = AppTestHarness(ProbeApp)
    assert_type(harness, AppTestHarness[ProbeApp])

    async with harness as active:
        assert_type(active, AppTestHarness[ProbeApp])
        assert_type(active.app, ProbeApp)
        active.app.probe_value


async def probe_simulate_return_types() -> None:
    async with AppTestHarness(ProbeApp) as harness:
        assert_type(await harness.simulate_state_change("sensor.x", old_value="a", new_value="b"), RawStateChangeEvent)
        assert_type(
            await harness.simulate_attribute_change("sensor.x", "unit", old_value="a", new_value="b"),
            RawStateChangeEvent,
        )
        assert_type(await harness.simulate_call_service("light", "turn_on"), CallServiceEvent)
        assert_type(await harness.simulate_component_loaded("mqtt"), ComponentLoadedEvent)
        assert_type(await harness.simulate_service_registered("light", "turn_on"), ServiceRegisteredEvent)
        assert_type(await harness.simulate_hassette_service_status("Svc", ResourceStatus.RUNNING), HassetteServiceEvent)
        assert_type(await harness.simulate_hassette_service_ready("Svc"), HassetteServiceEvent)
        assert_type(await harness.simulate_hassette_service_failed("Svc"), HassetteServiceEvent)
        assert_type(await harness.simulate_hassette_service_crashed("Svc"), HassetteServiceEvent)
        assert_type(await harness.simulate_hassette_service_started("Svc"), HassetteServiceEvent)
        assert_type(await harness.simulate_websocket_connected(), HassetteSimpleEvent)
        assert_type(await harness.simulate_websocket_disconnected(), HassetteSimpleEvent)
        assert_type(await harness.simulate_app_state_changed(ResourceStatus.RUNNING), HassetteAppStateEvent)
        assert_type(await harness.simulate_app_running(), HassetteAppStateEvent)
        assert_type(await harness.simulate_app_stopping(), HassetteAppStateEvent)
        assert_type(await harness.simulate_homeassistant_restart(), CallServiceEvent)
        assert_type(await harness.simulate_homeassistant_start(), CallServiceEvent)
        assert_type(await harness.simulate_homeassistant_stop(), CallServiceEvent)
