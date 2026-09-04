"""Tier 1 event/state factory functions.

Contains the eight public factory functions exposed via ``hassette.testing.__all__``
(``create_state_change_event``, ``create_call_service_event``, ``make_state_dict``,
``make_light_state_dict``, ``make_sensor_state_dict``, ``make_switch_state_dict``,
``make_typed_state``, ``make_full_state_change_event``) plus the private helpers they
depend on (``create_hass_event``, ``split_state_kwargs``, ``STATE_DICT_KEYS``).
"""

from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import hassette.utils.date_utils as date_utils
from hassette.conversion import STATE_REGISTRY
from hassette.events import CallServiceEvent, RawStateChangeEvent, create_event_from_hass
from hassette.types import StateT

if TYPE_CHECKING:
    from hassette.events import HassEventEnvelopeDict, HassStateDict

STATE_DICT_KEYS = frozenset({"last_changed", "last_updated", "last_reported", "context"})


def create_hass_event(event_type: str, data: dict[str, Any]) -> Any:
    """Build a HassEventEnvelopeDict envelope and delegate to create_event_from_hass.

    Args:
        event_type: The HA event type string (e.g., "state_changed", "call_service").
        data: The event data dict specific to the event type.

    Returns:
        The typed Event produced by create_event_from_hass.
    """
    envelope: HassEventEnvelopeDict = {
        "id": 1,  # Discarded by create_event_from_hass; present only to satisfy HassEventEnvelopeDict shape
        "type": "event",
        "event": {
            "event_type": event_type,
            "data": data,
            "origin": "LOCAL",
            "time_fired": date_utils.now().format_iso(),
            "context": {"id": str(uuid4()), "parent_id": None, "user_id": None},
        },
    }
    return create_event_from_hass(envelope)


def create_state_change_event(
    *,
    entity_id: str,
    old_value: Any,
    new_value: Any,
    old_attrs: dict[str, Any] | None = None,
    new_attrs: dict[str, Any] | None = None,
) -> RawStateChangeEvent:
    """Create a state change event for testing.

    Pass ``None`` for ``old_value`` or ``new_value`` to simulate entity creation or removal
    (produces ``None`` for that state dict, not ``{"state": None, ...}``).
    """
    old_state = make_state_dict(entity_id, str(old_value), attributes=old_attrs) if old_value is not None else None
    new_state = make_state_dict(entity_id, str(new_value), attributes=new_attrs) if new_value is not None else None
    event = create_hass_event(
        "state_changed",
        {"entity_id": entity_id, "old_state": old_state, "new_state": new_state},
    )
    assert isinstance(event, RawStateChangeEvent)
    return event


def create_call_service_event(
    *,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
) -> CallServiceEvent:
    """Create a call service event for testing."""
    event = create_hass_event(
        "call_service",
        {"domain": domain, "service": service, "service_data": service_data or {}},
    )
    assert isinstance(event, CallServiceEvent)
    return event


def make_state_dict(
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
    last_changed: str | None = None,
    last_updated: str | None = None,
    last_reported: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Factory for creating state dictionary in Home Assistant format.

    Args:
        entity_id: The entity ID (e.g., "light.kitchen")
        state: The state value (e.g., "on", "off", "25.5")
        attributes: Entity attributes dict
        last_changed: ISO timestamp string
        last_updated: ISO timestamp string
        last_reported: ISO timestamp string
        context: Event context dict

    Returns:
        Dictionary matching Home Assistant state format
    """
    now = date_utils.now().format_iso()
    result = {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": last_changed or now,
        "last_updated": last_updated or now,
        "context": context or {"id": str(uuid4()), "parent_id": None, "user_id": None},
    }
    if last_reported is not None:
        result["last_reported"] = last_reported
    return result


def split_state_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state_kwargs = {k: v for k, v in kwargs.items() if k in STATE_DICT_KEYS}
    extra_attrs = {k: v for k, v in kwargs.items() if k not in STATE_DICT_KEYS}
    return state_kwargs, extra_attrs


def make_light_state_dict(
    entity_id: str = "light.kitchen",
    state: str = "on",
    brightness: int | None = None,
    color_temp: int | None = None,
    **kwargs: Any,
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

    state_kwargs, extra_attrs = split_state_kwargs(kwargs)
    attributes.update(extra_attrs)

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_sensor_state_dict(
    entity_id: str = "sensor.temperature",
    state: str = "25.5",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    **kwargs: Any,
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

    state_kwargs, extra_attrs = split_state_kwargs(kwargs)
    attributes.update(extra_attrs)

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_switch_state_dict(entity_id: str = "switch.outlet", state: str = "on", **kwargs: Any) -> dict[str, Any]:
    """Factory for creating switch state dictionary.

    Args:
        entity_id: The switch entity ID
        state: "on" or "off"
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant switch state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}

    state_kwargs, extra_attrs = split_state_kwargs(kwargs)
    attributes.update(extra_attrs)

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_typed_state(state_class: type[StateT], state_dict: "dict[str, Any]") -> StateT:
    """Convert a raw state dict to a typed state via the conversion pipeline.

    Replaces direct ``XState.model_validate(dict)`` calls in tests; routes through
    the conversion entry point so tests exercise the same path as production.

    Args:
        state_class: The target state model class (e.g., LightState, SensorState).
        state_dict: A raw state dict as produced by make_state_dict / make_*_state_dict.

    Returns:
        The typed state instance.
    """
    entity_id: str = state_dict.get("entity_id", "<unknown>")
    result = STATE_REGISTRY.coerce_and_construct(state_class, cast("HassStateDict", state_dict), entity_id)
    assert isinstance(result, state_class)
    return result


def make_full_state_change_event(
    entity_id: str, old_state: dict[str, Any] | None, new_state: dict[str, Any] | None
) -> RawStateChangeEvent:
    """Factory for creating state change events from pre-built state dicts.

    Args:
        entity_id: The entity ID
        old_state: Old state dictionary (None for new entity)
        new_state: New state dictionary (None for removed entity)

    Returns:
        RawStateChangeEvent instance
    """
    event = create_hass_event(
        "state_changed",
        {"entity_id": entity_id, "old_state": old_state, "new_state": new_state},
    )
    assert isinstance(event, RawStateChangeEvent)
    return event
