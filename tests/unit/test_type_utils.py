from typing import Any

import pytest

from hassette import STATE_REGISTRY
from hassette.events import HassStateDict
from hassette.utils.type_utils import get_pretty_actual_type_from_value


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [
        (42, "int"),
        ("hello", "str"),
        (3.14, "float"),
        ([1, 2, 3], "list[int]"),
        ({"a", "b", "c"}, "set[str]"),
        (frozenset({1.0, 2.0}), "frozenset[float]"),
        ({"key": 1, "value": 2}, "dict[str, int]"),
        ({1: "one", 2: "two"}, "dict[int, str]"),
        ([], "list[Any]"),
        (set(), "set[Any]"),
        (frozenset(), "frozenset[Any]"),
        ({}, "dict[Any, Any]"),
    ],
)
def test_get_pretty_actual_type_simple_values(value: Any, expected_type: Any):
    actual = get_pretty_actual_type_from_value(value)
    assert actual == expected_type, f"Expected {expected_type}, got {actual}"


def test_get_pretty_actual_type_from_state_instance(hass_state_dicts: list[HassStateDict]):
    for state_dict in hass_state_dicts:
        inst = STATE_REGISTRY.try_convert_state(state_dict)

        str_repr = get_pretty_actual_type_from_value(inst)

        assert "typing." not in str_repr, "Expected 'typing.' to be stripped from string representation"


def test_get_pretty_actual_type_from_dumped_state(hass_state_dicts: list[HassStateDict]):
    for state_dict in hass_state_dicts:
        inst = STATE_REGISTRY.try_convert_state(state_dict)

        str_repr = get_pretty_actual_type_from_value(inst.model_dump())

        assert "typing." not in str_repr, (
            f"Expected 'typing.' to be stripped from string representation, got {str_repr}"
        )
