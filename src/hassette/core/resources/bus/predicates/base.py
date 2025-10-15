import itertools
import typing
from collections.abc import Iterable
from dataclasses import dataclass
from inspect import isawaitable

from hassette.types import E_contra

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.types import Predicate


@dataclass(frozen=True)
class Guard(typing.Generic[E_contra]):
    """Wraps a predicate function to be used in combinators.

    Allows for passing any callable as a predicate. Generic over E_contra to allow type checkers to understand the
    expected event type.
    """

    fn: "Predicate[E_contra]"

    async def __call__(self, event: "Event[E_contra]") -> bool:  # pyright: ignore[reportInvalidTypeArguments]
        return await _eval(self.fn, event)


@dataclass(frozen=True)
class AllOf:
    """Predicate that evaluates to True if all of the contained predicates evaluate to True."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    async def __call__(self, event: "Event") -> bool:
        for p in self.predicates:
            if not await _eval(p, event):
                return False
        return True

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Iterable[Predicate]") -> "AllOf":
        return cls(tuple(ensure_iterable(where)))

    def __iter__(self):
        return iter(self.predicates)


@dataclass(frozen=True)
class AnyOf:
    """Predicate that evaluates to True if any of the contained predicates evaluate to True."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    async def __call__(self, event: "Event") -> bool:
        for p in self.predicates:
            if await _eval(p, event):
                return True
        return False

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Iterable[Predicate]") -> "AnyOf":
        return cls(tuple(ensure_iterable(where)))


@dataclass(frozen=True)
class Not:
    """Negates the result of the predicate."""

    predicate: "Predicate"

    async def __call__(self, event: "Event") -> bool:
        return not await _eval(self.predicate, event)


def normalize_where(where: "Predicate | Iterable[Predicate] | None") -> "Predicate | None":
    """Normalize the 'where' clause into a single Predicate or None.

    Args:
        where (Predicate | Iterable[Predicate] | None): The 'where' clause to normalize.

    Returns:
        Predicate | None: A single Predicate if 'where' was provided, otherwise None.
    """

    if where is None:
        return None

    if isinstance(where, Iterable) and not callable(where):
        return AllOf.ensure_iterable(where)

    return where


def ensure_iterable(where: "Predicate | Iterable[Predicate]") -> Iterable["Predicate"]:
    """Ensure that the 'where' clause is an iterable of predicates.

    Args:
        where (Predicate | Iterable[Predicate]): The 'where' clause to ensure as iterable.

    Returns:
        Iterable[Predicate]: An iterable of predicates.
    """

    if isinstance(where, Iterable) and not callable(where):
        flat_where = itertools.chain.from_iterable(
            w.predicates if isinstance(w, AllOf | AnyOf) else (w,) for w in where
        )
        return flat_where

    return (where,)


async def _eval(pred: "Predicate", event: "Event") -> bool:
    """Evaluate a predicate, handling both synchronous and asynchronous callables."""

    res = pred(event)
    if isawaitable(res):
        return await res
    return bool(res)
