"""Integration tests for AppTestHarness.

Tests the full lifecycle: setup, app initialization, event simulation, teardown,
config validation, and state preservation.
"""

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from hassette import context
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import RawStateChangeEvent
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
