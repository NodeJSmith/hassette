from typing import Any, TypeVarTuple

import pytest
from typing_extensions import TypeAliasType, TypeVar

from hassette import STATE_REGISTRY
from hassette.events import HassStateDict
from hassette.utils.type_utils import get_pretty_actual_type_from_value, unwrap_type_alias

T = TypeVar("T")
U = TypeVar("U")
UDefault = TypeVar("UDefault", default=int)
Ts = TypeVarTuple("Ts")

# PEP 695 equivalents in the comments; `TypeAliasType` builds them on 3.11 too.
Identity = TypeAliasType("Identity", T, type_params=(T,))  # type Identity[T] = T
NestedIdentity = TypeAliasType("NestedIdentity", Identity[Identity[T]], type_params=(T,))
Pair = TypeAliasType("Pair", dict[T, U], type_params=(T, U))  # type Pair[T, U] = dict[T, U]
PairWithDefault = TypeAliasType(
    "PairWithDefault", dict[T, UDefault], type_params=(T, UDefault)
)  # type PairWithDefault[T, U = int] = dict[T, U]
Packed = TypeAliasType("Packed", tuple[*Ts], type_params=(Ts,))  # type Packed[*Ts] = tuple[*Ts]


class CyclicAlias:
    """Stands in for `type X = Y; type Y = X`, which only PEP 695 syntax (3.12+) can build."""

    __type_params__ = ()

    def __init__(self) -> None:
        self.__value__: Any = None


class GrowingAlias:
    """Stands in for `type G[T] = G[list[T]]`: every expansion yields a new, never-repeating alias."""

    __type_params__ = ()

    @property
    def __value__(self) -> "GrowingAlias":
        return GrowingAlias()


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


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        (Identity[Identity[int]], int),
        (NestedIdentity[str], str),
        (PairWithDefault[str], dict[str, int]),
        (Packed[()], tuple[()]),
    ],
    ids=["repeated_alias_in_args", "repeated_alias_in_value", "defaulted_param", "empty_variadic_pack"],
)
def test_unwrap_type_alias_resolves(alias: Any, expected: Any):
    assert unwrap_type_alias(alias) == expected


def test_unwrap_type_alias_returns_unsubstituted_value_for_too_few_args():
    """`Pair[int]` is creatable at runtime but leaves `U` unbound; resolve to the raw value rather than raise."""
    assert unwrap_type_alias(Pair[int]) is Pair.__value__


def test_unwrap_type_alias_stops_on_cyclic_aliases():
    x, y = CyclicAlias(), CyclicAlias()
    x.__value__, y.__value__ = y, x

    assert unwrap_type_alias(x) in (x, y)


def test_unwrap_type_alias_stops_on_ever_growing_aliases():
    assert isinstance(unwrap_type_alias(GrowingAlias()), GrowingAlias)
