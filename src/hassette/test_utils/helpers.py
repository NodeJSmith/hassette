from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from whenever import ZonedDateTime

from hassette.events import CallServiceEvent, RawStateChangeEvent, create_event_from_hass
from hassette.events.hass.hass import RawStateChangePayload

if TYPE_CHECKING:
    from hassette.events import HassEventEnvelopeDict


def create_state_change_event(
    *,
    entity_id: str,
    old_value: Any,
    new_value: Any,
    old_attrs: dict[str, Any] | None = None,
    new_attrs: dict[str, Any] | None = None,
    topic: str = "hass.event.state_changed",
) -> Any:
    data = RawStateChangePayload(
        entity_id=entity_id,
        old_state={"state": old_value, "attributes": old_attrs or {}},  # pyright: ignore[reportArgumentType]
        new_state={"state": new_value, "attributes": new_attrs or {}},  # pyright: ignore[reportArgumentType]
    )

    payload = SimpleNamespace(data=data)
    return cast("RawStateChangeEvent", SimpleNamespace(topic=topic, payload=payload))


def create_call_service_event(
    *,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
) -> CallServiceEvent:
    """Create a mock call service event for testing."""
    data = SimpleNamespace(domain=domain, service=service, service_data=service_data or {})
    payload = SimpleNamespace(data=data)
    return cast("CallServiceEvent", SimpleNamespace(topic="hass.event.call_service", payload=payload))


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
    now = ZonedDateTime.now("UTC").format_iso()
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
    attributes: dict[str, Any] = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}
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


def make_full_state_change_event(
    entity_id: str, old_state: dict[str, Any] | None, new_state: dict[str, Any] | None
) -> RawStateChangeEvent:
    """Factory for creating state change events.

    Args:
        entity_id: The entity ID
        old_state: Old state dictionary (None for new entity)
        new_state: New state dictionary (None for removed entity)

    Returns:
        RawStateChangeEvent instance
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
    assert isinstance(event, RawStateChangeEvent)
    return event
