"""Tests for predicate architecture in hassette.event_handling.predicates.

This module tests the core predicate system including:
- ValueIs predicate with various conditions
- State/Attr From/To predicates
- Change detection predicates (StateDidChange, AttrDidChange)
- Entity/Domain/Service matching predicates
- Accessor functions for extracting event data
- summarize() golden tests for all predicate types
"""

from types import SimpleNamespace

from hassette import A, P
from hassette.const import MISSING_VALUE, NOT_PROVIDED
from hassette.event_handling.predicates import (
    AllOf,
    AnyOf,
    AttrComparison,
    AttrDidChange,
    AttrFrom,
    AttrTo,
    DidChange,
    DomainMatches,
    EntityMatches,
    Guard,
    IsMissing,
    IsPresent,
    Not,
    ServiceDataWhere,
    ServiceMatches,
    StateComparison,
    StateDidChange,
    StateFrom,
    StateTo,
    ValueIs,
)
from hassette.test_utils import create_call_service_event, create_state_change_event


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
    # State values are stored as strings; conditions that need numeric comparison
    # should use string comparison or convert within the condition
    event = create_state_change_event(entity_id="sensor.temp", old_value="20", new_value="25")

    def gt_twenty(value: str) -> bool:
        return float(value) > 20

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
        old_value="on",
        new_value="on",
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
        old_value="on",
        new_value="on",
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


def test_attr_did_change_returns_true_when_old_state_none() -> None:
    """AttrDidChange treats old_state=None as a match for bootstrap/immediate-fire events.

    When immediate=True fires at registration time, the synthetic event has old_state=None.
    AttrDidChange must return True in this case so that attribute-change listeners
    participate in immediate-fire correctly.
    """
    predicate = P.AttrDidChange("brightness")
    # Simulate a synthetic immediate-fire event with old_state=None
    event = create_state_change_event(
        entity_id="light.office",
        old_value=None,  # None → old_state is None in the event
        new_value="on",
        new_attrs={"brightness": 200},
    )
    assert predicate(event) is True


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
    # State values are stored as strings (HA always serializes state as str)
    event = create_state_change_event(entity_id="sensor.temp", old_value="20", new_value="25")

    assert A.get_state_value_old(event) == "20"
    assert A.get_state_value_new(event) == "25"


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


# ---------------------------------------------------------------------------
# ValueIs.summarize() tests (RED → GREEN phase)
# ---------------------------------------------------------------------------


def test_value_is_summarize_literal_condition() -> None:
    """ValueIs.summarize() returns literal condition value and source name for non-callable conditions."""
    from hassette.event_handling.accessors import get_state_value_new

    pred = ValueIs(source=get_state_value_new, condition="on")
    result = pred.summarize()
    assert "on" in result
    assert "get_state_value_new" in result


def test_value_is_summarize_callable_condition() -> None:
    """ValueIs.summarize() returns 'custom condition from <source>' for callable conditions."""
    from hassette.event_handling.accessors import get_state_value_new

    pred = ValueIs(source=get_state_value_new, condition=lambda v: v > 50)
    result = pred.summarize()
    assert result.startswith("custom condition from")
    assert "get_state_value_new" in result


def test_value_is_summarize_distinguishes_sources() -> None:
    """ValueIs with same condition but different sources produces distinct summarize() strings."""
    from hassette.event_handling.accessors import get_state_value_new, get_state_value_old

    pred_new = ValueIs(source=get_state_value_new, condition="on")
    pred_old = ValueIs(source=get_state_value_old, condition="on")
    assert pred_new.summarize() != pred_old.summarize()


# ---------------------------------------------------------------------------
# Golden/snapshot tests — exact summarize() output for all predicate types
# ---------------------------------------------------------------------------
# These are stability contract tests. When summarize() output changes, these
# tests fail loudly, signalling a migration may be needed to avoid orphaning
# historical rows that rely on human_description for natural key matching.


def test_predicate_summarize_golden_entity_matches() -> None:
    assert EntityMatches("light.kitchen").summarize() == "entity light.kitchen"


def test_predicate_summarize_golden_domain_matches() -> None:
    assert DomainMatches("light").summarize() == "domain light"


def test_predicate_summarize_golden_service_matches() -> None:
    assert ServiceMatches("turn_on").summarize() == "service turn_on"


def test_predicate_summarize_golden_state_did_change() -> None:
    assert StateDidChange().summarize() == "state changed"


def test_predicate_summarize_golden_attr_did_change() -> None:
    assert AttrDidChange(attr_name="brightness").summarize() == "attr brightness changed"


def test_predicate_summarize_golden_state_to() -> None:
    assert StateTo("on").summarize() == "\u2192 on"


def test_predicate_summarize_golden_state_from() -> None:
    assert StateFrom("off").summarize() == "from off"


def test_predicate_summarize_golden_attr_to() -> None:
    assert AttrTo(attr_name="brightness", condition=255).summarize() == "attr brightness \u2192 255"


def test_predicate_summarize_golden_attr_from() -> None:
    assert AttrFrom(attr_name="brightness", condition=100).summarize() == "attr brightness from 100"


def test_predicate_summarize_golden_state_comparison() -> None:
    from hassette.event_handling.conditions import Increased

    assert StateComparison(condition=Increased()).summarize() == "state Increased()"


def test_predicate_summarize_golden_attr_comparison() -> None:
    from hassette.event_handling.conditions import Increased

    assert AttrComparison(attr_name="brightness", condition=Increased()).summarize() == "attr brightness Increased()"


def test_predicate_summarize_golden_value_is_literal() -> None:
    """ValueIs with literal condition — exact format: 'value is <condition> from <source>'."""
    from hassette.event_handling.accessors import get_state_value_new

    assert ValueIs(source=get_state_value_new, condition="on").summarize() == "value is on from get_state_value_new"


def test_predicate_summarize_golden_value_is_callable() -> None:
    """ValueIs with callable condition — exact format: 'custom condition from <source>'."""
    from hassette.event_handling.accessors import get_state_value_new

    pred = ValueIs(source=get_state_value_new, condition=lambda v: v > 50)
    assert pred.summarize() == "custom condition from get_state_value_new"


def test_predicate_summarize_golden_guard() -> None:
    assert Guard(lambda _e: True).summarize() == "custom condition"


def test_predicate_summarize_golden_all_of() -> None:
    pred = AllOf(predicates=(EntityMatches("light.kitchen"), StateTo("on")))
    assert pred.summarize() == "entity light.kitchen and \u2192 on"


def test_predicate_summarize_golden_any_of() -> None:
    pred = AnyOf(predicates=(StateTo("on"), StateTo("off")))
    assert pred.summarize() == "\u2192 on or \u2192 off"


def test_predicate_summarize_golden_not() -> None:
    assert Not(predicate=StateTo("on")).summarize() == "not \u2192 on"


def test_predicate_summarize_golden_is_present() -> None:
    from hassette.event_handling.accessors import get_state_value_new

    assert IsPresent(source=get_state_value_new).summarize() == "is present"


def test_predicate_summarize_golden_is_missing() -> None:
    from hassette.event_handling.accessors import get_state_value_new

    assert IsMissing(source=get_state_value_new).summarize() == "is missing"


def test_predicate_summarize_golden_did_change() -> None:
    from hassette.event_handling.accessors import get_state_value_old_new

    assert DidChange(source=get_state_value_old_new).summarize() == "changed"


def test_predicate_summarize_golden_service_data_where() -> None:
    pred = ServiceDataWhere(spec={"entity_id": "light.kitchen"})
    assert pred.summarize() == "service data where entity_id = light.kitchen"


def test_predicate_summarize_golden_service_data_where_callable_condition() -> None:
    """ServiceDataWhere with callable condition uses callable_name() — not memory address."""
    pred = ServiceDataWhere(spec={"brightness": lambda v: v > 100, "entity_id": "light.kitchen"})
    result = pred.summarize()
    # Must not contain a memory address
    assert "0x" not in result
    # Callable condition shows as <callable>
    assert "brightness = <callable>" in result
    # Literal condition shows as-is
    assert "entity_id = light.kitchen" in result
