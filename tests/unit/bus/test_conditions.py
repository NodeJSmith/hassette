"""Tests for predicate condition functions.

Tests condition matchers like Contains, EndsWith, StartsWith, Present, Missing,
Glob, Regex, etc. that are used within predicates to test extracted values.
"""

import pytest

from hassette.const import MISSING_VALUE
from hassette.event_handling.conditions import (
    Comparison,
    Contains,
    Decreased,
    EndsWith,
    Glob,
    Increased,
    Intersects,
    IsIn,
    IsNone,
    IsNotNone,
    IsOrContains,
    Missing,
    NotIn,
    NotIntersects,
    Present,
    Regex,
    StartsWith,
)


def test_contains_condition_comprehensive() -> None:
    """Test Contains condition with various input types."""
    condition = Contains("test")

    assert condition("test_string") is True
    assert condition("string_test") is True
    assert condition("string_test_string") is True
    assert condition("no_match") is False
    assert condition("") is False
    assert condition(123) is False  # Non-string
    assert condition(None) is False  # None


def test_endswith_condition_comprehensive() -> None:
    """Test EndsWith condition with various input types."""
    condition = EndsWith("_test")

    assert condition("string_test") is True
    assert condition("another_test") is True
    assert condition("test_string") is False
    assert condition("_test") is True  # Exact match
    assert condition("test") is False
    assert condition("") is False
    assert condition(123) is False  # Non-string


def test_endswith_condition() -> None:
    """Test EndsWith condition matcher."""
    condition = EndsWith(".kitchen")

    assert condition("light.kitchen") is True
    assert condition("sensor.kitchen") is True
    assert condition("light.living") is False
    assert condition(123) is False  # Non-string


def test_startswith_condition_comprehensive() -> None:
    """Test StartsWith condition with various input types."""
    condition = StartsWith("test_")

    assert condition("test_string") is True
    assert condition("test_another") is True
    assert condition("string_test") is False
    assert condition("test_") is True  # Exact match
    assert condition("test") is False
    assert condition("") is False
    assert condition(123) is False  # Non-string


def test_startswith_condition() -> None:
    """Test StartsWith condition matcher."""
    condition = StartsWith("light.")

    assert condition("light.kitchen") is True
    assert condition("light.living") is True
    assert condition("sensor.temp") is False
    assert condition(123) is False  # Non-string


def test_present_condition_comprehensive() -> None:
    """Test Present condition with various value types."""
    condition = Present()

    assert condition("string") is True
    assert condition(123) is True
    assert condition(0) is True
    assert condition(False) is True
    assert condition(None) is True
    assert condition([]) is True
    assert condition({}) is True
    assert condition(MISSING_VALUE) is False


def test_present_condition() -> None:
    """Test Present condition matcher."""
    condition = Present()

    assert condition("any_value") is True
    assert condition(0) is True
    assert condition(False) is True
    assert condition(None) is True
    assert condition(MISSING_VALUE) is False


def test_missing_condition() -> None:
    """Test Missing condition detects MISSING_VALUE."""
    condition = Missing()

    assert condition(MISSING_VALUE) is True
    assert condition("string") is False
    assert condition(123) is False
    assert condition(0) is False
    assert condition(False) is False
    assert condition(None) is False
    assert condition([]) is False
    assert condition({}) is False


def test_glob_condition() -> None:
    """Test Glob condition matcher."""
    glob = Glob("light.*")

    assert glob("light.kitchen") is True
    assert glob("light.living") is True
    assert glob("sensor.temp") is False
    assert glob(123) is False  # Non-string


def test_regex_condition() -> None:
    """Test Regex condition matcher."""
    condition = Regex(r"light\..*kitchen")

    assert condition("light.main_kitchen") is True
    assert condition("light.back_kitchen") is True
    assert condition("light.living") is False
    assert condition("sensor.kitchen") is False
    assert condition(123) is False  # Non-string


def test_contains_condition() -> None:
    """Test Contains condition matcher."""
    condition = Contains("kitchen")

    assert condition("light.kitchen") is True
    assert condition("sensor.kitchen_temp") is True
    assert condition("light.living") is False
    assert condition(123) is False  # Non-string


def test_comparison_condition() -> None:
    """Test Comparison condition matcher."""

    greater_than = Comparison("gt", 10)
    less_than = Comparison("lt", 20)
    equal_to = Comparison("eq", 15)

    assert greater_than(15) is True
    assert greater_than(5) is False

    assert less_than(15) is True
    assert less_than(25) is False

    assert equal_to(15) is True
    assert equal_to(10) is False


@pytest.mark.parametrize(
    ("op", "threshold", "value", "expected"),
    [
        ("gt", 75, "80.5", True),
        ("gt", 75, "70.0", False),
        ("gt", 75, "80", True),
        ("gt", 20.5, "21.0", True),
        ("gt", 20.5, "20.0", False),
        ("lt", 100, "99.9", True),
        ("lt", 100, "200", False),
        ("ge", 75, "75.0", True),
        ("ge", 75, "74.9", False),
        ("le", 75, "75.0", True),
        ("le", 75, "75.1", False),
        ("eq", 0, "0", True),
        ("eq", 0, "1", False),
        ("ne", 0, "1", True),
        ("ne", 0, "0", False),
    ],
)
def test_comparison_numeric_string_coercion(op: str, threshold: int | float, value: str, expected: bool) -> None:
    assert Comparison(op, threshold)(value) is expected


@pytest.mark.parametrize("value", ["unavailable", "unknown", ""])
def test_comparison_non_numeric_string_returns_false(value: str) -> None:
    assert Comparison("gt", 75)(value) is False


@pytest.mark.parametrize(
    ("op", "threshold", "value", "expected"),
    [
        ("==", "on", "on", True),
        ("==", "on", "off", False),
        ("!=", "off", "on", True),
        ("!=", "on", "on", False),
        ("eq", "unavailable", "unavailable", True),
        ("ne", "unavailable", "unavailable", False),
    ],
)
def test_comparison_string_to_string_unchanged(op: str, threshold: str, value: str, expected: bool) -> None:
    assert Comparison(op, threshold)(value) is expected


def test_condition_summarize_glob() -> None:
    assert Glob("light.*").summarize() == "matches light.*"


def test_condition_summarize_starts_with() -> None:
    assert StartsWith("light.").summarize() == "starts with light."


def test_condition_summarize_ends_with() -> None:
    assert EndsWith(".kitchen").summarize() == "ends with .kitchen"


def test_condition_summarize_contains() -> None:
    assert Contains("kitchen").summarize() == "contains kitchen"


def test_condition_summarize_regex() -> None:
    assert Regex(r"light\..*kitchen").summarize() == r"matches /light\..*kitchen/"


def test_condition_summarize_present() -> None:
    assert Present().summarize() == "present"


def test_condition_summarize_missing() -> None:
    assert Missing().summarize() == "missing"


def test_condition_summarize_is_in() -> None:
    assert IsIn(["a", "b", "c"]).summarize() == "in [a, b, c]"


def test_condition_summarize_is_in_truncates() -> None:
    assert IsIn(["a", "b", "c", "d"]).summarize() == "in [a, b, c, …]"


def test_condition_summarize_not_in() -> None:
    assert NotIn(["x", "y"]).summarize() == "not in [x, y]"


def test_condition_summarize_intersects() -> None:
    assert Intersects(["a", "b"]).summarize() == "intersects [a, b]"


def test_condition_summarize_not_intersects() -> None:
    assert NotIntersects(["a", "b"]).summarize() == "does not intersect [a, b]"


def test_condition_summarize_is_or_contains() -> None:
    assert IsOrContains("light.kitchen").summarize() == "is or contains light.kitchen"


def test_condition_summarize_is_none() -> None:
    assert IsNone().summarize() == "is none"


def test_condition_summarize_is_not_none() -> None:
    assert IsNotNone().summarize() == "is not none"


def test_condition_summarize_comparison() -> None:
    assert Comparison(">", 50).summarize() == "> 50"


def test_condition_summarize_comparison_eq() -> None:
    assert Comparison("==", "on").summarize() == "== on"


def test_condition_summarize_comparison_aliased_ops() -> None:
    assert Comparison("gt", 50).summarize() == "> 50"
    assert Comparison("lt", 10).summarize() == "< 10"
    assert Comparison("ge", 100).summarize() == ">= 100"
    assert Comparison("le", 0).summarize() == "<= 0"
    assert Comparison("eq", "on").summarize() == "== on"
    assert Comparison("ne", "off").summarize() == "!= off"


def test_condition_summarize_increased() -> None:
    assert Increased().summarize() == "increased"


def test_condition_summarize_decreased() -> None:
    assert Decreased().summarize() == "decreased"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("10", "20", True),
        ("20", "10", False),
        ("10", "10", False),
        ("10.5", "11.0", True),
        (10, 20, True),
        ("unavailable", "20", False),
        ("10", "unavailable", False),
    ],
)
def test_increased_behavior(old: str | int, new: str | int, expected: bool) -> None:
    assert Increased()(old, new) is expected


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("20", "10", True),
        ("10", "20", False),
        ("10", "10", False),
        ("11.0", "10.5", True),
        (20, 10, True),
        ("unavailable", "20", False),
        ("10", "unavailable", False),
    ],
)
def test_decreased_behavior(old: str | int, new: str | int, expected: bool) -> None:
    assert Decreased()(old, new) is expected


def test_is_in_condition_behavior() -> None:
    """IsIn returns True only for values present in the collection."""
    condition = IsIn(["light.kitchen", "light.living"])

    assert condition("light.kitchen") is True
    assert condition("light.bedroom") is False


def test_is_in_rejects_string_collection() -> None:
    """IsIn raises ValueError when given a raw string instead of a sequence of values.

    A bare string is iterable character-by-character, which would silently produce
    nonsensical membership checks — so it is rejected outright.
    """
    with pytest.raises(ValueError, match="collection must be a sequence"):
        IsIn("light.kitchen")  # pyright: ignore[reportArgumentType]


def test_not_in_condition_behavior() -> None:
    """NotIn returns True only for values absent from the collection."""
    condition = NotIn(["light.kitchen", "light.living"])

    assert condition("light.bedroom") is True
    assert condition("light.kitchen") is False


def test_not_in_rejects_string_collection() -> None:
    """NotIn raises ValueError when given a raw string instead of a sequence."""
    with pytest.raises(ValueError, match="collection must be a sequence"):
        NotIn("light.kitchen")  # pyright: ignore[reportArgumentType]


def test_intersects_condition_behavior() -> None:
    """Intersects returns True when any item in the value overlaps with the collection."""
    condition = Intersects(["kitchen", "living"])

    assert condition(["kitchen", "office"]) is True
    assert condition(["office", "garage"]) is False


def test_intersects_returns_false_for_non_sequence_value() -> None:
    """Intersects returns False (not an error) when the value isn't a sequence at all."""
    condition = Intersects(["kitchen", "living"])

    assert condition(None) is False
    assert condition(42) is False


def test_intersects_rejects_string_collection() -> None:
    """Intersects raises ValueError when given a raw string instead of a sequence."""
    with pytest.raises(ValueError, match="collection must be a sequence"):
        Intersects("kitchen")  # pyright: ignore[reportArgumentType]


def test_not_intersects_condition_behavior() -> None:
    """NotIntersects returns True only when no item in the value overlaps with the collection."""
    condition = NotIntersects(["kitchen", "living"])

    assert condition(["office", "garage"]) is True
    assert condition(["kitchen", "office"]) is False


def test_not_intersects_returns_true_for_non_sequence_value() -> None:
    """NotIntersects returns True (vacuously, no overlap possible) for a non-sequence value."""
    condition = NotIntersects(["kitchen", "living"])

    assert condition(None) is True
    assert condition(42) is True


def test_not_intersects_rejects_string_collection() -> None:
    """NotIntersects raises ValueError when given a raw string instead of a sequence."""
    with pytest.raises(ValueError, match="collection must be a sequence"):
        NotIntersects("kitchen")  # pyright: ignore[reportArgumentType]


def test_is_or_contains_matches_scalar_value() -> None:
    """IsOrContains compares a scalar value directly for equality."""
    condition = IsOrContains("light.kitchen")

    assert condition("light.kitchen") is True
    assert condition("light.living") is False


def test_is_or_contains_matches_within_sequence() -> None:
    """IsOrContains checks membership when the value is a non-string sequence."""
    condition = IsOrContains("light.kitchen")

    assert condition(["light.kitchen", "light.living"]) is True
    assert condition(["light.living", "light.bedroom"]) is False


def test_is_or_contains_treats_string_value_as_scalar() -> None:
    """IsOrContains does not iterate over a string value character-by-character."""
    condition = IsOrContains("k")

    # "k" is a Sequence of characters, but strings are excluded from the "contains" branch
    assert condition("kitchen") is False
    assert condition("k") is True


def test_is_none_condition_behavior() -> None:
    """IsNone returns True only for None, not for other falsy values."""
    condition = IsNone()

    assert condition(None) is True
    assert condition(0) is False
    assert condition("") is False
    assert condition(MISSING_VALUE) is False


def test_is_not_none_condition_behavior() -> None:
    """IsNotNone returns False only for None."""
    condition = IsNotNone()

    assert condition(None) is False
    assert condition(0) is True
    assert condition("") is True


def test_comparison_invalid_operator_raises_value_error() -> None:
    """Comparison rejects unknown operator strings at construction time."""
    with pytest.raises(ValueError, match="Invalid comparison operator"):
        Comparison("~=", 10)  # pyright: ignore[reportArgumentType]


def test_comparison_returns_false_on_incompatible_types() -> None:
    """Comparison catches TypeError from an incompatible comparison and returns False."""
    condition = Comparison("gt", 10)

    assert condition(None) is False
    assert condition(object()) is False


def test_glob_repr() -> None:
    """Glob has a custom repr distinct from the default dataclass repr."""
    assert repr(Glob("light.*")) == "Glob('light.*')"


def test_starts_with_repr() -> None:
    """StartsWith has a custom repr distinct from the default dataclass repr."""
    assert repr(StartsWith("light.")) == "StartsWith('light.')"


def test_ends_with_repr() -> None:
    """EndsWith has a custom repr distinct from the default dataclass repr."""
    assert repr(EndsWith(".kitchen")) == "EndsWith('.kitchen')"


def test_contains_repr() -> None:
    """Contains has a custom repr distinct from the default dataclass repr."""
    assert repr(Contains("kitchen")) == "Contains('kitchen')"


def test_regex_repr() -> None:
    """Regex has a custom repr distinct from the default dataclass repr."""
    assert repr(Regex(r"light\..*kitchen")) == r"Regex('light\\..*kitchen')"


def test_comparison_ge_and_le_operators() -> None:
    """Comparison supports >= and <= via both symbol and alias forms."""
    assert Comparison(">=", 10)(10) is True
    assert Comparison(">=", 10)(9) is False
    assert Comparison("<=", 10)(10) is True
    assert Comparison("<=", 10)(11) is False
    assert Comparison("ge", 10)(10) is True
    assert Comparison("le", 10)(10) is True
