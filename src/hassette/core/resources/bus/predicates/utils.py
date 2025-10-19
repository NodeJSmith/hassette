import typing
from collections.abc import Mapping, Sequence
from inspect import isawaitable, iscoroutinefunction
from typing import Any

from boltons.iterutils import is_collection

from hassette.const.misc import NOT_PROVIDED
from hassette.types import ChangeType, Predicate, PredicateCallable

if typing.TYPE_CHECKING:
    from hassette.types import Predicate


def _is_predicate_collection(obj: Any) -> bool:
    """Return True for *predicate collections* we want to recurse into.

    We treat only list/tuple/set/frozenset-like things as collections of predicates.
    We explicitly DO NOT recurse into:
      - mappings (those feed ServiceDataWhere elsewhere),
      - strings/bytes,
      - callables (predicates are callables; don't explode them),
      - None.
    """
    if obj is None:
        return False
    if callable(obj):
        return False
    if isinstance(obj, (str, bytes, Mapping)):
        return False
    # boltons.is_collection filters out scalars for us; we just fence off types we don't want
    return is_collection(obj)


def normalize_where(where: "Predicate | Sequence[Predicate] | None"):
    """Normalize a 'where' clause into a single Predicate (usually AllOf.ensure_iterable), or None.

    - If where is None → None
    - If where is a predicate collection (list/tuple/set/...) → AllOf.ensure_iterable(where)
    - Otherwise (single predicate or mapping handled elsewhere) → where
    """
    if where is None:
        return None

    # prevent circular import only when needed
    if _is_predicate_collection(where):
        from .predicates import AllOf

        return AllOf.ensure_iterable(where)  # type: ignore[arg-type]

    # help the type checker know that `where` is not an Sequence here
    if typing.TYPE_CHECKING:
        assert not isinstance(where, Sequence)

    return where  # single predicate or mapping gets handled by the caller


def ensure_tuple(where: "Predicate | Sequence[Predicate]") -> tuple["Predicate", ...]:
    """Ensure the 'where' is a flat tuple of predicates, flattening *only* predicate collections.

    Recurses into list/tuple/set/frozenset; leaves Mapping, strings/bytes, and callables intact.
    """
    if _is_predicate_collection(where):
        out: list[Predicate] = []
        # mypy/pyright: guarded by _is_predicate_collection, so safe to iterate
        for item in typing.cast("Sequence[Predicate | Sequence[Predicate]]", where):
            out.extend(ensure_tuple(item))
        return tuple(out)

    return (typing.cast("Predicate", where),)


def compare_value(condition: ChangeType, actual: Any) -> bool:
    """Compare a 'condition' (literal or predicate) against an actual value.

    - If condition is NOT_PROVIDED, treat as 'no constraint' (True).
    - If condition is a non-callable, compare for equality (or membership for collections).
    - If condition is a PredicateCallable, call and ensure bool.
    - Async/coroutine predicates are explicitly disallowed (raise).
    """
    if condition is NOT_PROVIDED:
        return True

    if not callable(condition):
        # Treat sequences/sets as collections where membership constitutes a match.
        if isinstance(actual, (set, frozenset)):
            return condition in actual

        if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes, bytearray)):
            return condition in actual

        return actual == condition

    # Disallow async predicates to keep filters pure/fast.
    if iscoroutinefunction(condition):
        raise TypeError("Async predicates are not supported; make the condition synchronous.")

    result = condition(actual)

    if isawaitable(result):
        raise TypeError("Predicate returned an awaitable; make it return bool.")

    if isinstance(condition, PredicateCallable):
        if not isinstance(result, bool):
            raise TypeError(f"Predicate callable {condition!r} did not return a boolean (returned {type(result)})")
        return result

    # Fallback: callable but not declared as PredicateCallable; still require bool.
    if not isinstance(result, bool):
        raise TypeError(f"Predicate must return bool, got {type(result)}")
    return result
