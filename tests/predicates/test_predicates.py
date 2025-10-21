"""Tests for the new predicate architecture in hassette.core.resources.bus.predicates."""

import typing
from types import SimpleNamespace

import pytest

from hassette import accessors as A
from hassette import conditions as C
from hassette import predicates as P
from hassette.const import MISSING_VALUE, NOT_PROVIDED
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
    predicate = P.AllOf((always_true, always_true))
    assert predicate(mock_event) is True  # pyright: ignore[reportArgumentType]

    # Mixed
    predicate = P.AllOf((always_true, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]

    # All false
    predicate = P.AllOf((always_false, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]


def test_anyof_evaluates_any_predicate() -> None:
    """Test that AnyOf returns True when any predicate returns True."""

    mock_event = SimpleNamespace()

    # Any true
    predicate = P.AnyOf((always_false, always_true))
    assert predicate(mock_event) is True  # pyright: ignore[reportArgumentType]

    # All false
    predicate = P.AnyOf((always_false, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]


def test_not_inverts_predicate() -> None:
    """Test that Not inverts the result of wrapped predicate."""

    mock_event = SimpleNamespace()

    assert P.Not(always_true)(mock_event) is False  # pyright: ignore[reportArgumentType]
    assert P.Not(always_false)(mock_event) is True  # pyright: ignore[reportArgumentType]


def test_guard_wraps_callable() -> None:
    """Test that Guard wraps arbitrary callables as predicates."""
    sentinel = object()

    def check_identity(event) -> bool:
        return event is sentinel

    guard = P.Guard(check_identity)
    assert guard(sentinel) is True
    assert guard(object()) is False


# ValueIs tests
def test_value_is_with_literal_condition() -> None:
    """Test ValueIs with literal value conditions."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    # Test old state value
    predicate = P.ValueIs(source=A.get_state_value_old, condition="off")
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    predicate = P.ValueIs(source=A.get_state_value_old, condition="on")
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]

    # Test new state value
    predicate = P.ValueIs(source=A.get_state_value_new, condition="on")
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]


def test_value_is_with_callable_condition() -> None:
    """Test ValueIs with callable conditions."""
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=25)

    def gt_twenty(value: int) -> bool:
        return value > 20

    predicate = P.ValueIs(source=A.get_state_value_new, condition=gt_twenty)
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    predicate = P.ValueIs(source=A.get_state_value_old, condition=gt_twenty)
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]


def test_value_is_with_not_provided() -> None:
    """Test ValueIs with NOT_PROVIDED (no constraint)."""
    event = _create_state_event(entity_id="any.entity", old_value="any", new_value="any")

    predicate = P.ValueIs(source=A.get_state_value_new, condition=NOT_PROVIDED)
    assert predicate(event) is True


# From/To predicates
def test_state_from_predicate() -> None:
    """Test StateFrom predicate for old state values."""
    event = _create_state_event(entity_id="light.living", old_value="off", new_value="on")

    assert P.StateFrom("off")(event) is True
    assert P.StateFrom("on")(event) is False


def test_state_to_predicate() -> None:
    """Test StateTo predicate for new state values."""
    event = _create_state_event(entity_id="light.living", old_value="off", new_value="on")

    assert P.StateTo("on")(event) is True
    assert P.StateTo("off")(event) is False


def test_attr_from_predicate() -> None:
    """Test AttrFrom predicate for old attribute values."""
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert P.AttrFrom("brightness", 100)(event) is True
    assert P.AttrFrom("brightness", 200)(event) is False


def test_attr_to_predicate() -> None:
    """Test AttrTo predicate for new attribute values."""
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert P.AttrTo("brightness", 200)(event) is True
    assert P.AttrTo("brightness", 100)(event) is False


# Change detection predicates
def test_state_did_change() -> None:
    """Test StateDidChange predicate detects state transitions."""
    # State changed
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=25)
    predicate = P.StateDidChange()
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
    predicate = P.AttrDidChange("brightness")
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
    predicate = P.EntityMatches("light.kitchen")
    assert predicate(event) is True

    # No match
    predicate = P.EntityMatches("light.living")
    assert predicate(event) is False

    # Glob match
    predicate = P.EntityMatches("light.*")
    assert predicate(event) is True

    predicate = P.EntityMatches("sensor.*")
    assert predicate(event) is False


def test_domain_matches() -> None:
    """Test DomainMatches predicate with literal and glob patterns."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    # Exact match
    predicate = P.DomainMatches("light")
    assert predicate(event) is True

    # No match
    predicate = P.DomainMatches("sensor")
    assert predicate(event) is False


def test_service_matches() -> None:
    """Test ServiceMatches predicate."""
    event = _create_service_event(domain="light", service="turn_on")

    # Exact match
    predicate = P.ServiceMatches("turn_on")
    assert predicate(event) is True

    # No match
    predicate = P.ServiceMatches("turn_off")
    assert predicate(event) is False

    # Glob match
    predicate = P.ServiceMatches("turn_*")
    assert predicate(event) is True


# ServiceDataWhere tests
def test_service_data_where_exact_match() -> None:
    """Test ServiceDataWhere with exact value matching."""
    event = _create_service_event(
        domain="light", service="turn_on", service_data={"entity_id": "light.kitchen", "brightness": 255}
    )

    predicate = P.ServiceDataWhere({"entity_id": "light.kitchen", "brightness": 255})
    assert predicate(event) is True

    predicate = P.ServiceDataWhere({"entity_id": "light.living"})
    assert predicate(event) is False


def test_service_data_where_with_callable() -> None:
    """Test ServiceDataWhere with callable conditions."""
    event = _create_service_event(domain="light", service="turn_on", service_data={"brightness": 255})

    def brightness_gt_200(value: int) -> bool:
        return value > 200

    predicate = P.ServiceDataWhere({"brightness": brightness_gt_200})
    assert predicate(event) is True


def test_service_data_where_with_not_provided() -> None:
    """Test ServiceDataWhere requiring key presence with NOT_PROVIDED."""
    event = _create_service_event(domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"})

    # Key exists
    predicate = P.ServiceDataWhere({"entity_id": NOT_PROVIDED})
    assert predicate(event) is True

    # Key missing
    predicate = P.ServiceDataWhere({"brightness": NOT_PROVIDED})
    assert predicate(event) is False


def test_service_data_where_with_globs() -> None:
    """Test ServiceDataWhere with automatic glob pattern handling."""
    event = _create_service_event(domain="light", service="turn_on", service_data={"entity_id": "light.kitchen"})

    predicate = P.ServiceDataWhere({"entity_id": "light.*"})
    assert predicate(event) is True

    predicate = P.ServiceDataWhere({"entity_id": "sensor.*"})
    assert predicate(event) is False


# Condition tests
def test_glob_condition() -> None:
    """Test Glob condition matcher."""
    glob = C.Glob("light.*")

    assert glob("light.kitchen") is True
    assert glob("light.living") is True
    assert glob("sensor.temp") is False
    assert glob(123) is False  # Non-string


def test_startswith_condition() -> None:
    """Test StartsWith condition matcher."""
    condition = C.StartsWith("light.")

    assert condition("light.kitchen") is True
    assert condition("light.living") is True
    assert condition("sensor.temp") is False
    assert condition(123) is False  # Non-string


def test_endswith_condition() -> None:
    """Test EndsWith condition matcher."""
    condition = C.EndsWith(".kitchen")

    assert condition("light.kitchen") is True
    assert condition("sensor.kitchen") is True
    assert condition("light.living") is False
    assert condition(123) is False  # Non-string


def test_contains_condition() -> None:
    """Test Contains condition matcher."""
    condition = C.Contains("kitchen")

    assert condition("light.kitchen") is True
    assert condition("sensor.kitchen_temp") is True
    assert condition("light.living") is False
    assert condition(123) is False  # Non-string


def test_regex_condition() -> None:
    """Test Regex condition matcher."""
    condition = C.Regex(r"light\..*kitchen")

    assert condition("light.main_kitchen") is True
    assert condition("light.back_kitchen") is True
    assert condition("light.living") is False
    assert condition("sensor.kitchen") is False
    assert condition(123) is False  # Non-string


def test_present_condition() -> None:
    """Test Present condition matcher."""
    condition = C.Present()

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


def test_compare_value_with_not_provided() -> None:
    """Test compare_value with NOT_PROVIDED sentinel."""
    assert compare_value("any_value", NOT_PROVIDED) is True


def test_compare_value_with_callable() -> None:
    """Test compare_value with callable conditions."""

    def gt_ten(value: int) -> bool:
        return value > 10

    assert compare_value(15, gt_ten) is True
    assert compare_value(5, gt_ten) is False


def test_compare_value_error_handling() -> None:
    """Test compare_value error handling for invalid conditions."""

    # Async callable should raise
    async def async_predicate(value):  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return True

    with pytest.raises(TypeError, match="Async predicates are not supported"):
        compare_value("value", async_predicate)

    # Non-bool return should raise
    def non_bool_predicate(value):  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return "not_bool"

    with pytest.raises(TypeError, match="Predicate must return bool"):
        compare_value("value", non_bool_predicate)


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
    assert isinstance(result, P.AllOf)
    assert len(result.predicates) == 2


# Accessor tests
def test_get_entity_id_accessor() -> None:
    """Test get_entity_id accessor function."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert A.get_entity_id(event) == "light.kitchen"


def test_get_domain_accessor() -> None:
    """Test get_domain accessor function."""
    event = _create_state_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert A.get_domain(event) == "light"


def test_get_state_value_accessors() -> None:
    """Test state value accessor functions."""
    event = _create_state_event(entity_id="sensor.temp", old_value=20, new_value=25)

    assert A.get_state_value_old(event) == 20
    assert A.get_state_value_new(event) == 25


def test_get_attr_accessors() -> None:
    """Test attribute accessor functions."""
    event = _create_state_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100, "color": "red"},
        new_attrs={"brightness": 200, "color": "blue"},
    )

    assert A.get_attr_old("brightness")(event) == 100
    assert A.get_attr_new("brightness")(event) == 200
    assert A.get_attr_old("color")(event) == "red"
    assert A.get_attr_new("color")(event) == "blue"

    # Missing attribute
    assert A.get_attr_old("missing")(event) == MISSING_VALUE
    assert A.get_attr_new("missing")(event) == MISSING_VALUE


def test_get_service_data_key_accessor() -> None:
    """Test get_service_data_key accessor function."""
    event = _create_service_event(
        domain="light", service="turn_on", service_data={"entity_id": "light.kitchen", "brightness": 255}
    )

    accessor = A.get_service_data_key("entity_id")
    assert accessor(event) == "light.kitchen"

    accessor = A.get_service_data_key("brightness")
    assert accessor(event) == 255

    # Missing key
    accessor = A.get_service_data_key("missing")
    assert accessor(event) == MISSING_VALUE


def test_get_path_accessor() -> None:
    """Test get_path accessor function with various path expressions."""
    # Create a complex nested object structure
    test_obj = SimpleNamespace(
        simple_attr="simple_value",
        nested=SimpleNamespace(
            level1=SimpleNamespace(
                level2="nested_value",
                number=42,
                flag=True,
            ),
            array=[1, 2, 3, {"key": "array_value"}],
            dict_attr={"dict_key": "dict_value", "nested_dict": {"deep": "deep_value"}},
        ),
        list_attr=["item1", "item2", {"list_item_key": "list_item_value"}],
        dict_with_spaces={"key with spaces": "spaced_value"},
        none_value=None,
    )

    # Test simple attribute access
    accessor = A.get_path("simple_attr")
    assert accessor(test_obj) == "simple_value"

    # Test nested attribute access
    accessor = A.get_path("nested.level1.level2")
    assert accessor(test_obj) == "nested_value"

    # Test nested numeric access
    accessor = A.get_path("nested.level1.number")
    assert accessor(test_obj) == 42

    # Test nested boolean access
    accessor = A.get_path("nested.level1.flag")
    assert accessor(test_obj) is True

    # Test array/list indexing
    accessor = A.get_path("nested.array.0")
    assert accessor(test_obj) == 1

    accessor = A.get_path("list_attr.2.list_item_key")
    assert accessor(test_obj) == "list_item_value"

    # Test dictionary key access
    accessor = A.get_path("nested.dict_attr.dict_key")
    assert accessor(test_obj) == "dict_value"

    # Test deeply nested dictionary access
    accessor = A.get_path("nested.dict_attr.nested_dict.deep")
    assert accessor(test_obj) == "deep_value"

    # Test accessing None values
    accessor = A.get_path("none_value")
    assert accessor(test_obj) is None

    # Test accessing non-existent paths - should return MISSING_VALUE
    accessor = A.get_path("nonexistent")
    assert accessor(test_obj) is MISSING_VALUE

    accessor = A.get_path("nested.nonexistent")
    assert accessor(test_obj) is MISSING_VALUE

    accessor = A.get_path("nested.level1.nonexistent")
    assert accessor(test_obj) is MISSING_VALUE

    # Test invalid array index
    accessor = A.get_path("list_attr.10")
    assert accessor(test_obj) is MISSING_VALUE

    # Test accessing attribute on None
    accessor = A.get_path("none_value.some_attr")
    assert accessor(test_obj) is MISSING_VALUE


def test_get_path_with_dict_objects() -> None:
    """Test get_path with dictionary objects instead of SimpleNamespace."""
    test_dict = {
        "top_level": "value",
        "nested": {
            "inner": {
                "deep": "deep_value",
                "list": [{"item": "list_item"}],
            },
            "simple": "simple_value",
        },
        "array": [1, 2, {"nested_in_array": "array_nested"}],
    }

    # Test dictionary key access
    accessor = A.get_path("top_level")
    assert accessor(test_dict) == "value"

    # Test nested dictionary access
    accessor = A.get_path("nested.inner.deep")
    assert accessor(test_dict) == "deep_value"

    accessor = A.get_path("nested.simple")
    assert accessor(test_dict) == "simple_value"

    # Test mixed dictionary and list access
    accessor = A.get_path("nested.inner.list.0.item")
    assert accessor(test_dict) == "list_item"

    accessor = A.get_path("array.2.nested_in_array")
    assert accessor(test_dict) == "array_nested"

    # Test missing keys
    accessor = A.get_path("missing_key")
    assert accessor(test_dict) is MISSING_VALUE

    accessor = A.get_path("nested.missing")
    assert accessor(test_dict) is MISSING_VALUE


def test_get_path_error_handling() -> None:
    """Test get_path error handling for various edge cases."""
    # Test with invalid object types
    accessor = A.get_path("some.path")

    # Should return MISSING_VALUE for non-dict/object types
    assert accessor("string") is MISSING_VALUE
    assert accessor(123) is MISSING_VALUE
    assert accessor([1, 2, 3]) is MISSING_VALUE  # List without proper path
    assert accessor(None) is MISSING_VALUE

    # Test with empty path strings
    accessor = A.get_path("")
    test_obj = {"key": "value"}
    # Empty path causes glom to raise an exception, so should return MISSING_VALUE
    assert accessor(test_obj) is MISSING_VALUE

    # Test with malformed paths that cause glom to fail
    test_obj = SimpleNamespace(attr="value")

    # These should all return MISSING_VALUE due to exceptions
    accessor = A.get_path("attr.nonexistent.deep")
    assert accessor(test_obj) is MISSING_VALUE

    # Test accessing methods/attributes that don't exist
    accessor = A.get_path("nonexistent_method()")
    assert accessor(test_obj) is MISSING_VALUE


def test_get_path_with_real_event_structure() -> None:
    """Test get_path with realistic event-like structures."""
    # Simulate a Home Assistant event structure
    event = SimpleNamespace(
        topic="hass.event.state_changed",
        payload=SimpleNamespace(
            data=SimpleNamespace(
                entity_id="light.kitchen",
                domain="light",
                old_state_value="off",
                new_state_value="on",
                service_data={"brightness": 255, "transition": 2},
            )
        ),
    )

    # Test paths similar to what's used in the codebase
    accessor = A.get_path("payload.data.entity_id")
    assert accessor(event) == "light.kitchen"

    accessor = A.get_path("payload.data.domain")
    assert accessor(event) == "light"

    accessor = A.get_path("payload.data.service_data.brightness")
    assert accessor(event) == 255

    accessor = A.get_path("topic")
    assert accessor(event) == "hass.event.state_changed"

    # Test missing paths on realistic structure
    accessor = A.get_path("payload.data.nonexistent")
    assert accessor(event) is MISSING_VALUE

    accessor = A.get_path("payload.metadata.missing")
    assert accessor(event) is MISSING_VALUE
