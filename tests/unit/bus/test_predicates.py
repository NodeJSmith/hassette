"""Tests for predicate architecture in hassette.event_handling.predicates.

This module tests the core predicate system including:
- ValueIs predicate with various conditions
- State/Attr From/To predicates
- Change detection predicates (StateDidChange, AttrDidChange)
- Entity/Domain/Service matching predicates
- Accessor functions for extracting event data
"""

from types import SimpleNamespace

from hassette import accessors as A
from hassette import predicates as P
from hassette.const import MISSING_VALUE, NOT_PROVIDED
from hassette.test_utils.helpers import create_call_service_event, create_state_change_event


# ValueIs tests
def test_value_is_with_literal_condition() -> None:
    """Test ValueIs with literal value conditions."""
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

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
    event = create_state_change_event(entity_id="sensor.temp", old_value=20, new_value=25)

    def gt_twenty(value: int) -> bool:
        return value > 20

    predicate = P.ValueIs(source=A.get_state_value_new, condition=gt_twenty)
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    predicate = P.ValueIs(source=A.get_state_value_old, condition=gt_twenty)
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]


def test_value_is_with_not_provided() -> None:
    """Test ValueIs with NOT_PROVIDED (no constraint)."""
    event = create_state_change_event(entity_id="any.entity", old_value="any", new_value="any")

    predicate = P.ValueIs(source=A.get_state_value_new, condition=NOT_PROVIDED)
    assert predicate(event) is True


# From/To predicates
def test_state_from_predicate() -> None:
    """Test StateFrom predicate for old state values."""
    event = create_state_change_event(entity_id="light.living", old_value="off", new_value="on")

    assert P.StateFrom("off")(event) is True
    assert P.StateFrom("on")(event) is False


def test_state_to_predicate() -> None:
    """Test StateTo predicate for new state values."""
    event = create_state_change_event(entity_id="light.living", old_value="off", new_value="on")

    assert P.StateTo("on")(event) is True
    assert P.StateTo("off")(event) is False


def test_attr_from_predicate() -> None:
    """Test AttrFrom predicate for old attribute values."""
    event = create_state_change_event(
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
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 200},
    )

    assert P.AttrTo("brightness", 200)(event) is True
    assert P.AttrTo("brightness", 100)(event) is False


def test_attr_from_to_predicates_apply_conditions() -> None:
    """Test that AttrFrom and AttrTo predicates correctly match old and new attribute values."""
    event = create_state_change_event(
        entity_id="light.office",
        old_value=None,
        new_value=None,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 150},
    )

    attr_from = P.AttrFrom("brightness", 100)
    attr_to = P.AttrTo("brightness", 150)

    assert attr_from(event) is True
    assert attr_to(event) is True


def test_from_to_predicates_match_state_values() -> None:
    """Test that StateFrom and StateTo predicates correctly match old and new state values."""
    event = create_state_change_event(entity_id="light.office", old_value="off", new_value="on")

    from_pred = P.StateFrom("off")
    to_pred = P.StateTo("on")

    assert from_pred(event) is True
    assert to_pred(event) is True


# Change detection predicates
def test_state_did_change_detects_transitions() -> None:
    """Test that StateDidChange predicate detects when state values change."""
    predicate = P.StateDidChange()
    event = create_state_change_event(entity_id="sensor.kitchen", old_value="off", new_value="on")
    assert predicate(event) is True


def test_state_did_change_false_when_unchanged() -> None:
    """Test that StateDidChange predicate returns False when state values are unchanged."""
    predicate = P.StateDidChange()
    event = create_state_change_event(entity_id="sensor.kitchen", old_value="idle", new_value="idle")
    assert predicate(event) is False


def test_attr_did_change_detects_attribute_modifications() -> None:
    """Test that AttrDidChange predicate detects when specified attributes change."""
    predicate = P.AttrDidChange("brightness")
    event = create_state_change_event(
        entity_id="light.office",
        old_value=None,
        new_value=None,
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 150},
    )
    assert predicate(event) is True


def test_attr_did_change_false_when_unchanged() -> None:
    """Test that AttrDidChange returns False when specified attribute is unchanged."""
    predicate = P.AttrDidChange("brightness")
    event = create_state_change_event(
        entity_id="light.office",
        old_value="on",
        new_value="on",
        old_attrs={"brightness": 100},
        new_attrs={"brightness": 100},
    )
    assert predicate(event) is False


# Entity/Domain/Service matching predicates
def test_entity_matches_supports_globs() -> None:
    """Test that EntityMatches predicate supports glob pattern matching."""
    predicate = P.EntityMatches("sensor.*")
    event = create_state_change_event(entity_id="sensor.kitchen", old_value=None, new_value=None)
    assert predicate(event) is True


def test_entity_matches_exact_match() -> None:
    """Test that EntityMatches predicate supports exact entity ID matching."""
    predicate = P.EntityMatches("sensor.kitchen")

    # Exact match
    event = create_state_change_event(entity_id="sensor.kitchen", old_value=None, new_value=None)
    assert predicate(event) is True

    # No match
    event = create_state_change_event(entity_id="sensor.living", old_value=None, new_value=None)
    assert predicate(event) is False


def test_entity_matches_glob_patterns() -> None:
    """Test EntityMatches with various glob patterns."""
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

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
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

    # Exact match
    predicate = P.DomainMatches("light")
    assert predicate(event) is True

    # No match
    predicate = P.DomainMatches("sensor")
    assert predicate(event) is False


def test_service_matches() -> None:
    """Test ServiceMatches predicate."""
    event = create_call_service_event(domain="light", service="turn_on")

    # Exact match
    predicate = P.ServiceMatches("turn_on")
    assert predicate(event) is True

    # No match
    predicate = P.ServiceMatches("turn_off")
    assert predicate(event) is False

    # Glob match
    predicate = P.ServiceMatches("turn_*")
    assert predicate(event) is True


# Accessor tests
def test_get_entity_id_accessor() -> None:
    """Test get_entity_id accessor function."""
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert A.get_entity_id(event) == "light.kitchen"


def test_get_domain_accessor() -> None:
    """Test get_domain accessor function."""
    event = create_state_change_event(entity_id="light.kitchen", old_value="off", new_value="on")

    assert A.get_domain(event) == "light"


def test_get_state_value_accessors() -> None:
    """Test state value accessor functions."""
    event = create_state_change_event(entity_id="sensor.temp", old_value=20, new_value=25)

    assert A.get_state_value_old(event) == 20
    assert A.get_state_value_new(event) == 25


def test_get_attr_accessors() -> None:
    """Test attribute accessor functions."""
    event = create_state_change_event(
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
    event = create_call_service_event(
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
