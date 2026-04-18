"""Integration tests for AppTestHarness.

Tests the full lifecycle: setup, app initialization, event simulation, teardown,
config validation, and state preservation.
"""

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from hassette import D, context
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import CallServiceEvent, RawStateChangeEvent
from hassette.models import states
from hassette.test_utils.app_harness import AppConfigurationError, AppTestHarness
from hassette.test_utils.recording_api import RecordingApi
from hassette.types.enums import ResourceStatus

# ---------------------------------------------------------------------------
# Minimal test app defined inline.
# Class names don't start with "Test" to avoid pytest collection warnings.
# ---------------------------------------------------------------------------


class SensorConfig(AppConfig):
    """Minimal AppConfig subclass for testing."""

    test_entity: str = "sensor.test"


class SensorApp(App[SensorConfig]):
    """Minimal App subclass for integration testing."""

    handler_calls: list[Any]

    async def on_initialize(self) -> None:
        self.handler_calls = []
        self.bus.on_state_change("sensor.test", handler=self._on_change)

    async def _on_change(self, event: RawStateChangeEvent) -> None:
        self.handler_calls.append(event)


class RequiredFieldConfig(AppConfig):
    """AppConfig with a required field (no default)."""

    required_field: str


class RequiredFieldApp(App[RequiredFieldConfig]):
    """App whose config has a required field."""

    async def on_initialize(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_lifecycle():
    """AppTestHarness starts and stops cleanly; harness.app is a SensorApp in RUNNING state."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        assert isinstance(harness.app, SensorApp)
        assert harness.app.status == ResourceStatus.RUNNING


@pytest.mark.asyncio
async def test_api_recorder_is_recording_api():
    """harness.api_recorder is a RecordingApi instance."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        assert isinstance(harness.api_recorder, RecordingApi)


@pytest.mark.asyncio
async def test_bus_scheduler_states_exposed():
    """harness.bus, harness.scheduler, harness.states are the app's actual resources."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        assert harness.bus is harness.app.bus
        assert harness.scheduler is harness.app.scheduler
        assert harness.states is harness.app.states


@pytest.mark.asyncio
async def test_bad_config_raises_app_configuration_error():
    """Passing an invalid config raises AppConfigurationError with the app class name."""
    # RequiredFieldApp needs "required_field" — passing nothing should fail
    with pytest.raises(AppConfigurationError) as exc_info:
        async with AppTestHarness(RequiredFieldApp, config={}):
            pass

    error = exc_info.value
    assert "RequiredFieldApp" in str(error)
    assert error.app_cls is RequiredFieldApp
    assert error.original_error is not None


@pytest.mark.asyncio
async def test_config_hermetic_ignores_env(monkeypatch: pytest.MonkeyPatch):
    """Env vars are not picked up by hermetic validation."""
    # Even if TEST_ENTITY env var is set, the hermetic factory should ignore it
    monkeypatch.setenv("TEST_ENTITY", "sensor.from_env")

    async with AppTestHarness(SensorApp, config={}) as harness:
        # test_entity should be the default "sensor.test", not "sensor.from_env"
        assert harness.app.app_config.test_entity == "sensor.test"


@pytest.mark.asyncio
async def test_cleanup_on_aenter_failure():
    """If __aenter__ fails partway through, exit stack unwinds (no leaked ContextVar state)."""
    # Capture the ContextVar state before
    before = context.HASSETTE_INSTANCE.get(None)

    class BrokenApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            raise RuntimeError("Intentional failure during on_initialize")

    # The RuntimeError is re-raised from on_initialize; the TimeoutError is the
    # harness startup timeout from wait_for() in harness.py — NOT a drain timeout.
    # Harness startup still uses a bare TimeoutError, so DrainTimeout is not the
    # right exception to expect here.
    with pytest.raises((RuntimeError, TimeoutError)):
        async with AppTestHarness(BrokenApp, config={}):
            pass  # Should not reach here

    # ContextVar should be reset to its pre-test state
    after = context.HASSETTE_INSTANCE.get(None)
    assert after is before, f"ContextVar leaked: before={before!r}, after={after!r}"


@pytest.mark.asyncio
async def test_sequential_tests_dont_collide():
    """Two sequential async with blocks do not raise 'already set' ContextVar errors."""
    async with AppTestHarness(SensorApp, config={}) as harness1:
        assert harness1.app is not None

    # Second block should work without error
    async with AppTestHarness(SensorApp, config={}) as harness2:
        assert harness2.app is not None


@pytest.mark.asyncio
async def test_manifest_restored_after_exit():
    """SensorApp.app_manifest is restored (or removed) to its original value after exit."""
    original = getattr(SensorApp, "app_manifest", AppTestHarness._UNSET)

    async with AppTestHarness(SensorApp, config={}):
        # Inside the context, app_manifest is set to the synthesized one
        assert hasattr(SensorApp, "app_manifest")

    # After exit, should be restored to original
    restored = getattr(SensorApp, "app_manifest", AppTestHarness._UNSET)
    assert restored is original


@pytest.mark.asyncio
async def test_api_factory_restored_after_exit():
    """SensorApp._api_factory is None after exit (restored to original value)."""
    # Before entry, _api_factory should be None (the class default)
    original_factory = SensorApp._api_factory
    assert original_factory is None

    async with AppTestHarness(SensorApp, config={}):
        # Inside, _api_factory is RecordingApi
        assert SensorApp._api_factory is RecordingApi

    # After exit, restored to None
    assert SensorApp._api_factory is None


@pytest.mark.asyncio
async def test_auto_tmpdir_created_and_cleaned():
    """Without tmp_path, a tmpdir is auto-created and removed after exit."""
    captured_data_dir: list[Path] = []

    class DirCapturingApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            captured_data_dir.append(self.hassette.config.data_dir)

    async with AppTestHarness(DirCapturingApp, config={}):
        pass

    assert len(captured_data_dir) == 1
    data_dir = captured_data_dir[0]
    # The directory should not exist after exit (cleaned up)
    assert not data_dir.exists(), f"tmpdir {data_dir} was not cleaned up"


@pytest.mark.asyncio
async def test_simulate_state_change_triggers_handler():
    """simulate_state_change fires the bus handler and it completes before the call returns."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        assert harness.app.handler_calls == []

        await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")

        assert len(harness.app.handler_calls) == 1


@pytest.mark.asyncio
async def test_api_recorder_records_calls():
    """When the app calls self.api.turn_on(), api_recorder captures the call."""

    class CallsApiApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_state_change("sensor.test", handler=self._on_change)

        async def _on_change(self, event: RawStateChangeEvent) -> None:
            await self.api.turn_on("light.kitchen")

    async with AppTestHarness(CallsApiApp, config={}) as harness:
        harness.api_recorder.assert_not_called("turn_on")

        await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")

        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")


# ---------------------------------------------------------------------------
# State seeding tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_state_seeds_proxy():
    """set_state populates the StateProxy so states.get() returns the value."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        await harness.set_state("light.kitchen", "on", brightness=255)

        state = harness.app.states.get("light.kitchen")
        assert state is not None
        assert state.entity_id == "light.kitchen"


@pytest.mark.asyncio
async def test_set_state_does_not_fire_events():
    """set_state is silent — no bus events, no handler invocations."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        # SensorApp listens to sensor.test — setting its state should NOT trigger the handler
        await harness.set_state("sensor.test", "25.5")

        assert harness.app.handler_calls == [], "set_state should not fire bus events"


@pytest.mark.asyncio
async def test_set_states_multiple():
    """set_states seeds multiple entities at once."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        await harness.set_states(
            {
                "light.kitchen": "on",
                "sensor.temp": ("25.5", {"unit_of_measurement": "°C"}),
                "switch.fan": "off",
            }
        )

        assert harness.app.states.get("light.kitchen") is not None
        assert harness.app.states.get("sensor.temp") is not None
        assert harness.app.states.get("switch.fan") is not None


# ---------------------------------------------------------------------------
# Additional event simulation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_state_change_drains_handlers():
    """simulate_state_change returns only after the handler has fully completed."""

    class SlowHandlerApp(App[SensorConfig]):
        handler_finished: bool = False

        async def on_initialize(self) -> None:
            self.handler_finished = False
            self.bus.on_state_change("sensor.test", handler=self._slow_handler)

        async def _slow_handler(self, event: RawStateChangeEvent) -> None:
            await asyncio.sleep(0.05)  # Simulate async work
            self.handler_finished = True

    async with AppTestHarness(SlowHandlerApp, config={}) as harness:
        await harness.simulate_state_change("sensor.test", old_value="off", new_value="on")
        assert harness.app.handler_finished, "Handler should have completed before simulate returned"


@pytest.mark.asyncio
async def test_simulate_call_service():
    """simulate_call_service sends a call_service event through the bus without error."""
    async with AppTestHarness(SensorApp, config={}) as harness:
        # Verify the method executes without raising — the event is sent through the bus
        await harness.simulate_call_service("light", "turn_on")


# ---------------------------------------------------------------------------
# simulate_attribute_change with explicit state= argument
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_attribute_change_uses_explicit_state():
    """When state= is passed, simulate_attribute_change uses it instead of proxy lookup.

    Patches simulate_state_change to capture the call args, verifying the explicit
    state= value is forwarded rather than the cached proxy value.
    """
    from unittest.mock import AsyncMock, patch

    async with AppTestHarness(SensorApp, config={}) as harness:
        await harness.set_state("sensor.test", "20.0")

        # Patch simulate_state_change to capture call args without actually sending
        with patch.object(harness, "simulate_state_change", new_callable=AsyncMock) as mock_ssc:
            await harness.simulate_attribute_change(
                "sensor.test",
                "unit_of_measurement",
                old_value="°C",
                new_value="°F",
                state="25.0",
            )

            mock_ssc.assert_called_once()
            call_kwargs = mock_ssc.call_args
            # The state values should be "25.0" (explicit), not "20.0" (cached)
            assert call_kwargs.kwargs["old_value"] == "25.0"
            assert call_kwargs.kwargs["new_value"] == "25.0"


# ---------------------------------------------------------------------------
# Typed DI handler tests (WP01 — fix existing event factories)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_state_change_typed_di_state_new():
    """Handler with D.StateNew[BinarySensorState] receives a valid typed model."""
    received: list[states.BinarySensorState] = []

    class BinarySensorApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_state_change("binary_sensor.test", handler=self._on_change)

        async def _on_change(self, new_state: D.StateNew[states.BinarySensorState]) -> None:
            received.append(new_state)

    async with AppTestHarness(BinarySensorApp, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.test", old_value="off", new_value="on")

    assert len(received) == 1
    assert isinstance(received[0], states.BinarySensorState)
    assert received[0].value is True  # "on" converts to True
    assert received[0].entity_id == "binary_sensor.test"


@pytest.mark.asyncio
async def test_simulate_state_change_typed_di_state_old():
    """Handler with D.StateOld[BinarySensorState] receives a valid typed model."""
    received: list[states.BinarySensorState] = []

    class BinarySensorOldApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_state_change("binary_sensor.test", handler=self._on_change)

        async def _on_change(self, old_state: D.StateOld[states.BinarySensorState]) -> None:
            received.append(old_state)

    async with AppTestHarness(BinarySensorOldApp, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.test", old_value="off", new_value="on")

    assert len(received) == 1
    assert isinstance(received[0], states.BinarySensorState)
    assert received[0].value is False  # "off" converts to False
    assert received[0].entity_id == "binary_sensor.test"


@pytest.mark.asyncio
async def test_simulate_state_change_none_old_value():
    """old_value=None produces None old_state dict; D.MaybeStateOld returns None."""
    received_old: list[Any] = []

    class NewEntityApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_state_change("binary_sensor.test", handler=self._on_change)

        async def _on_change(self, old_state: D.MaybeStateOld[states.BinarySensorState]) -> None:
            received_old.append(old_state)

    async with AppTestHarness(NewEntityApp, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.test", old_value=None, new_value="on")

    assert len(received_old) == 1
    assert received_old[0] is None


@pytest.mark.asyncio
async def test_simulate_state_change_none_new_value():
    """new_value=None produces None new_state dict (entity removed)."""
    received: list[RawStateChangeEvent] = []

    class RemovedEntityApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_state_change("binary_sensor.test", handler=self._on_change)

        async def _on_change(self, event: RawStateChangeEvent) -> None:
            received.append(event)

    async with AppTestHarness(RemovedEntityApp, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.test", old_value="on", new_value=None)

    assert len(received) == 1
    assert received[0].payload.data.new_state is None


@pytest.mark.asyncio
async def test_simulate_call_service_typed_di_domain():
    """Handler with D.Domain receives the correct domain string."""
    received_domains: list[str] = []

    class CallServiceApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_call_service(handler=self._on_call)

        async def _on_call(self, domain: D.Domain) -> None:
            received_domains.append(domain)

    async with AppTestHarness(CallServiceApp, config={}) as harness:
        await harness.simulate_call_service("light", "turn_on")

    assert len(received_domains) == 1
    assert received_domains[0] == "light"


@pytest.mark.asyncio
async def test_simulate_call_service_is_real_call_service_event():
    """simulate_call_service produces a real CallServiceEvent (not SimpleNamespace)."""
    received_events: list[Any] = []

    class EventCapturingApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_call_service(handler=self._on_call)

        async def _on_call(self, event: CallServiceEvent) -> None:
            received_events.append(event)

    async with AppTestHarness(EventCapturingApp, config={}) as harness:
        await harness.simulate_call_service("light", "turn_on", brightness=255)

    assert len(received_events) == 1
    event = received_events[0]
    assert isinstance(event, CallServiceEvent)
    assert event.payload.data.domain == "light"
    assert event.payload.data.service == "turn_on"
    assert event.payload.data.service_data == {"brightness": 255}


@pytest.mark.asyncio
async def test_simulate_attribute_change_typed_di():
    """Handler with D.StateNew[SensorState] works through the attribute change delegation path."""
    received: list[states.SensorState] = []

    class TempSensorApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_attribute_change("sensor.test", "unit_of_measurement", handler=self._on_attr)

        async def _on_attr(self, new_state: D.StateNew[states.SensorState]) -> None:
            received.append(new_state)

    async with AppTestHarness(TempSensorApp, config={}) as harness:
        await harness.set_state("sensor.test", "25.5")
        await harness.simulate_attribute_change(
            "sensor.test",
            "unit_of_measurement",
            old_value="°C",
            new_value="°F",
        )

    assert len(received) == 1
    assert isinstance(received[0], states.SensorState)
    assert received[0].entity_id == "sensor.test"


# ---------------------------------------------------------------------------
# simulate_component_loaded / simulate_service_registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_component_loaded():
    """simulate_component_loaded fires on_component_loaded handler."""
    calls: list[Any] = []

    class ComponentApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_component_loaded(handler=self._on_loaded)

        async def _on_loaded(self) -> None:
            calls.append(True)

    async with AppTestHarness(ComponentApp, config={}) as harness:
        await harness.simulate_component_loaded("my_component")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_service_registered():
    """simulate_service_registered fires on_service_registered handler."""
    calls: list[Any] = []

    class ServiceRegApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_service_registered(handler=self._on_registered)

        async def _on_registered(self) -> None:
            calls.append(True)

    async with AppTestHarness(ServiceRegApp, config={}) as harness:
        await harness.simulate_service_registered("light", "turn_on")

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# simulate_hassette_service_status / failed / crashed / started
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_hassette_service_status():
    """simulate_hassette_service_status fires on_hassette_service_status handler."""
    calls: list[Any] = []

    class ServiceStatusApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_hassette_service_status(handler=self._on_status)

        async def _on_status(self) -> None:
            calls.append(True)

    async with AppTestHarness(ServiceStatusApp, config={}) as harness:
        # Clear calls accumulated during harness startup (services emit status events)
        calls.clear()
        await harness.simulate_hassette_service_status("MyService", ResourceStatus.RUNNING)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_hassette_service_failed():
    """simulate_hassette_service_failed fires on_hassette_service_failed handler."""
    calls: list[Any] = []

    class ServiceFailedApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_hassette_service_failed(handler=self._on_failed)

        async def _on_failed(self) -> None:
            calls.append(True)

    async with AppTestHarness(ServiceFailedApp, config={}) as harness:
        await harness.simulate_hassette_service_failed("MyService", exception=RuntimeError("boom"))

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_hassette_service_crashed():
    """simulate_hassette_service_crashed fires on_hassette_service_crashed handler."""
    calls: list[Any] = []

    class ServiceCrashedApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_hassette_service_crashed(handler=self._on_crashed)

        async def _on_crashed(self) -> None:
            calls.append(True)

    async with AppTestHarness(ServiceCrashedApp, config={}) as harness:
        await harness.simulate_hassette_service_crashed("MyService")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_hassette_service_started():
    """simulate_hassette_service_started fires on_hassette_service_started handler."""
    calls: list[Any] = []

    class ServiceStartedApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_hassette_service_started(handler=self._on_started)

        async def _on_started(self) -> None:
            calls.append(True)

    async with AppTestHarness(ServiceStartedApp, config={}) as harness:
        # Clear calls accumulated during harness startup (services emit RUNNING events)
        calls.clear()
        await harness.simulate_hassette_service_started("MyService")

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# simulate_websocket_connected / disconnected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_websocket_connected():
    """simulate_websocket_connected fires on_websocket_connected handler."""
    calls: list[Any] = []

    class WsConnectedApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_websocket_connected(handler=self._on_connected)

        async def _on_connected(self) -> None:
            calls.append(True)

    async with AppTestHarness(WsConnectedApp, config={}) as harness:
        await harness.simulate_websocket_connected()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_websocket_disconnected():
    """simulate_websocket_disconnected fires on_websocket_disconnected handler."""
    calls: list[Any] = []

    class WsDisconnectedApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_websocket_disconnected(handler=self._on_disconnected)

        async def _on_disconnected(self) -> None:
            calls.append(True)

    async with AppTestHarness(WsDisconnectedApp, config={}) as harness:
        await harness.simulate_websocket_disconnected()

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# simulate_app_state_changed / running / stopping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_app_state_changed():
    """simulate_app_state_changed fires on_app_state_changed handler."""
    calls: list[Any] = []

    class AppStateApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_app_state_changed(handler=self._on_state)

        async def _on_state(self) -> None:
            calls.append(True)

    async with AppTestHarness(AppStateApp, config={}) as harness:
        await harness.simulate_app_state_changed(ResourceStatus.STOPPING)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_app_running():
    """simulate_app_running fires on_app_state_changed handler with RUNNING status."""
    calls: list[Any] = []

    class AppRunningApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_app_state_changed(handler=self._on_state)

        async def _on_state(self) -> None:
            calls.append(True)

    async with AppTestHarness(AppRunningApp, config={}) as harness:
        await harness.simulate_app_running()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_app_stopping():
    """simulate_app_stopping fires on_app_state_changed handler with STOPPING status."""
    calls: list[Any] = []

    class AppStoppingApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_app_state_changed(handler=self._on_state)

        async def _on_state(self) -> None:
            calls.append(True)

    async with AppTestHarness(AppStoppingApp, config={}) as harness:
        await harness.simulate_app_stopping()

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# simulate_homeassistant_restart / start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_homeassistant_restart():
    """simulate_homeassistant_restart fires on_homeassistant_restart handler."""
    calls: list[Any] = []

    class HaRestartApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_homeassistant_restart(handler=self._on_restart)

        async def _on_restart(self) -> None:
            calls.append(True)

    async with AppTestHarness(HaRestartApp, config={}) as harness:
        await harness.simulate_homeassistant_restart()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_homeassistant_start():
    """simulate_homeassistant_start fires on_homeassistant_start handler."""
    calls: list[Any] = []

    class HaStartApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_homeassistant_start(handler=self._on_start)

        async def _on_start(self) -> None:
            calls.append(True)

    async with AppTestHarness(HaStartApp, config={}) as harness:
        await harness.simulate_homeassistant_start()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_simulate_homeassistant_stop():
    """simulate_homeassistant_stop fires on_homeassistant_stop handler."""
    calls: list[Any] = []

    class HaStopApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_homeassistant_stop(handler=self._on_stop)

        async def _on_stop(self) -> None:
            calls.append(True)

    async with AppTestHarness(HaStopApp, config={}) as harness:
        await harness.simulate_homeassistant_stop()

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Typed DI handler tests for new simulate methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulate_hassette_service_status_typed_di():
    """Handler asserts event.payload.data.status and resource_name match expected values."""
    from hassette.events.hassette import HassetteServiceEvent

    received: list[HassetteServiceEvent] = []

    class ServiceStatusDiApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_hassette_service_status(handler=self._on_status)

        async def _on_status(self, event: HassetteServiceEvent) -> None:
            received.append(event)

    async with AppTestHarness(ServiceStatusDiApp, config={}) as harness:
        # Clear events accumulated during harness startup
        received.clear()
        await harness.simulate_hassette_service_status("WebSocketService", ResourceStatus.FAILED)

    assert len(received) == 1
    assert received[0].payload.data.status == ResourceStatus.FAILED
    assert received[0].payload.data.resource_name == "WebSocketService"


@pytest.mark.asyncio
async def test_simulate_app_state_changed_typed_di():
    """Handler asserts event.payload.data.app_key matches harness app key."""
    from hassette.events.hassette import HassetteAppStateEvent

    received: list[HassetteAppStateEvent] = []

    class AppStateDiApp(App[SensorConfig]):
        async def on_initialize(self) -> None:
            self.bus.on_app_state_changed(handler=self._on_state)

        async def _on_state(self, event: HassetteAppStateEvent) -> None:
            received.append(event)

    async with AppTestHarness(AppStateDiApp, config={}) as harness:
        await harness.simulate_app_state_changed(ResourceStatus.STOPPING)
        expected_key = harness.app.app_manifest.app_key

    assert len(received) == 1
    assert received[0].payload.data.app_key == expected_key
