"""Tests for the new predicate architecture in hassette.core.resources.bus.predicates."""

import typing
from types import SimpleNamespace

import pytest

from hassette.const.misc import MISSING_VALUE, NOT_PROVIDED
from hassette.core.resources.bus.predicates import (
    AllOf,
    AnyOf,
    AttrDidChange,
    AttrFrom,
    AttrTo,
    DomainMatches,
    EntityMatches,
    From,
    Guard,
    Not,
    ServiceDataWhere,
    ServiceMatches,
    StateDidChange,
    To,
    ValueIs,
)
from hassette.core.resources.bus.predicates.accessors import (
    get_attr_new,
    get_attr_old,
    get_domain,
    get_entity_id,
    get_service_data_key,
    get_state_value_new,
    get_state_value_old,
)
from hassette.core.resources.bus.predicates.conditions import Contains, EndsWith, Glob, Present, Regex, StartsWith
from hassette.core.resources.bus.predicates.utils import compare_value, ensure_tuple, normalize_where
from hassette.events import CallServiceEvent, Event


class _MockAttrs:
    """Mock attributes class for testing."""

    def __init__(self, values: dict[str, typing.Any]):
        self._values = values

    def model_dump(self) -> dict[str, typing.Any]:
        return self._values


def always_true(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
    return True


def always_false(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
    return False


def _create_state_event(
    *,
    entity_id: str,
    old_value: typing.Any,
    new_value: typing.Any,
    old_attrs: dict[str, typing.Any] | None = None,
    new_attrs: dict[str, typing.Any] | None = None,
) -> Event:
    """Create a mock state change event for testing."""
    data = SimpleNamespace(
        entity_id=entity_id,
        domain=entity_id.split(".")[0] if "." in entity_id else None,
        old_state_value=old_value,
        new_state_value=new_value,
        old_state=SimpleNamespace(attributes=_MockAttrs(old_attrs or {})) if old_attrs is not None else None,
        new_state=SimpleNamespace(attributes=_MockAttrs(new_attrs or {})) if new_attrs is not None else None,
    )
    return typing.cast("Event", SimpleNamespace(topic="hass.event.state_changed", payload=SimpleNamespace(data=data)))


def _create_service_event(
    *,
    domain: str,
    service: str,
    service_data: dict[str, typing.Any] | None = None,
) -> CallServiceEvent:
    """Create a mock call service event for testing."""
    data = SimpleNamespace(domain=domain, service=service, service_data=service_data or {})
    payload = SimpleNamespace(data=data)
    return typing.cast("CallServiceEvent", SimpleNamespace(topic="hass.event.call_service", payload=payload))


# Base predicate tests
def test_allof_evaluates_all_predicates() -> None:
    """Test that AllOf returns True only when all predicates return True."""

    mock_event = SimpleNamespace()

    # All true
    predicate = AllOf((always_true, always_true))
    assert predicate(mock_event) is True  # pyright: ignore[reportArgumentType]

    # Mixed
    predicate = AllOf((always_true, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]

    # All false
    predicate = AllOf((always_false, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]


def test_anyof_evaluates_any_predicate() -> None:
    """Test that AnyOf returns True when any predicate returns True."""

    mock_event = SimpleNamespace()

    # Any true
    predicate = AnyOf((always_false, always_true))
    assert predicate(mock_event) is True  # pyright: ignore[reportArgumentType]

    # All false
    predicate = AnyOf((always_false, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]


def test_not_inverts_predicate() -> None:
    """Test that Not inverts the result of wrapped predicate."""

    mock_event = SimpleNamespace()

    assert Not(always_true)(mock_event) is False  # pyright: ignore[reportArgumentType]
    assert Not(always_false)(mock_event) is True  # pyright: ignore[reportArgumentType]


def test_guard_wraps_callable() -> None:
    """Test that Guard wraps arbitrary callables as predicates."""
    sentinel = object()

    def check_identity(event) -> bool:
        return event is sentinel

    guard = Guard(check_identity)
    assert guard(sentinel) is True
    assert guard(object()) is False


# ValueIs tests
def test_value_is_with_literal_condition() -> None:
    """Test ValueIs with literal value conditions."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    # Test old state value
    predicate = ValueIs(source=get_state_value_old, condition="off")
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    predicate = ValueIs(source=get_state_value_old, condition="on")
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]

    # Test new state value
    predicate = ValueIs(source=get_state_value_new, condition="on")
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]


def test_value_is_with_callable_condition() -> None:
    """Test ValueIs with callable conditions."""
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=25)

    def gt_twenty(value: int) -> bool:
        return value > 20

    predicate = ValueIs(source=get_state_value_new, condition=gt_twenty)
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    predicate = ValueIs(source=get_state_value_old, condition=gt_twenty)
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]


def test_value_is_with_not_provided() -> None:
    """Test ValueIs with NOT_PROVIDED (no constraint)."""
    event = _create_state_event(entity_id="any.entity", old_value="any", new_value="any")

    predicate = ValueIs(source=get_state_value_new, condition=NOT_PROVIDED)
    assert predicate(event) is True


# From/To predicates
def test_from_predicate() -> None:
    """Test From predicate for old state values."""
    event = _create_state_event(entity_id="light.living", old_value="off", new_value="on")

    assert From("off")(event) is True
    assert From("on")(event) is False


def test_to_predicate() -> None:
    """Test To predicate for new state values."""
    event = _create_state_event(entity_id="light.living", old_value="off", new_value="on")

    assert To("on")(event) is True
    assert To("off")(event) is False


def test_attr_from_predicate() -> None:
    """Test AttrFrom predicate for old attribute values."""
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert AttrFrom("brightness", 100)(event) is True
    assert AttrFrom("brightness", 200)(event) is False


def test_attr_to_predicate() -> None:
    """Test AttrTo predicate for new attribute values."""
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert AttrTo("brightness", 200)(event) is True
    assert AttrTo("brightness", 100)(event) is False


# Change detection predicates
def test_state_did_change() -> None:
    """Test StateDidChange predicate detects state transitions."""
    # State changed
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=25)
    predicate = StateDidChange()
    assert predicate(event) is True

    # State unchanged
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=20)
    assert predicate(event) is False


def test_attr_did_change() -> None:
    """Test AttrDidChange predicate detects attribute changes."""
    # Attribute changed
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )
    predicate = AttrDidChange("brightness")
    assert predicate(event) is True

    # Attribute unchanged
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 100},
    )
    assert predicate(event) is False


# Entity/Domain matching predicates
def test_entity_matches() -> None:
    """Test EntityMatches predicate with literal and glob patterns."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    # Exact match
    predicate = EntityMatches("light.kitchen")
    assert predicate(event) is True

    # No match
    predicate = EntityMatches("light.living")
    assert predicate(event) is False

    # Glob match
    predicate = EntityMatches("light.*")
    assert predicate(event) is True

    predicate = EntityMatches("sensor.*")
    assert predicate(event) is False


def test_domain_matches() -> None:
    """Test DomainMatches predicate with literal and glob patterns."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    # Exact match
    predicate = DomainMatches("light")
    assert predicate(event) is True

    # No match
    predicate = DomainMatches("sensor")
    assert predicate(event) is False


def test_service_matches() -> None:
    """Test ServiceMatches predicate."""
    event = _create_service_event(domain="light", service="turn_on")

    # Exact match
    predicate = ServiceMatches("turn_on")
    assert predicate(event) is True

    # No match
    predicate = ServiceMatches("turn_off")
    assert predicate(event) is False

    # Glob match
    predicate = ServiceMatches("turn_*")
    assert predicate(event) is True


# ServiceDataWhere tests
def test_service_data_where_exact_match() -> None:
    """Test ServiceDataWhere with exact value matching."""
    event = _create_service_event(
        domain="light", service="turn_on", service_data={"entity_id": "light.kitchen", "brightness": 255}
    )

    predicate = ServiceDataWhere({"entity_id": "light.kitchen", "brightness": 255})
    assert predicate(event) is True

    predicate = ServiceDataWhere({"entity_id": "light.living"})
    assert predicate(event) is False


def test_service_data_where_with_callable() -> None:
    """Test ServiceDataWhere with callable conditions."""
    event = _create_service_event(domain="light", service="turn_on", service_data={"brightness": 255})

    def brightness_gt_200(value: int) -> bool:
        return value > 200

    predicate = ServiceDataWhere({"brightness": brightness_gt_200})
    assert predicate(event) is True


def test_service_data_where_with_not_provided() -> None:
    """Test ServiceDataWhere requiring key presence with NOT_PROVIDED."""
    event = _create_service_event(domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"})

    # Key exists
    predicate = ServiceDataWhere({"entity_id": NOT_PROVIDED})
    assert predicate(event) is True

    # Key missing
    predicate = ServiceDataWhere({"brightness": NOT_PROVIDED})
    assert predicate(event) is False


def test_service_data_where_with_globs() -> None:
    """Test ServiceDataWhere with automatic glob pattern handling."""
    event = _create_service_event(domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"})

    predicate = ServiceDataWhere({"entity_id": "light.*"})
    assert predicate(event) is True

    predicate = ServiceDataWhere({"entity_id": "sensor.*"})
    assert predicate(event) is False


# Condition tests
def test_glob_condition() -> None:
    """Test Glob condition matcher."""
    glob = Glob("light.*")

    assert glob("light.kitchen") is True
    assert glob("light.living") is True
    assert glob("sensor.temp") is False
    assert glob(123) is False  # Non-string


def test_startswith_condition() -> None:
    """Test StartsWith condition matcher."""
    condition = StartsWith("light.")

    assert condition("light.kitchen") is True
    assert condition("light.living") is True
    assert condition("sensor.temp") is False
    assert condition(123) is False  # Non-string


def test_endswith_condition() -> None:
    """Test EndsWith condition matcher."""
    condition = EndsWith(".kitchen")

    assert condition("light.kitchen") is True
    assert condition("sensor.kitchen") is True
    assert condition("light.living") is False
    assert condition(123) is False  # Non-string


def test_contains_condition() -> None:
    """Test Contains condition matcher."""
    condition = Contains("kitchen")

    assert condition("light.kitchen") is True
    assert condition("sensor.kitchen_temp") is True
    assert condition("light.living") is False
    assert condition(123) is False  # Non-string


def test_regex_condition() -> None:
    """Test Regex condition matcher."""
    condition = Regex(r"light\..*kitchen")

    assert condition("light.main_kitchen") is True
    assert condition("light.back_kitchen") is True
    assert condition("light.living") is False
    assert condition("sensor.kitchen") is False
    assert condition(123) is False  # Non-string


def test_present_condition() -> None:
    """Test Present condition matcher."""
    condition = Present()

    assert condition("any_value") is True
    assert condition(0) is True
    assert condition(False) is True
    assert condition(None) is True
    assert condition(MISSING_VALUE) is False


# Utility function tests
def test_compare_value_with_literals() -> None:
    """Test compare_value with literal conditions."""
    assert compare_value("exact", "exact") is True
    assert compare_value("exact", "different") is False
    assert compare_value(42, 42) is True
    assert compare_value(42, 43) is False


def test_compare_value_with_sequences() -> None:
    """Test compare_value with sequence membership."""
    assert compare_value("target", ["target", "other"]) is True
    assert compare_value("missing", ["target", "other"]) is False
    assert compare_value("target", {"target", "other"}) is True
    assert compare_value("missing", {"target", "other"}) is False


def test_compare_value_with_not_provided() -> None:
    """Test compare_value with NOT_PROVIDED sentinel."""
    assert compare_value(NOT_PROVIDED, "any_value") is True


def test_compare_value_with_callable() -> None:
    """Test compare_value with callable conditions."""

    def gt_ten(value: int) -> bool:
        return value > 10

    assert compare_value(gt_ten, 15) is True
    assert compare_value(gt_ten, 5) is False


def test_compare_value_error_handling() -> None:
    """Test compare_value error handling for invalid conditions."""

    # Async callable should raise
    async def async_predicate(value):  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return True

    with pytest.raises(TypeError, match="Async predicates are not supported"):
        compare_value(async_predicate, "value")

    # Non-bool return should raise
    def non_bool_predicate(value):  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return "not_bool"

    with pytest.raises(TypeError, match="Predicate must return bool"):
        compare_value(non_bool_predicate, "value")


def test_ensure_tuple_flattening() -> None:
    """Test ensure_tuple flattens nested predicate sequences."""

    def pred1(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return True

    def pred2(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return False

    def pred3(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return True

    # Nested sequence
    result = ensure_tuple([pred1, (pred2, pred3)])  # pyright: ignore[reportArgumentType]
    assert len(result) == 3
    assert result == (pred1, pred2, pred3)

    # Single predicate
    result = ensure_tuple(pred1)
    assert result == (pred1,)

    # Flat sequence
    result = ensure_tuple([pred1, pred2])
    assert result == (pred1, pred2)


def test_normalize_where_handling() -> None:
    """Test normalize_where with various input types."""

    # None input
    assert normalize_where(None) is None

    # Single predicate
    result = normalize_where(always_true)
    assert result is always_true

    # Sequence of predicates
    result = normalize_where([always_true, always_false])
    assert isinstance(result, AllOf)
    assert len(result.predicates) == 2


# Accessor tests
def test_get_entity_id_accessor() -> None:
    """Test get_entity_id accessor function."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert get_entity_id(event) == "light.kitchen"


def test_get_domain_accessor() -> None:
    """Test get_domain accessor function."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert get_domain(event) == "light"


def test_get_state_value_accessors() -> None:
    """Test state value accessor functions."""
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=25)

    assert get_state_value_old(event) == 20
    assert get_state_value_new(event) == 25


def test_get_attr_accessors() -> None:
    """Test attribute accessor functions."""
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100, "color": "red"},
        new_attrs={"brightness": 200, "color": "blue"},
    )

    assert get_attr_old("brightness")(event) == 100
    assert get_attr_new("brightness")(event) == 200
    assert get_attr_old("color")(event) == "red"
    assert get_attr_new("color")(event) == "blue"

    # Missing attribute
    assert get_attr_old("missing")(event) == MISSING_VALUE
    assert get_attr_new("missing")(event) == MISSING_VALUE


def test_get_service_data_key_accessor() -> None:
    """Test get_service_data_key accessor function."""
    event = _create_service_event(
        domain="light", service="turn_on", service_data={"entity_id": "light.kitchen", "brightness": 255}
    )

    accessor = get_service_data_key("entity_id")
    assert accessor(event) == "light.kitchen"

    accessor = get_service_data_key("brightness")
    assert accessor(event) == 255

    # Missing key
    accessor = get_service_data_key("missing")
    assert accessor(event) == MISSING_VALUE
