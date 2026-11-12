"""Value comparison and ``where=`` clause normalization."""

import typing
from inspect import isawaitable
from typing import Any

from hassette.const import NOT_PROVIDED
from hassette.event_handling.conditions import coerce_to_literal_type
from hassette.event_handling.predicate_collections import ensure_tuple, is_predicate_collection
from hassette.exceptions import UnableToConvertValueError
from hassette.types.types import WhereClause
from hassette.utils.func_utils import is_async_callable

from .combinators import AllOf

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from hassette.types import ChangeType, Predicate


def compare_value(actual: Any, condition: "ChangeType") -> bool:
    """Compare an actual value against a condition.

    Args:
        actual: The actual value to compare.
        condition: The condition to compare against. Can be a literal value or a callable.

    Returns:
        True if the actual value matches the condition, False otherwise.

    Behavior:
        - If condition is NOT_PROVIDED, treat as 'no constraint' (True).
        - If condition is a non-callable, compare for equality only. A string ``actual`` is first coerced to a
          bool or numeric condition's type (see ``coerce_to_literal_type``); a string that cannot be coerced does
          not match. Wrap the literal in ``C.Exact`` to compare the raw value instead.
        - If condition is a callable, call and ensure bool.
        - Async/coroutine predicates are explicitly disallowed (raise).

    Note:
        This function does not handle collections any differently than other literals — it compares
        them for equality only. Use specific conditions like IsIn/NotIn/Intersects for collection membership tests.
    """
    if condition is NOT_PROVIDED:
        return True

    if not callable(condition):
        try:
            return coerce_to_literal_type(actual, condition) == condition
        except UnableToConvertValueError:
            return False

    if is_async_callable(condition):
        raise TypeError("Async predicates are not supported; make the condition synchronous.")

    if typing.TYPE_CHECKING:
        condition = typing.cast("Callable[[Any], bool]", condition)

    result = condition(actual)

    if isawaitable(result):
        raise TypeError("Predicate returned an awaitable; make it return bool.")

    # Fallback: callable but not declared as PredicateCallable; still require bool.
    if not isinstance(result, bool):
        raise TypeError(f"Predicate must return bool, got {type(result)}")
    return result


def _reject_async_predicate(pred: Any) -> None:
    if is_async_callable(pred):
        raise TypeError(f"Bus predicates must be synchronous; got async callable {pred!r}")


def normalize_where(where: WhereClause) -> "Predicate | None":
    """Normalize a 'where' clause into a single Predicate, or None.

    Rejects async callables (including inside collections) at registration time.

    - If where is None → None
    - If where is a predicate collection (list/tuple/set/...) → AllOf wrapping flattened members
    - Otherwise (single predicate or mapping handled elsewhere) → where
    """
    if where is None:
        return None

    _reject_async_predicate(where)

    if is_predicate_collection(where):
        flat = ensure_tuple(where)
        for pred in flat:
            _reject_async_predicate(pred)
        return AllOf(flat)

    # help the type checker know that `where` is not an Sequence here
    if typing.TYPE_CHECKING:
        assert not isinstance(where, Sequence)

    return where  # single predicate or mapping gets handled by the caller
