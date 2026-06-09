"""Tests for predicate condition functions.

Tests condition matchers like Contains, EndsWith, StartsWith, Present, Missing,
Glob, Regex, etc. that are used within predicates to test extracted values.
"""

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


def test_comparison_numeric_string_coercion() -> None:
    """Comparison coerces string values to float when compare_to is numeric."""
    assert Comparison("gt", 75)("80.5") is True
    assert Comparison("gt", 75)("70.0") is False
    assert Comparison("lt", 100)("99.9") is True
    assert Comparison("lt", 100)("200") is False
    assert Comparison("ge", 75)("75.0") is True
    assert Comparison("ge", 75)("74.9") is False
    assert Comparison("le", 75)("75.0") is True
    assert Comparison("le", 75)("75.1") is False
    assert Comparison("eq", 0)("0") is True
    assert Comparison("eq", 0)("1") is False
    assert Comparison("ne", 0)("1") is True
    assert Comparison("ne", 0)("0") is False
    # int compare_to against string value
    assert Comparison("gt", 75)("80") is True
    # float compare_to against string value
    assert Comparison("gt", 20.5)("21.0") is True
    assert Comparison("gt", 20.5)("20.0") is False


def test_comparison_non_numeric_string_returns_false() -> None:
    """Non-numeric strings return False gracefully, no exceptions raised."""
    assert Comparison("gt", 75)("unavailable") is False
    assert Comparison("gt", 75)("unknown") is False
    assert Comparison("gt", 75)("") is False
    assert Comparison("lt", 50)("unavailable") is False


def test_comparison_string_to_string_unchanged() -> None:
    """String-to-string comparisons are unaffected by numeric coercion."""
    assert Comparison("==", "on")("on") is True
    assert Comparison("==", "on")("off") is False
    assert Comparison("!=", "off")("on") is True
    assert Comparison("!=", "on")("on") is False


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
