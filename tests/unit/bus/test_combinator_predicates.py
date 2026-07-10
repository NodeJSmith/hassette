"""Tests for predicate combinators and utility functions.

Tests the base combinators (AllOf, AnyOf, Not, Guard) and utility functions
for composing and normalizing predicates.
"""

from types import SimpleNamespace

from hassette.event_handling.predicates import (
    AllOf,
    AnyOf,
    Guard,
    Not,
    ensure_tuple,
    is_predicate_collection,
    normalize_where,
)


def always_true(_event) -> bool:
    return True


def always_false(_event) -> bool:
    return False


# AllOf combinator tests
def test_allof_evaluates_all_predicates() -> None:
    """Test that AllOf returns True only when all predicates return True."""
    mock_event = SimpleNamespace()

    # All true
    predicate = AllOf((always_true, always_true))
    assert predicate(mock_event) is True  # pyright: ignore[reportArgumentType]

    # Mixed
    predicate = AllOf((always_true, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]

    # All false
    predicate = AllOf((always_false, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]


# AnyOf combinator tests
def test_anyof_evaluates_any_predicate() -> None:
    """Test that AnyOf returns True when any predicate returns True."""
    mock_event = SimpleNamespace()

    # Any true
    predicate = AnyOf((always_false, always_true))
    assert predicate(mock_event) is True  # pyright: ignore[reportArgumentType]

    # All false
    predicate = AnyOf((always_false, always_false))
    assert predicate(mock_event) is False  # pyright: ignore[reportArgumentType]


# Not combinator tests
def test_not_inverts_predicate() -> None:
    """Test that Not inverts the result of wrapped predicate."""
    mock_event = SimpleNamespace()

    assert Not(always_true)(mock_event) is False  # pyright: ignore[reportArgumentType]
    assert Not(always_false)(mock_event) is True  # pyright: ignore[reportArgumentType]


# Guard combinator tests
def test_guard_wraps_callable() -> None:
    """Test that Guard wraps arbitrary callables as predicates."""
    sentinel = object()

    def check_identity(event) -> bool:
        return event is sentinel

    guard = Guard(check_identity)
    assert guard(sentinel) is True
    assert guard(object()) is False


# Utility function tests
def test_ensure_tuple_flattening() -> None:
    """Test ensure_tuple flattens nested predicate sequences."""

    def pred1(_event) -> bool:
        return True

    def pred2(_event) -> bool:
        return False

    def pred3(_event) -> bool:
        return True

    # Nested sequence
    result = ensure_tuple([pred1, (pred2, pred3)])  # pyright: ignore[reportArgumentType]
    assert len(result) == 3
    assert result == (pred1, pred2, pred3)

    # Single predicate
    result = ensure_tuple(pred1)
    assert result == (pred1,)

    # Flat sequence
    result = ensure_tuple([pred1, pred2])
    assert result == (pred1, pred2)


def test_normalize_where_handling() -> None:
    """Test normalize_where with various input types."""

    # None input
    assert normalize_where(None) is None

    # Single predicate
    result = normalize_where(always_true)
    assert result is always_true

    # Sequence of predicates
    result = normalize_where([always_true, always_false])
    assert isinstance(result, AllOf)
    assert len(result.predicates) == 2


# AllOf.ensure_iterable / AnyOf.ensure_iterable classmethods
def test_allof_ensure_iterable_wraps_a_sequence() -> None:
    """AllOf.ensure_iterable builds an AllOf from a sequence of predicates."""
    result = AllOf.ensure_iterable([always_true, always_false])

    assert isinstance(result, AllOf)
    assert result.predicates == (always_true, always_false)


def test_anyof_ensure_iterable_wraps_a_sequence() -> None:
    """AnyOf.ensure_iterable builds an AnyOf from a sequence of predicates."""
    result = AnyOf.ensure_iterable([always_true, always_false])

    assert isinstance(result, AnyOf)
    assert result.predicates == (always_true, always_false)


# is_predicate_collection edge cases
def test_is_predicate_collection_false_for_none() -> None:
    """is_predicate_collection returns False for None (nothing to recurse into)."""
    assert is_predicate_collection(None) is False


def test_is_predicate_collection_false_for_callable() -> None:
    """is_predicate_collection returns False for a callable — predicates aren't exploded."""
    assert is_predicate_collection(always_true) is False


def test_is_predicate_collection_false_for_string_and_mapping() -> None:
    """is_predicate_collection excludes strings, bytes, and mappings even though they're iterable."""
    assert is_predicate_collection("light.kitchen") is False
    assert is_predicate_collection(b"light.kitchen") is False
    assert is_predicate_collection({"entity_id": "light.kitchen"}) is False


def test_is_predicate_collection_true_for_list_tuple_set() -> None:
    """is_predicate_collection returns True for list/tuple/set/frozenset containers."""
    assert is_predicate_collection([always_true]) is True
    assert is_predicate_collection((always_true,)) is True
    assert is_predicate_collection({always_true}) is True
    assert is_predicate_collection(frozenset({always_true})) is True
