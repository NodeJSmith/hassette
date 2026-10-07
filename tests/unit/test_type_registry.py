from enum import StrEnum

import pytest

from hassette import TYPE_REGISTRY
from hassette.exceptions import UnableToConvertValueError


def test_type_already_in_desired_state_not_converted_again() -> None:
    """Test that a state already in the desired type is not converted again."""
    desired_value = 12.1
    desired_type = float

    output = TYPE_REGISTRY.convert(desired_value, desired_type)
    assert output == desired_value
    assert type(output) is desired_type


def test_type_conversion_idempotent() -> None:
    """Test that a state already in the desired type is not converted again."""
    original_value = "12.1"
    desired_value = 12.1
    desired_type = float

    output = TYPE_REGISTRY.convert(original_value, desired_type)
    assert output == desired_value
    assert type(output) is desired_type

    output_two = TYPE_REGISTRY.convert(output, desired_type)
    assert output_two == output
    assert type(output_two) is desired_type


class TestConstructorFallbackCache:
    """Verify constructor fallback behavior (memoization removed; conversion result unchanged)."""

    def test_constructor_fallback_succeeds(self) -> None:
        """Constructor fallback converts successfully for an unregistered type pair."""

        class Custom:
            def __init__(self, val: str) -> None:
                self.val = val

        result = TYPE_REGISTRY.convert("hello", Custom)

        assert isinstance(result, Custom)
        assert result.val == "hello"

    def test_constructor_fallback_succeeds_on_repeated_calls(self) -> None:
        """Constructor fallback works correctly on every call — no memoization required."""

        class Custom:
            def __init__(self, val: int) -> None:
                self.val = val

        result_one = TYPE_REGISTRY.convert(42, Custom)
        result_two = TYPE_REGISTRY.convert(99, Custom)

        assert isinstance(result_one, Custom)
        assert result_one.val == 42
        assert isinstance(result_two, Custom)
        assert result_two.val == 99

    def test_constructor_fallback_raises_for_unconvertible_types(self) -> None:
        """Constructor fallback raises UnableToConvertValueError when constructor fails."""

        class Strict:
            def __init__(self, val: str) -> None:
                raise TypeError("nope")

        with pytest.raises(UnableToConvertValueError):
            TYPE_REGISTRY.convert("hello", Strict)


@pytest.mark.parametrize(
    ("value", "to_type", "expected", "expected_type"),
    [
        ("42", (int, float, str), 42, int),
        ("4.5", (int, float, str), 4.5, float),
        ("abc", (int, float, str), "abc", str),
        ("42", (str, int, float), "42", str),
        ("abc", (str, type(None)), "abc", str),
        (None, (str, type(None)), None, type(None)),
        (4.5, (int, float), 4.5, float),
        (3, (float, int), 3, int),
    ],
)
def test_tuple_conversion_tries_types_in_order_for_strings(
    value: object, to_type: tuple[type, ...], expected: object, expected_type: type
) -> None:
    """Strings walk the tuple in declared order; already-typed non-strings short-circuit."""
    result = TYPE_REGISTRY.convert(value, to_type)
    assert result == expected
    assert type(result) is expected_type


def test_tuple_conversion_raises_when_no_type_matches() -> None:
    """A string that no tuple member can convert raises instead of passing through."""
    with pytest.raises(UnableToConvertValueError):
        TYPE_REGISTRY.convert("abc", (int, float))


class Mode(StrEnum):
    CLEANING = "cleaning"


def test_tuple_conversion_keeps_already_typed_str_subclass() -> None:
    """A str subclass that already matches a tuple member is not re-converted to a plain str."""
    result = TYPE_REGISTRY.convert(Mode.CLEANING, (str, Mode))
    assert type(result) is Mode
