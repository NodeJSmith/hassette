"""Tests for States class functionality.

Tests cover domain-specific accessors, generic state access,
typed getters, and DomainStates helper class.
"""

import asyncio
from copy import copy
from typing import TYPE_CHECKING

import pytest

from hassette.models import states
from hassette.state_manager import DomainStates, StateManager
from hassette.test_utils.helpers import (
    make_full_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_dict,
    make_switch_state_dict,
)
from hassette.types import Topic

if TYPE_CHECKING:
    from hassette import Hassette


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
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Create StateManager instance and access lights
        states_instance = StateManager.create(hassette, hassette)
        lights = states_instance.light

        assert isinstance(lights, DomainStates)

        # Iterate and verify only lights are returned
        light_ids = []
        for entity_id, light_state in lights:
            light_ids.append(entity_id)
            assert isinstance(light_state, states.LightState), (
                f"Expected LightState but got {type(light_state).__name__}"
            )
            assert not isinstance(light_state, states.BaseState) or isinstance(light_state, states.LightState), (
                "Should be LightState, not bare BaseState"
            )
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
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        sensors = states_instance.sensor

        sensor_ids = []
        for eid, sensor_state in sensors:
            sensor_ids.append(eid)
            assert isinstance(sensor_state, states.SensorState), (
                f"Expected SensorState but got {type(sensor_state).__name__}"
            )
            assert type(sensor_state) is not states.BaseState, "Should be SensorState, not bare BaseState"

        assert "sensor.temperature" in sensor_ids
        assert "sensor.humidity" in sensor_ids

    async def test_switches_returns_switch_states(self, hassette_with_state_proxy: "Hassette") -> None:
        """switches property returns DomainStates[SwitchState] containing only switches."""
        hassette = hassette_with_state_proxy

        # Add switch states
        switch1 = make_switch_state_dict("switch.outlet1", "on")
        switch2 = make_switch_state_dict("switch.outlet2", "off")

        for entity_id, state_dict in [("switch.outlet1", switch1), ("switch.outlet2", switch2)]:
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        switches = states_instance.switch

        switch_ids = []
        for eid, switch_state in switches:
            switch_ids.append(eid)
            assert isinstance(switch_state, states.SwitchState), (
                f"Expected SwitchState but got {type(switch_state).__name__}"
            )
            assert type(switch_state) is not states.BaseState, "Should be SwitchState, not bare BaseState"

        assert "switch.outlet1" in switch_ids
        assert "switch.outlet2" in switch_ids


class TestStatesGenericAccess:
    """Tests for generic state access methods."""

    async def test_get_states_with_model(self, hassette_with_state_proxy: "Hassette") -> None:
        """get_states() returns DomainStates for the specified model."""
        hassette = hassette_with_state_proxy

        # Add light
        light = make_light_state_dict("light.test", "on", brightness=200)
        event = make_full_state_change_event("light.test", None, light)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        lights = states_instance.get_states(states.LightState)

        assert isinstance(lights, DomainStates)

        # Should contain light entities with proper types
        light_ids = []
        for eid, light_state in lights:
            light_ids.append(eid)
            assert isinstance(light_state, states.LightState), f"get_states returned {type(light_state).__name__}"
            assert type(light_state) is not states.BaseState, "Should be LightState, not bare BaseState"

        assert "light.test" in light_ids


class TestDomainStates:
    """Tests for DomainStates helper class."""

    async def test_value_with_decimals_does_not_lose_precision(self, hassette_with_state_proxy: "Hassette") -> None:
        """Test that state values with decimals do not lose precision when converted."""
        hassette = hassette_with_state_proxy

        # Add a sensor state with a decimal value
        old_sensor_dict = make_state_dict("input_number.test_value", "22.1")
        new_sensor_dict = make_state_dict("input_number.test_value", "22.5")
        event = make_full_state_change_event("input_number.test_value", old_sensor_dict, new_sensor_dict)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)

        assert states_instance.input_number.get("input_number.test_value").value == 22.5

        # initial issue had second access of value causing loss of precision due to double conversion
        assert states_instance.input_number.get("input_number.test_value").value == 22.5

    async def test_states_are_cached_until_changed(self, hassette_with_state_proxy: "Hassette") -> None:
        """Test that state objects are cached until the state changes."""
        hassette = hassette_with_state_proxy

        # Add a sensor state with a decimal value
        old_state_dict = make_state_dict("input_number.test_value", "22.1")
        new_state_dict = make_state_dict("input_number.test_value", "22.5")
        event = make_full_state_change_event("input_number.test_value", old_state_dict, new_state_dict)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        input_number_manager = states_instance.input_number

        orig_obj = input_number_manager.get("input_number.test_value")
        obj_id = id(orig_obj)
        assert input_number_manager.get("input_number.test_value") is orig_obj, (
            "State object should be the same before state change"
        )
        assert id(input_number_manager.get("input_number.test_value")) == obj_id, (
            "State object ID should remain the same before state change"
        )

        old_state_dict = copy(new_state_dict)
        new_state_dict = make_state_dict("input_number.test_value", "23.0")
        event = make_full_state_change_event("input_number.test_value", old_state_dict, new_state_dict)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        assert input_number_manager.get("input_number.test_value") is not orig_obj, (
            "State object should be replaced after state change"
        )

    async def test_iteration_over_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates can be iterated to get (entity_id, state) tuples."""
        hassette = hassette_with_state_proxy

        # Add lights
        for i in range(3):
            light = make_light_state_dict(f"light.room_{i}", "on")
            event = make_full_state_change_event(f"light.room_{i}", None, light)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        lights = states_instance.light

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
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        sensors = states_instance.sensor

        assert len(sensors) >= 2

    async def test_get_with_matching_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates.get() returns state if domain matches."""
        hassette = hassette_with_state_proxy

        # Add light
        light = make_light_state_dict("light.test", "on", brightness=100)
        event = make_full_state_change_event("light.test", None, light)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)
        lights = states_instance.light

        result = lights.get("light.test")

        assert result is not None
        assert isinstance(result, states.LightState), f"Expected LightState but got {type(result).__name__}"
        assert type(result) is not states.BaseState, "Should be LightState, not bare BaseState"
        assert result.entity_id == "light.test"
        assert hasattr(result.attributes, "brightness"), "LightState should have brightness attribute"

    async def test_get_with_wrong_domain_raises_value_error(self, hassette_with_state_proxy: "Hassette") -> None:
        """DomainStates.get() returns None if entity domain doesn't match."""
        hassette = hassette_with_state_proxy

        # Add sensor
        sensor = make_sensor_state_dict("sensor.test", "25")
        event = make_full_state_change_event("sensor.test", None, sensor)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)

        # Try to get sensor from lights domain
        lights = states_instance.light
        with pytest.raises(ValueError, match=r"Entity ID 'sensor\.test' does not belong to domain 'light'"):
            lights.get("sensor.test")

    async def test_iteration_over_empty_domain(self, hassette_with_state_proxy: "Hassette") -> None:
        """Iterating over DomainStates with no entities returns empty."""
        hassette = hassette_with_state_proxy

        states_instance = StateManager.create(hassette, hassette)

        # Assuming no climate entities exist
        climate_states = states_instance.climate

        count = sum(1 for _ in climate_states)
        assert count == 0
        assert len(climate_states) == 0


class TestStatesIntegration:
    """Integration tests combining StateProxy and StateManager."""

    async def test_proxy_stores_base_states_accessors_convert(self, hassette_with_state_proxy: "Hassette") -> None:
        """StateProxy stores BaseState, States accessors convert to domain-specific types."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy
        states_instance = StateManager.create(hassette, hassette)

        # Add various entity types
        light = make_light_state_dict("light.test", "on", brightness=150)
        sensor = make_sensor_state_dict("sensor.test", "25.5", unit_of_measurement="°C")
        switch = make_switch_state_dict("switch.test", "off")

        for entity_id, state_dict in [
            ("light.test", light),
            ("sensor.test", sensor),
            ("switch.test", switch),
        ]:
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Verify proxy stores BaseState (not domain-specific types)
        light_state_raw = proxy.states.get("light.test")
        assert light_state_raw is not None
        assert isinstance(light_state_raw, dict), (
            f"Proxy should store HassStateDict, got {type(light_state_raw).__name__}"
        )

        sensor_state_raw = proxy.states.get("sensor.test")
        assert sensor_state_raw is not None
        assert isinstance(sensor_state_raw, dict), (
            f"Proxy should store HassStateDict, got {type(sensor_state_raw).__name__}"
        )

        # But States accessors should convert to domain-specific types
        light_state = states_instance.light.get("light.test")
        assert light_state is not None
        assert isinstance(light_state, states.LightState), (
            f"States accessor should return LightState, got {type(light_state).__name__}"
        )

        sensor_state = states_instance.sensor.get("sensor.test")
        assert sensor_state is not None
        assert isinstance(sensor_state, states.SensorState), (
            f"States accessor should return SensorState, got {type(sensor_state).__name__}"
        )

    async def test_states_reflects_proxy_updates(self, hassette_with_state_proxy: "Hassette") -> None:
        """States accessors reflect live updates from StateProxy."""
        hassette = hassette_with_state_proxy

        states_instance = StateManager.create(hassette, hassette)

        light_manager = states_instance.light

        # Initially no lights
        initial_light_count = len(light_manager)

        # Add a light via state change event
        light = make_light_state_dict("light.dynamic", "on", brightness=150)
        event = make_full_state_change_event("light.dynamic", None, light)
        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        # States should now show the new light
        new_light_count = len(light_manager)
        assert new_light_count == initial_light_count + 1

        # Should be able to retrieve it
        dynamic_light = light_manager.get("light.dynamic")
        assert dynamic_light is not None
        assert isinstance(dynamic_light, states.LightState), (
            f"Expected LightState but got {type(dynamic_light).__name__}"
        )
        assert type(dynamic_light) is not states.BaseState, "Should be LightState, not bare BaseState"
        assert dynamic_light.attributes.brightness == 150

    async def test_domain_filtering_across_updates(self, hassette_with_state_proxy: "Hassette") -> None:
        """Domain accessors correctly filter across multiple updates."""
        hassette = hassette_with_state_proxy

        states_instance = StateManager.create(hassette, hassette)

        # Add multiple entity types
        entities = [
            ("light.test_1", make_light_state_dict("light.test_1", "on")),
            ("light.test_2", make_light_state_dict("light.test_2", "off")),
            ("sensor.test_1", make_sensor_state_dict("sensor.test_1", "10")),
            ("switch.test_1", make_switch_state_dict("switch.test_1", "on")),
        ]

        for entity_id, state_dict in entities:
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Each domain should only contain its entities with proper types
        light_ids = set()
        for eid, light_state in states_instance.light:
            if eid.startswith("light.test_"):
                light_ids.add(eid)
                assert isinstance(light_state, states.LightState), (
                    f"Light iteration returned {type(light_state).__name__}"
                )

        sensor_ids = set()
        for eid, sensor_state in states_instance.sensor:
            if eid.startswith("sensor.test_"):
                sensor_ids.add(eid)
                assert isinstance(sensor_state, states.SensorState), (
                    f"Sensor iteration returned {type(sensor_state).__name__}"
                )

        switch_ids = set()
        for eid, switch_state in states_instance.switch:
            if eid.startswith("switch.test_"):
                switch_ids.add(eid)
                assert isinstance(switch_state, states.SwitchState), (
                    f"Switch iteration returned {type(switch_state).__name__}"
                )

        assert "light.test_1" in light_ids
        assert "light.test_2" in light_ids
        assert "sensor.test_1" in sensor_ids
        assert "switch.test_1" in switch_ids

        # Cross-domain check
        assert "sensor.test_1" not in light_ids
        assert "light.test_1" not in sensor_ids

    async def test_yield_items(self, hassette_with_state_proxy: "Hassette") -> None:
        """Test that yield_items returns the correct items lazily."""
        hassette = hassette_with_state_proxy

        # Add multiple entity types
        entities = [
            ("light.test_1", make_light_state_dict("light.test_1", "on")),
            ("light.test_2", make_light_state_dict("light.test_2", "off")),
        ]

        for entity_id, state_dict in entities:
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        states_instance = StateManager.create(hassette, hassette)

        light_manager = states_instance.light

        assert len(light_manager._cache) == 0

        for i, (entity_id, light_state) in enumerate(light_manager.iteritems()):
            assert isinstance(light_state, states.LightState)
            assert entity_id.startswith("light.")
            assert len(light_manager._cache) == i + 1

        for _, light_state in light_manager:
            assert isinstance(light_state, states.LightState)
            # The cache should already be populated from the previous iteritems call
            assert len(light_manager._cache) == i + 1
