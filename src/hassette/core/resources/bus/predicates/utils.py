import itertools
import typing
from collections.abc import Iterable
from inspect import isawaitable

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.types import Predicate


def normalize_where(where: "Predicate | Iterable[Predicate] | None") -> "Predicate | None":
    """Normalize the 'where' clause into a single Predicate or None. If 'where' is an iterable, it is wrapped in an\
        AllOf.

    Args:
        where (Predicate | Iterable[Predicate] | None): The 'where' clause to normalize.

    Returns:
        Predicate | None: A single Predicate if 'where' was provided, otherwise None.
    """

    # prevent circular import
    from .base import AllOf

    if where is None:
        return None

    if isinstance(where, Iterable) and not callable(where):
        return AllOf.ensure_iterable(where)

    return where


def ensure_tuple(where: "Predicate | Iterable[Predicate]") -> tuple["Predicate", ...]:
    """Ensure that the 'where' clause is an tuple of predicates.

    Args:
        where (Predicate | Iterable[Predicate]): The 'where' clause to ensure is iterable.

    Returns:
        tuple[Predicate, ...]: A tuple of predicates.
    """

    if isinstance(where, Iterable) and not callable(where):
        flat_where = itertools.chain.from_iterable(ensure_tuple(w) for w in where)
        return tuple(flat_where)

    return (where,)


async def evaluate_predicate(pred: "Predicate", event: "Event") -> bool:
    """Evaluate a predicate, handling both synchronous and asynchronous callables."""

    res = pred(event)
    if isawaitable(res):
        return await res
    return bool(res)
