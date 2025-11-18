"""Tests for States class functionality.

Tests cover domain-specific accessors, generic state access,
typed getters, and DomainStates helper class.
"""

import asyncio
from typing import TYPE_CHECKING

import pytest
from fixtures.state_fixtures import (
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_change_event,
    make_switch_state_dict,
)

from hassette.exceptions import EntityNotFoundError
from hassette.models import states
from hassette.states import DomainStates, States
from hassette.types import topics

if TYPE_CHECKING:
    from hassette import Hassette


class TestStatesClassInit:
    """Tests for States class initialization."""

    async def test_create_returns_instance(self, hassette_with_state_proxy: "Hassette") -> None:
        """States.create returns a configured States instance."""
        hassette = hassette_with_state_proxy

        # Create a States instance
        states_instance = States.create(hassette, hassette)

        assert isinstance(states_instance, States)
        assert states_instance.hassette is hassette

    async def test_accesses_state_proxy(self, hassette_with_state_proxy: "Hassette") -> None:
        """States instance accesses the StateProxyResource."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        # Should be able to access state proxy
        assert states_instance.state_proxy is hassette._state_proxy_resource


class TestStatesDomainAccessors:
    """Tests for domain-specific properties."""

    async def test_lights_returns_light_states(self, hassette_with_state_proxy: "Hassette") -> None:
        """lights property returns DomainStates[LightState] containing only lights."""
        hassette = hassette_with_state_proxy

        # Add mixed entity types
        light1_dict = make_light_state_dict("light.bedroom", "on", brightness=150)
        light2_dict = make_light_state_dict("light.kitchen", "off")
        sensor_dict = make_sensor_state_dict("sensor.temp", "22.0")

        for entity_id, state_dict in [
            ("light.bedroom", light1_dict),
            ("light.kitchen", light2_dict),
            ("sensor.temp", sensor_dict),
        ]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Create States instance and access lights
        states_instance = States.create(hassette, hassette)
        lights = states_instance.lights

        assert isinstance(lights, DomainStates)

        # Iterate and verify only lights are returned
        light_ids = []
        for entity_id, light_state in lights:
            light_ids.append(entity_id)
            assert isinstance(light_state, states.LightState)
            assert entity_id.startswith("light.")

        assert "light.bedroom" in light_ids
        assert "light.kitchen" in light_ids
        assert "sensor.temp" not in light_ids

    async def test_sensors_returns_sensor_states(self, hassette_with_state_proxy: "Hassette") -> None:
        """sensors property returns DomainStates[SensorState] containing only sensors."""
        hassette = hassette_with_state_proxy

        # Add sensor states
        sensor1 = make_sensor_state_dict("sensor.temperature", "22.5", unit_of_measurement="°C")
        sensor2 = make_sensor_state_dict("sensor.humidity", "60", unit_of_measurement="%")

        for entity_id, state_dict in [("sensor.temperature", sensor1), ("sensor.humidity", sensor2)]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        sensors = states_instance.sensors

        sensor_ids = [eid for eid, _ in sensors]
        assert "sensor.temperature" in sensor_ids
        assert "sensor.humidity" in sensor_ids

    async def test_switches_returns_switch_states(self, hassette_with_state_proxy: "Hassette") -> None:
        """switches property returns DomainStates[SwitchState] containing only switches."""
        hassette = hassette_with_state_proxy

        # Add switch states
        switch1 = make_switch_state_dict("switch.outlet1", "on")
        switch2 = make_switch_state_dict("switch.outlet2", "off")

        for entity_id, state_dict in [("switch.outlet1", switch1), ("switch.outlet2", switch2)]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        switches = states_instance.switches

        switch_ids = [eid for eid, _ in switches]
        assert "switch.outlet1" in switch_ids
        assert "switch.outlet2" in switch_ids

    async def test_iteration_filters_by_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates iteration filters entities by domain."""
        hassette = hassette_with_state_proxy

        # Add various entities
        light = make_light_state_dict("light.test", "on")
        sensor = make_sensor_state_dict("sensor.test", "25")
        switch = make_switch_state_dict("switch.test", "off")

        for entity_id, state_dict in [("light.test", light), ("sensor.test", sensor), ("switch.test", switch)]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)

        # Each domain accessor should only return its own domain
        light_ids = [eid for eid, _ in states_instance.lights]
        sensor_ids = [eid for eid, _ in states_instance.sensors]
        switch_ids = [eid for eid, _ in states_instance.switches]

        assert "light.test" in light_ids, f"Expected 'light.test' in light_ids: {light_ids}"
        assert "sensor.test" in sensor_ids, f"Expected 'sensor.test' in sensor_ids: {sensor_ids}"
        assert "switch.test" in switch_ids, f"Expected 'switch.test' in switch_ids: {switch_ids}"

    async def test_len_counts_domain_entities(self, hassette_with_state_proxy: "Hassette") -> None:
        """len() on DomainStates returns count of entities in that domain."""
        hassette = hassette_with_state_proxy

        # Add multiple lights
        for i in range(3):
            light = make_light_state_dict(f"light.test_{i}", "on")
            event = make_state_change_event(f"light.test_{i}", None, light)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        lights = states_instance.lights

        assert len(lights) >= 3


class TestStatesGenericAccess:
    """Tests for generic state access methods."""

    async def test_all_returns_copy_of_states(self, hassette_with_state_proxy: "Hassette") -> None:
        """all property returns a copy of the entire states dictionary."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add states
        light = make_light_state_dict("light.test", "on")
        event = make_state_change_event("light.test", None, light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        all_states = states_instance.all

        assert isinstance(all_states, dict)
        assert "light.test" in all_states

        # Verify it's a copy (not a reference)
        assert all_states is not proxy.states

    async def test_get_states_with_model(self, hassette_with_state_proxy: "Hassette") -> None:
        """get_states() returns DomainStates for the specified model."""
        hassette = hassette_with_state_proxy

        # Add light
        light = make_light_state_dict("light.test", "on", brightness=200)
        event = make_state_change_event("light.test", None, light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        lights = states_instance.get_states(states.LightState)

        assert isinstance(lights, DomainStates)

        # Should contain light entities
        light_ids = [eid for eid, _ in lights]
        assert "light.test" in light_ids


class TestStatesTypedGetter:
    """Tests for typed state getter."""

    async def test_get_with_type_returns_typed_state(self, hassette_with_state_proxy: "Hassette") -> None:
        """states.get[Model](entity_id) returns typed state."""
        hassette = hassette_with_state_proxy

        # Add light
        light = make_light_state_dict("light.bedroom", "on", brightness=180)
        event = make_state_change_event("light.bedroom", None, light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)

        # Use typed getter
        bedroom_light = states_instance.get[states.LightState]("light.bedroom")

        assert isinstance(bedroom_light, states.LightState)
        assert bedroom_light.entity_id == "light.bedroom"
        assert bedroom_light.attributes.brightness == 180

    async def test_get_with_type_raises_on_missing(self, hassette_with_state_proxy: "Hassette") -> None:
        """states.get[Model](entity_id) raises EntityNotFoundError for missing entity."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        with pytest.raises(EntityNotFoundError, match=r"State for entity_id 'light\.nonexistent' not found"):
            states_instance.get[states.LightState]("light.nonexistent")

    async def test_get_method_returns_none(self, hassette_with_state_proxy: "Hassette") -> None:
        """states.get[Model].get(entity_id) returns None for missing entity."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        result = states_instance.get[states.LightState].get("light.nonexistent")

        assert result is None

    async def test_validates_with_model(self, hassette_with_state_proxy: "Hassette") -> None:
        """Typed getter validates state data with the model."""
        hassette = hassette_with_state_proxy

        # Add sensor
        sensor = make_sensor_state_dict(
            "sensor.temperature", "22.5", unit_of_measurement="°C", device_class="temperature"
        )
        event = make_state_change_event("sensor.temperature", None, sensor)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)

        # Get with correct type
        temp_sensor = states_instance.get[states.SensorState]("sensor.temperature")

        assert isinstance(temp_sensor, states.SensorState)
        assert temp_sensor.attributes.device_class == "temperature"
        assert temp_sensor.attributes.unit_of_measurement == "°C"


class TestDomainStates:
    """Tests for DomainStates helper class."""

    async def test_iteration_over_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates can be iterated to get (entity_id, state) tuples."""
        hassette = hassette_with_state_proxy

        # Add lights
        for i in range(3):
            light = make_light_state_dict(f"light.room_{i}", "on")
            event = make_state_change_event(f"light.room_{i}", None, light)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        lights = states_instance.lights

        # Iterate and collect
        collected = []
        for entity_id, light_state in lights:
            collected.append((entity_id, light_state))
            assert isinstance(light_state, states.LightState)
            assert entity_id.startswith("light.")

        assert len(collected) >= 3

    async def test_len_of_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """len(DomainStates) returns count of entities in domain."""
        hassette = hassette_with_state_proxy

        # Add exactly 2 sensors
        sensor1 = make_sensor_state_dict("sensor.test_1", "10")
        sensor2 = make_sensor_state_dict("sensor.test_2", "20")

        for entity_id, state_dict in [("sensor.test_1", sensor1), ("sensor.test_2", sensor2)]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        sensors = states_instance.sensors

        assert len(sensors) >= 2

    async def test_get_with_matching_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates.get() returns state if domain matches."""
        hassette = hassette_with_state_proxy

        # Add light
        light = make_light_state_dict("light.test", "on", brightness=100)
        event = make_state_change_event("light.test", None, light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)
        lights = states_instance.lights

        result = lights.get("light.test")

        assert result is not None
        assert isinstance(result, states.LightState)
        assert result.entity_id == "light.test"

    async def test_get_with_wrong_domain_returns_none(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates.get() returns None if entity domain doesn't match."""
        hassette = hassette_with_state_proxy

        # Add sensor
        sensor = make_sensor_state_dict("sensor.test", "25")
        event = make_state_change_event("sensor.test", None, sensor)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = States.create(hassette, hassette)

        # Try to get sensor from lights domain
        lights = states_instance.lights
        result = lights.get("sensor.test")

        assert result is None

    async def test_iteration_over_empty_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """Iterating over DomainStates with no entities returns empty."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        # Assuming no climate entities exist
        climate_states = states_instance.climate

        count = sum(1 for _ in climate_states)
        assert count == 0
        assert len(climate_states) == 0


class TestStatesIntegration:
    """Integration tests combining StateProxyResource and States."""

    async def test_states_reflects_proxy_updates(self, hassette_with_state_proxy: "Hassette") -> None:
        """States accessors reflect live updates from StateProxyResource."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        # Initially no lights
        initial_light_count = len(states_instance.lights)

        # Add a light via state change event
        light = make_light_state_dict("light.dynamic", "on", brightness=150)
        event = make_state_change_event("light.dynamic", None, light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        # States should now show the new light
        new_light_count = len(states_instance.lights)
        assert new_light_count == initial_light_count + 1

        # Should be able to retrieve it
        dynamic_light = states_instance.lights.get("light.dynamic")
        assert dynamic_light is not None
        assert dynamic_light.attributes.brightness == 150

    async def test_typed_getter_with_live_updates(self, hassette_with_state_proxy: "Hassette") -> None:
        """Typed getter sees updates from state change events."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        # Add initial state
        light = make_light_state_dict("light.test", "on", brightness=100)
        event = make_state_change_event("light.test", None, light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        # Get initial state
        initial_state = states_instance.get[states.LightState]("light.test")
        assert initial_state.attributes.brightness == 100

        # Update state
        new_light = make_light_state_dict("light.test", "on", brightness=200)
        event = make_state_change_event("light.test", light, new_light)
        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        # Get updated state
        updated_state = states_instance.get[states.LightState]("light.test")
        assert updated_state.attributes.brightness == 200

    async def test_domain_filtering_across_updates(self, hassette_with_state_proxy: "Hassette") -> None:
        """Domain accessors correctly filter across multiple updates."""
        hassette = hassette_with_state_proxy

        states_instance = States.create(hassette, hassette)

        # Add multiple entity types
        entities = [
            ("light.test_1", make_light_state_dict("light.test_1", "on")),
            ("light.test_2", make_light_state_dict("light.test_2", "off")),
            ("sensor.test_1", make_sensor_state_dict("sensor.test_1", "10")),
            ("switch.test_1", make_switch_state_dict("switch.test_1", "on")),
        ]

        for entity_id, state_dict in entities:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Each domain should only contain its entities
        light_ids = {eid for eid, _ in states_instance.lights if eid.startswith("light.test_")}
        sensor_ids = {eid for eid, _ in states_instance.sensors if eid.startswith("sensor.test_")}
        switch_ids = {eid for eid, _ in states_instance.switches if eid.startswith("switch.test_")}

        assert "light.test_1" in light_ids
        assert "light.test_2" in light_ids
        assert "sensor.test_1" in sensor_ids
        assert "switch.test_1" in switch_ids

        # Cross-domain check
        assert "sensor.test_1" not in light_ids
        assert "light.test_1" not in sensor_ids
