"""Tests for literal-comparison coercion in predicates and conditions.

Bool and numeric literals coerce a raw Home Assistant string before comparing; ``C.Exact`` opts out.
"""

import pytest

from hassette import C, P
from hassette.event_handling.conditions import coerce_to_literal_type
from hassette.exceptions import UnableToConvertValueError
from hassette.testing import create_state_change_event
from tests.support.helpers import create_attr_change_event


@pytest.mark.parametrize(
    ("raw", "literal", "expected"),
    [
        pytest.param("on", True, True, id="on_true"),
        pytest.param("OFF", True, False, id="off_upper_true"),
        pytest.param("yes", True, True, id="yes_true"),
        pytest.param("0", False, False, id="zero_false"),
        pytest.param("21.5", 20, 21.5, id="numeric_int_literal"),
        pytest.param("20.0", 20, 20.0, id="decimal_string_int_literal"),
        pytest.param("20", 20.0, 20.0, id="numeric_float_literal"),
        pytest.param("on", "on", "on", id="str_literal_untouched"),
        pytest.param(5, True, 5, id="non_string_untouched"),
    ],
)
def test_coerce_to_literal_type(raw: object, literal: object, expected: object) -> None:
    assert coerce_to_literal_type(raw, literal) == expected


@pytest.mark.parametrize(("raw", "literal"), [("unavailable", True), ("unknown", 20)])
def test_coerce_to_literal_type_raises_on_unconvertible(raw: str, literal: object) -> None:
    with pytest.raises(UnableToConvertValueError):
        coerce_to_literal_type(raw, literal)


@pytest.mark.parametrize(
    ("old", "new", "literal", "to_expected", "from_expected"),
    [
        pytest.param("off", "on", True, True, False, id="bool_true"),
        pytest.param("off", "on", False, False, True, id="bool_false"),
        pytest.param("false", "true", True, True, False, id="bool_true_false_strings"),
        pytest.param("0", "1", True, True, False, id="bool_one_zero"),
        pytest.param("19.5", "20.0", 20, True, False, id="int_literal"),
        pytest.param("19.5", "20.0", 19.5, False, True, id="float_literal"),
        pytest.param("on", "unavailable", True, False, True, id="unconvertible_no_match"),
        pytest.param("off", "on", "on", True, False, id="string_literal_unchanged"),
    ],
)
def test_state_from_to_coerce_literals(
    old: str, new: str, literal: object, to_expected: bool, from_expected: bool
) -> None:
    event = create_state_change_event(entity_id="switch.fan", old_value=old, new_value=new)

    assert P.StateTo(literal)(event) is to_expected
    assert P.StateFrom(literal)(event) is from_expected


def test_attr_from_to_coerce_literals() -> None:
    event = create_attr_change_event("off", "on")

    assert P.AttrTo("brightness", True)(event) is True
    assert P.AttrFrom("brightness", False)(event) is True
    assert P.AttrTo("brightness", False)(event) is False


def test_exact_skips_coercion() -> None:
    event = create_state_change_event(entity_id="switch.fan", old_value="0", new_value="on")

    assert P.StateTo(C.Exact(True))(event) is False
    assert P.StateTo(C.Exact("on"))(event) is True
    assert P.StateFrom(C.Exact(0))(event) is False
    assert P.StateFrom(C.Exact("0"))(event) is True


def test_exact_summarize() -> None:
    assert P.StateTo(C.Exact("on")).summarize() == "→ exactly 'on'"


@pytest.mark.parametrize(
    ("raw", "literal"),
    [("on", True), ("off", False), ("1", True), ("20.0", 20), ("on", "on"), ("unavailable", True)],
)
def test_literal_and_comparison_eq_agree(raw: str, literal: object) -> None:
    """A bare literal and C.Comparison("==", literal) share one coercion path."""
    event = create_state_change_event(entity_id="switch.fan", old_value="x", new_value=raw)

    assert P.StateTo(literal)(event) is P.StateTo(C.Comparison("==", literal))(event)


@pytest.mark.parametrize("raw", ["unavailable", "unknown"])
def test_comparison_ne_unconvertible_returns_false(raw: str) -> None:
    assert C.Comparison("!=", True)(raw) is False


@pytest.mark.parametrize(
    ("raw", "literal", "expected"),
    [
        pytest.param("9007199254740993", 9007199254740993, True, id="exact_large_int"),
        pytest.param("9007199254740993", 9007199254740992, False, id="adjacent_large_int"),
    ],
)
def test_int_literal_preserves_precision(raw: str, literal: int, expected: bool) -> None:
    """Integer strings beyond float precision compare exactly against int literals."""
    event = create_state_change_event(entity_id="sensor.counter", old_value="0", new_value=raw)

    assert P.StateTo(literal)(event) is expected
    assert C.Comparison("==", literal)(raw) is expected
