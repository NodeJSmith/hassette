from types import SimpleNamespace

from hassette.core.resources.bus.predicates.predicates import AllOf, AnyOf, Guard, Not
from hassette.core.resources.bus.predicates.utils import ensure_tuple, normalize_where


def test_allof_requires_all_predicates_true() -> None:
    """Test that AllOf predicate returns True only when all contained predicates return True."""
    predicate = AllOf((lambda _: True, lambda _: True))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is True  # pyright: ignore[reportArgumentType]


def test_allof_returns_false_when_any_predicate_fails() -> None:
    """Test that AllOf predicate returns False when any contained predicate returns False."""
    predicate = AllOf((lambda _: True, lambda _: False))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is False  # pyright: ignore[reportArgumentType]


def test_anyof_succeeds_when_any_predicate_matches() -> None:
    """Test that AnyOf predicate returns True when any contained predicate returns True."""
    predicate = AnyOf((lambda _: False, lambda _: True))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is True  # pyright: ignore[reportArgumentType]


def test_anyof_returns_false_when_all_predicates_fail() -> None:
    """Test that AnyOf predicate returns False only when all contained predicates return False."""
    predicate = AnyOf((lambda _: False, lambda _: False))  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is False  # pyright: ignore[reportArgumentType]


def test_not_inverts_predicate_result() -> None:
    """Test that Not predicate inverts the result of the wrapped predicate."""
    predicate = Not(lambda _: True)  # pyright: ignore[reportArgumentType]
    assert predicate(SimpleNamespace()) is False  # pyright: ignore[reportArgumentType]


def test_guard_wraps_callable_and_executes_it() -> None:
    """Test that Guard wraps a callable predicate and executes it correctly."""
    sentinel = object()
    guard = Guard(lambda event: event is sentinel)
    assert guard(sentinel) is True
    assert guard(object()) is False


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
