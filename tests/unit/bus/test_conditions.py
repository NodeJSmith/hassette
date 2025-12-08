"""Tests for predicate condition functions.

Tests condition matchers like Contains, EndsWith, StartsWith, Present, Missing,
Glob, Regex, etc. that are used within predicates to test extracted values.
"""

from hassette.bus.conditions import (
    Contains,
    EndsWith,
    Glob,
    Missing,
    Present,
    Regex,
    StartsWith,
)
from hassette.const import MISSING_VALUE


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
