import typing
from types import SimpleNamespace

from hassette.bus.predicates import ServiceDataWhere
from hassette.const import ANY_VALUE
from hassette.events import Event


def _make_event(service_data: dict[str, typing.Any]) -> Event:
    """Create a mock CallServiceEvent for testing."""
    payload = SimpleNamespace(data=SimpleNamespace(service_data=service_data))
    return typing.cast("Event", SimpleNamespace(payload=payload))


def test_service_data_where_not_provided_requires_presence() -> None:
    """Test that ServiceDataWhere with ANY_VALUE requires key presence."""
    predicate = ServiceDataWhere({"required": ANY_VALUE})

    assert predicate(_make_event({"required": 0})) is True
    assert predicate(_make_event({})) is False


def test_service_data_where_typing_any_requires_presence() -> None:
    """Test that ServiceDataWhere with ANY_VALUE works with any value type."""
    predicate = ServiceDataWhere({"required": ANY_VALUE})

    assert predicate(_make_event({"required": "value"})) is True
    assert predicate(_make_event({})) is False


def test_service_data_where_exact_value_matching() -> None:
    """Test that ServiceDataWhere matches exact values in service data."""
    predicate = ServiceDataWhere({"brightness": 255, "entity_id": "light.living"})

    matching_event = _make_event({"brightness": 255, "entity_id": "light.living"})
    non_matching_brightness = _make_event({"brightness": 200, "entity_id": "light.living"})
    non_matching_entity = _make_event({"brightness": 255, "entity_id": "light.kitchen"})

    assert predicate(matching_event) is True
    assert predicate(non_matching_brightness) is False
    assert predicate(non_matching_entity) is False


def test_service_data_where_with_callable_conditions() -> None:
    """Test that ServiceDataWhere works with callable condition functions."""

    def brightness_gt_200(value: int) -> bool:
        return value > 200

    predicate = ServiceDataWhere({"brightness": brightness_gt_200})

    high_brightness = _make_event({"brightness": 255})
    low_brightness = _make_event({"brightness": 100})

    assert predicate(high_brightness) is True
    assert predicate(low_brightness) is False


def test_service_data_where_with_glob_patterns() -> None:
    """Test that ServiceDataWhere automatically handles glob patterns."""
    predicate = ServiceDataWhere({"entity_id": "light.*"})

    kitchen_light = _make_event({"entity_id": "light.kitchen"})
    living_light = _make_event({"entity_id": "light.living"})
    sensor_temp = _make_event({"entity_id": "sensor.temperature"})

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

    matching_event = _make_event({"entity_id": "light.kitchen", "brightness": 255, "transition": 2})

    missing_brightness = _make_event({"entity_id": "light.kitchen", "transition": 2})

    wrong_transition = _make_event({"entity_id": "light.kitchen", "brightness": 255, "transition": 1})

    assert predicate(matching_event) is True
    assert predicate(missing_brightness) is False
    assert predicate(wrong_transition) is False


def test_service_data_where_from_kwargs() -> None:
    """Test the ServiceDataWhere.from_kwargs convenience constructor."""
    predicate = ServiceDataWhere.from_kwargs(entity_id="light.*", brightness=255)

    matching_event = _make_event({"entity_id": "light.kitchen", "brightness": 255})
    non_matching_event = _make_event({"entity_id": "sensor.temp", "brightness": 255})

    assert predicate(matching_event) is True
    assert predicate(non_matching_event) is False
