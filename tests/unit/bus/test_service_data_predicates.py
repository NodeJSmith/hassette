"""Tests for ServiceDataWhere predicate.

Tests the ServiceDataWhere predicate which matches service_data dictionaries
with support for exact values, callables, glob patterns, and ANY_VALUE checks.
"""

import typing
from types import SimpleNamespace

from hassette.const import ANY_VALUE
from hassette.event_handling.predicates import ServiceDataWhere
from hassette.events import Event


def make_event(service_data: dict[str, typing.Any]) -> Event:
    """Create a mock CallServiceEvent for testing."""
    payload = SimpleNamespace(data=SimpleNamespace(service_data=service_data))
    return typing.cast("Event", SimpleNamespace(payload=payload))


def test_service_data_where_not_provided_requires_presence() -> None:
    """Test that ServiceDataWhere with ANY_VALUE requires key presence."""
    predicate = ServiceDataWhere({"required": ANY_VALUE})

    assert predicate(make_event({"required": 0})) is True
    assert predicate(make_event({})) is False


def test_service_data_where_exact_value_matching() -> None:
    """Test that ServiceDataWhere matches exact values in service data."""
    predicate = ServiceDataWhere({"brightness": 255, "entity_id": "light.living"})

    matching_event = make_event({"brightness": 255, "entity_id": "light.living"})
    non_matching_brightness = make_event({"brightness": 200, "entity_id": "light.living"})
    non_matching_entity = make_event({"brightness": 255, "entity_id": "light.kitchen"})

    assert predicate(matching_event) is True
    assert predicate(non_matching_brightness) is False
    assert predicate(non_matching_entity) is False


def test_service_data_where_with_callable_conditions() -> None:
    """Test that ServiceDataWhere works with callable condition functions."""

    def brightness_gt_200(value: int) -> bool:
        return value > 200

    predicate = ServiceDataWhere({"brightness": brightness_gt_200})

    high_brightness = make_event({"brightness": 255})
    low_brightness = make_event({"brightness": 100})

    assert predicate(high_brightness) is True
    assert predicate(low_brightness) is False


def test_service_data_where_with_glob_patterns() -> None:
    """Test that ServiceDataWhere automatically handles glob patterns."""
    predicate = ServiceDataWhere({"entity_id": "light.*"})

    kitchen_light = make_event({"entity_id": "light.kitchen"})
    living_light = make_event({"entity_id": "light.living"})
    sensor_temp = make_event({"entity_id": "sensor.temperature"})

    assert predicate(kitchen_light) is True
    assert predicate(living_light) is True
    assert predicate(sensor_temp) is False


def test_service_data_where_multiple_conditions() -> None:
    """Test that ServiceDataWhere evaluates all conditions (AND logic)."""
    predicate = ServiceDataWhere(
        {
            "entity_id": "light.*",
            "brightness": ANY_VALUE,  # Must be present
            "transition": 2,
        }
    )

    # All conditions match
    matching_event = make_event({"entity_id": "light.kitchen", "brightness": 255, "transition": 2})
    assert predicate(matching_event) is True

    # Missing brightness key
    missing_brightness = make_event({"entity_id": "light.kitchen", "transition": 2})
    assert predicate(missing_brightness) is False

    # Wrong transition value
    wrong_transition = make_event({"entity_id": "light.kitchen", "brightness": 255, "transition": 5})
    assert predicate(wrong_transition) is False

    # Wrong entity pattern
    wrong_entity = make_event({"entity_id": "sensor.temp", "brightness": 255, "transition": 2})
    assert predicate(wrong_entity) is False
