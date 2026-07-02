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


def always_true(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
    """Test helper that always returns True."""
    return True


def always_false(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
    """Test helper that always returns False."""
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


def test_allof_requires_all_predicates_true() -> None:
    """Test that AllOf predicate returns True only when all contained predicates return True."""
    predicate = AllOf((lambda _: True, lambda _: True))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is True  # pyright: ignore[reportArgumentType]


def test_allof_returns_false_when_any_predicate_fails() -> None:
    """Test that AllOf predicate returns False when any contained predicate returns False."""
    predicate = AllOf((lambda _: True, lambda _: False))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is False  # pyright: ignore[reportArgumentType]


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


def test_anyof_succeeds_when_any_predicate_matches() -> None:
    """Test that AnyOf predicate returns True when any contained predicate returns True."""
    predicate = AnyOf((lambda _: False, lambda _: True))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is True  # pyright: ignore[reportArgumentType]


def test_anyof_returns_false_when_all_predicates_fail() -> None:
    """Test that AnyOf predicate returns False only when all contained predicates return False."""
    predicate = AnyOf((lambda _: False, lambda _: False))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is False  # pyright: ignore[reportArgumentType]


# Not combinator tests
def test_not_inverts_predicate() -> None:
    """Test that Not inverts the result of wrapped predicate."""
    mock_event = SimpleNamespace()

    assert Not(always_true)(mock_event) is False  # pyright: ignore[reportArgumentType]
    assert Not(always_false)(mock_event) is True  # pyright: ignore[reportArgumentType]


def test_not_inverts_predicate_result() -> None:
    """Test that Not predicate inverts the result of the wrapped predicate."""
    predicate = Not(lambda _: True)  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is False  # pyright: ignore[reportArgumentType]


# Guard combinator tests
def test_guard_wraps_callable() -> None:
    """Test that Guard wraps arbitrary callables as predicates."""
    sentinel = object()

    def check_identity(event) -> bool:
        return event is sentinel

    guard = Guard(check_identity)
    assert guard(sentinel) is True
    assert guard(object()) is False


def test_guard_wraps_callable_and_executes_it() -> None:
    """Test that Guard wraps a callable predicate and executes it correctly."""
    sentinel = object()
    guard = Guard(lambda event: event is sentinel)
    assert guard(sentinel) is True
    assert guard(object()) is False


# Utility function tests
def test_ensure_tuple_flattening() -> None:
    """Test ensure_tuple flattens nested predicate sequences."""

    def pred1(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return True

    def pred2(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return False

    def pred3(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
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


def test_ensure_tuple_flattens_nested_sequences() -> None:
    """Test that ensure_tuple flattens nested sequences of predicates into a flat tuple."""
    predicates = ensure_tuple([lambda _: True, (lambda _: False, lambda _: True)])  # pyright: ignore[reportArgumentType]
    assert len(predicates) == 3


def test_ensure_tuple_handles_single_predicate() -> None:
    """Test that ensure_tuple wraps single predicates in a tuple."""

    def predicate(_event) -> bool:  # pyright: ignore[reportUnusedParameter]
        return True

    result = ensure_tuple(predicate)  # pyright: ignore[reportArgumentType]
    assert result == (predicate,)
    assert len(result) == 1


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


def test_normalize_where_returns_allof_for_sequences() -> None:
    """Test that normalize_where wraps sequences of predicates in AllOf."""
    predicate = normalize_where([lambda _: True, lambda _: True])  # pyright: ignore[reportArgumentType]
    assert isinstance(predicate, AllOf)


def test_normalize_where_returns_single_predicate() -> None:
    """Test that normalize_where returns single predicates unchanged."""

    def single(event) -> bool:  # pyright: ignore[reportUnusedParameter] # noqa: ARG001
        return True

    predicate = normalize_where(single)
    assert predicate is single


def test_normalize_where_returns_none_for_none() -> None:
    """Test that normalize_where returns None when passed None."""
    predicate = normalize_where(None)
    assert predicate is None


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
