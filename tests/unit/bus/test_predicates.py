"""Tests for the state and attribute predicates in hassette.event_handling.predicates.

Covers ValueIs, the State/Attr From/To predicates, change detection (StateDidChange, AttrDidChange),
StateComparison evaluation, and EventEntityFresh.
"""

from unittest.mock import patch

import pytest
from whenever import ZonedDateTime

from hassette import A, P, RawStateChangeEvent
from hassette.const import NOT_PROVIDED
from hassette.event_handling.conditions import CrossedAbove
from hassette.event_handling.predicates import (
    EventEntityFresh,
    ServiceDataWhere,
    StateComparison,
)
from hassette.testing import (
    create_state_change_event,
    make_full_state_change_event,
    make_state_dict,
)
from tests.support.helpers import create_attr_change_event

LAST_CHANGED = "2026-10-09T12:00:00.000+00:00"


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
    event = create_attr_change_event(100, 200)

    assert P.AttrFrom("brightness", 100)(event) is True
    assert P.AttrFrom("brightness", 200)(event) is False


def test_attr_to_predicate() -> None:
    """Test AttrTo predicate for new attribute values."""
    event = create_attr_change_event(100, 200)

    assert P.AttrTo("brightness", 200)(event) is True
    assert P.AttrTo("brightness", 100)(event) is False


def test_attr_from_to_predicates_apply_conditions() -> None:
    """Test that AttrFrom and AttrTo predicates correctly match old and new attribute values."""
    event = create_attr_change_event(100, 150)

    attr_from = P.AttrFrom("brightness", 100)
    attr_to = P.AttrTo("brightness", 150)

    assert attr_from(event) is True
    assert attr_to(event) is True


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
    event = create_attr_change_event(100, 150)
    assert predicate(event) is True


def test_attr_did_change_false_when_unchanged() -> None:
    """Test that AttrDidChange returns False when specified attribute is unchanged."""
    predicate = P.AttrDidChange("brightness")
    event = create_attr_change_event(100, 100)
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


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        pytest.param("24.5", "25.5", True, id="crossing"),
        pytest.param("25.5", "25.7", False, id="still_above"),
        pytest.param("unavailable", "26", False, id="unavailable_to_numeric"),
    ],
)
def test_state_comparison_crossed_above(old: str, new: str, expected: bool) -> None:
    """StateComparison feeds the old and new state values to CrossedAbove."""
    event = create_state_change_event(entity_id="sensor.temp", old_value=old, new_value=new)

    assert StateComparison(condition=CrossedAbove(25))(event) is expected


def event_entity_change(state_value: str | None, last_changed: str = LAST_CHANGED) -> RawStateChangeEvent:
    new_state = (
        make_state_dict("event.hallway_button", state_value, last_changed=last_changed)
        if state_value is not None
        else None
    )
    return make_full_state_change_event("event.hallway_button", old_state=None, new_state=new_state)


@pytest.mark.parametrize(
    ("state_value", "last_changed", "expected"),
    [
        pytest.param("2026-10-09T11:59:59.998+00:00", LAST_CHANGED, True, id="real_press"),
        pytest.param("2026-10-09T11:59:50.000+00:00", LAST_CHANGED, True, id="exactly_max_age"),
        pytest.param("2026-10-09T11:59:49.999+00:00", LAST_CHANGED, False, id="just_over_max_age"),
        pytest.param("2026-10-09T08:00:00.000+00:00", LAST_CHANGED, False, id="restart_replay"),
        pytest.param("2026-10-09T07:59:58.000-04:00", LAST_CHANGED, True, id="other_offset_recent"),
        pytest.param("2026-10-09T12:00:00.500+00:00", LAST_CHANGED, True, id="timestamp_after_last_changed"),
        pytest.param("unknown", LAST_CHANGED, True, id="unknown"),
        pytest.param("unavailable", LAST_CHANGED, True, id="unavailable"),
        pytest.param("2026-10-09T08:00:00.000+00:00", "garbage", True, id="unparseable_last_changed"),
        pytest.param(None, LAST_CHANGED, True, id="missing_new_state"),
    ],
)
def test_event_entity_fresh(state_value: str | None, last_changed: str, expected: bool) -> None:
    assert P.EventEntityFresh(max_age=10)(event_entity_change(state_value, last_changed)) is expected


def input_button_change(state_value: str | None) -> RawStateChangeEvent:
    """Build an ``input_button`` state change; ``None`` builds an entity removal, which has no new state."""
    new_state = (
        None
        if state_value is None
        else make_state_dict("input_button.naptime", state_value, last_changed="2026-10-29T22:04:28+00:00")
    )
    return make_full_state_change_event("input_button.naptime", old_state=None, new_state=new_state)


@pytest.mark.parametrize(
    ("state_value", "expected"),
    [
        pytest.param("2026-10-29T22:04:27.998+00:00", True, id="real_press"),
        pytest.param("2026-10-18T21:51:13+00:00", False, id="restart_replay"),
        pytest.param("unavailable", True, id="unavailable_fails_open"),
    ],
)
def test_event_entity_fresh_covers_input_button(state_value: str, expected: bool) -> None:
    event = input_button_change(state_value)
    assert P.EventEntityFresh(max_age=10)(event) is expected


@pytest.mark.parametrize(
    ("state_value", "expected"),
    [
        pytest.param("2026-10-29T22:04:27.998+00:00", True, id="real_press"),
        pytest.param("2026-10-18T21:51:13+00:00", False, id="restart_replay"),
        pytest.param("unavailable", False, id="unavailable"),
        pytest.param("unknown", False, id="unknown"),
        pytest.param(None, False, id="entity_removed"),
    ],
)
def test_event_entity_fresh_composed_form_passes_only_real_press(state_value: str | None, expected: bool) -> None:
    predicate = (
        P.EventEntityFresh(max_age=10)
        & P.IsPresent(A.get_state_value_new)
        & ~P.StateTo("unavailable")
        & ~P.StateTo("unknown")
    )
    event = input_button_change(state_value)
    assert predicate(event) is expected


def test_event_entity_fresh_ignores_wall_clock() -> None:
    """A press long ago still passes when its last_changed matches, so duration= hold rechecks keep firing."""
    event = event_entity_change("2026-10-09T11:59:59.998+00:00")
    with patch("hassette.utils.date_utils.now", return_value=ZonedDateTime(2026, 10, 10, 12, tz="UTC")):
        assert P.EventEntityFresh(max_age=10)(event) is True


@pytest.mark.parametrize("max_age", [0, -1, float("nan")])
def test_event_entity_fresh_rejects_non_positive_max_age(max_age: float) -> None:
    with pytest.raises(ValueError, match="max_age must be positive"):
        P.EventEntityFresh(max_age=max_age)


def test_predicate_summarize_golden_event_entity_fresh() -> None:
    assert EventEntityFresh(max_age=10).summarize() == "event within 10s"
    assert EventEntityFresh(max_age=2.5).summarize() == "event within 2.5s"


def test_service_data_where_equal_for_same_spec() -> None:
    """Two ServiceDataWhere built from the same spec compare equal; a different spec does not."""
    assert ServiceDataWhere({"entity_id": "light.kitchen"}) == ServiceDataWhere({"entity_id": "light.kitchen"})
    assert ServiceDataWhere({"entity_id": "light.kitchen"}) != ServiceDataWhere({"entity_id": "light.office"})
