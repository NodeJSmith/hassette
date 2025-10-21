"""Additional tests for predicate conditions and accessors not covered elsewhere."""

import typing
from types import SimpleNamespace

from hassette.const import MISSING_VALUE
from hassette.core.resources.bus.predicates.conditions import (
    Contains,
    EndsWith,
    IsOrContains,
    Missing,
    Present,
    StartsWith,
)
from hassette.core.resources.bus.predicates.predicates import DidChange, IsMissing, IsPresent, ServiceMatches, ValueIs


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


def test_service_matches_with_globs() -> None:
    """Test ServiceMatches predicate with glob patterns."""
    # Mock service event
    event = SimpleNamespace(payload=SimpleNamespace(data=SimpleNamespace(service="turn_on")))

    # Exact match
    predicate = ServiceMatches("turn_on")
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    # No match
    predicate = ServiceMatches("turn_off")
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]

    # Glob pattern
    predicate = ServiceMatches("turn_*")
    assert predicate(event) is True  # pyright: ignore[reportArgumentType]

    predicate = ServiceMatches("set_*")
    assert predicate(event) is False  # pyright: ignore[reportArgumentType]


def test_did_change_predicate() -> None:
    """Test DidChange predicate detects value differences."""

    def source_same(event) -> tuple[typing.Any, typing.Any]:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return ("value", "value")

    def source_different(event) -> tuple[typing.Any, typing.Any]:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return ("old", "new")

    mock_event = SimpleNamespace()

    # Same values
    predicate = DidChange(source_same)
    assert predicate(mock_event) is False

    # Different values
    predicate = DidChange(source_different)
    assert predicate(mock_event) is True


def test_is_present_predicate() -> None:
    """Test IsPresent predicate detects non-missing values."""

    def source_present(event) -> typing.Any:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return "present_value"

    def source_missing(event) -> typing.Any:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return MISSING_VALUE

    mock_event = SimpleNamespace()

    # Present value
    predicate = IsPresent(source_present)
    assert predicate(mock_event) is True

    # Missing value
    predicate = IsPresent(source_missing)
    assert predicate(mock_event) is False


def test_is_missing_predicate() -> None:
    """Test IsMissing predicate detects missing values."""

    def source_present(event) -> typing.Any:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return "present_value"

    def source_missing(event) -> typing.Any:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return MISSING_VALUE

    mock_event = SimpleNamespace()

    # Present value
    predicate = IsMissing(source_present)
    assert predicate(mock_event) is False

    # Missing value
    predicate = IsMissing(source_missing)
    assert predicate(mock_event) is True


def test_is_or_contains() -> None:
    """Test IsOrContains condition with single values and collections."""
    event = SimpleNamespace(
        payload=SimpleNamespace(data=SimpleNamespace(service_data={"entity_id": ["light.kitchen"]}))
    )

    non_matching_event = SimpleNamespace(
        payload=SimpleNamespace(data=SimpleNamespace(service_data={"entity_id": ["light.other"]}))
    )

    predicate = ValueIs(
        source=lambda event: event.payload.data.service_data.get("entity_id", MISSING_VALUE),
        condition=IsOrContains("light.kitchen"),
    )

    assert predicate(event) is True, "Expected predicate to match when value is in collection"
    assert predicate(non_matching_event) is False, "Expected predicate to not match when value is not in collection"
