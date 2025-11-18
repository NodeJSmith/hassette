"""Fixtures for state proxy and states testing.

Provides factory functions for creating test state data and events.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from whenever import ZonedDateTime

from hassette.events import StateChangeEvent, create_event_from_hass
from hassette.models.states import LightState, SensorState, StateUnion, SwitchState

if TYPE_CHECKING:
    from hassette.types.home_assistant import HassEventEnvelopeDict


def make_state_dict(
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
    last_changed: str | None = None,
    last_updated: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Factory for creating state dictionary in Home Assistant format.

    Args:
        entity_id: The entity ID (e.g., "light.kitchen")
        state: The state value (e.g., "on", "off", "25.5")
        attributes: Entity attributes dict
        last_changed: ISO timestamp string
        last_updated: ISO timestamp string
        context: Event context dict

    Returns:
        Dictionary matching Home Assistant state format
    """
    now = datetime.now(UTC).isoformat()
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": last_changed or now,
        "last_updated": last_updated or now,
        "context": context or {"id": "test_context_id", "parent_id": None, "user_id": None},
    }


def make_light_state_dict(
    entity_id: str = "light.kitchen",
    state: str = "on",
    brightness: int | None = None,
    color_temp: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Factory for creating light state dictionary.

    Args:
        entity_id: The light entity ID
        state: "on" or "off"
        brightness: Brightness value 0-255
        color_temp: Color temperature in mireds
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant light state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}
    if brightness is not None:
        attributes["brightness"] = brightness
    if color_temp is not None:
        attributes["color_temp"] = color_temp

    # Extract base state dict kwargs
    state_kwargs = {k: v for k, v in kwargs.items() if k in ("last_changed", "last_updated", "context")}
    # Add extra attributes
    attributes.update({k: v for k, v in kwargs.items() if k not in state_kwargs})

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_sensor_state_dict(
    entity_id: str = "sensor.temperature",
    state: str = "25.5",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Factory for creating sensor state dictionary.

    Args:
        entity_id: The sensor entity ID
        state: The sensor value as string
        unit_of_measurement: Unit string (e.g., "°C", "%")
        device_class: Device class (e.g., "temperature", "humidity")
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant sensor state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}
    if unit_of_measurement is not None:
        attributes["unit_of_measurement"] = unit_of_measurement
    if device_class is not None:
        attributes["device_class"] = device_class

    state_kwargs = {k: v for k, v in kwargs.items() if k in ("last_changed", "last_updated", "context")}
    attributes.update({k: v for k, v in kwargs.items() if k not in state_kwargs})

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_switch_state_dict(entity_id: str = "switch.outlet", state: str = "on", **kwargs) -> dict[str, Any]:
    """Factory for creating switch state dictionary.

    Args:
        entity_id: The switch entity ID
        state: "on" or "off"
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant switch state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}

    state_kwargs = {k: v for k, v in kwargs.items() if k in ("last_changed", "last_updated", "context")}
    attributes.update({k: v for k, v in kwargs.items() if k not in state_kwargs})

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_state_change_event(
    entity_id: str, old_state: dict[str, Any] | None, new_state: dict[str, Any] | None
) -> StateChangeEvent:
    """Factory for creating state change events.

    Args:
        entity_id: The entity ID
        old_state: Old state dictionary (None for new entity)
        new_state: New state dictionary (None for removed entity)

    Returns:
        StateChangeEvent instance
    """
    envelope: HassEventEnvelopeDict = {
        "id": 1,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "data": {
                "entity_id": entity_id,
                "old_state": old_state,
                "new_state": new_state,
            },
            "origin": "LOCAL",
            "time_fired": ZonedDateTime.now_in_system_tz().format_iso(),
            "context": {"id": "test_context_id", "parent_id": None, "user_id": None},
        },
    }
    event = create_event_from_hass(envelope)
    assert isinstance(event, StateChangeEvent)
    return event


@pytest.fixture
def sample_light_state_dict() -> dict[str, Any]:
    """Sample light state data."""
    return make_light_state_dict("light.bedroom", "on", brightness=200, color_temp=400)


@pytest.fixture
def sample_sensor_state_dict() -> dict[str, Any]:
    """Sample sensor state data."""
    return make_sensor_state_dict(
        "sensor.living_room_temperature", "22.5", unit_of_measurement="°C", device_class="temperature"
    )


@pytest.fixture
def sample_switch_state_dict() -> dict[str, Any]:
    """Sample switch state data."""
    return make_switch_state_dict("switch.living_room_outlet", "off")


@pytest.fixture
def populated_state_cache(
    sample_light_state_dict: dict[str, Any],
    sample_sensor_state_dict: dict[str, Any],
    sample_switch_state_dict: dict[str, Any],
) -> dict[str, StateUnion]:
    """Pre-populated state cache with various entity types.

    Returns:
        Dictionary mapping entity_id to validated state objects
    """
    return {
        sample_light_state_dict["entity_id"]: LightState.model_validate(sample_light_state_dict),
        sample_sensor_state_dict["entity_id"]: SensorState.model_validate(sample_sensor_state_dict),
        sample_switch_state_dict["entity_id"]: SwitchState.model_validate(sample_switch_state_dict),
        # Add some additional entities
        "light.kitchen": LightState.model_validate(make_light_state_dict("light.kitchen", "off")),
        "sensor.humidity": SensorState.model_validate(
            make_sensor_state_dict("sensor.humidity", "65", unit_of_measurement="%", device_class="humidity")
        ),
        "switch.bedroom_outlet": SwitchState.model_validate(make_switch_state_dict("switch.bedroom_outlet", "on")),
    }


@pytest.fixture
def empty_state_cache() -> dict[str, StateUnion]:
    """Empty state cache for testing."""
    return {}
