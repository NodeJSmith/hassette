import itertools
import typing
from collections.abc import Iterable
from dataclasses import dataclass
from inspect import isawaitable

from hassette.core.types import E_contra

if typing.TYPE_CHECKING:
    from hassette.core.events import Event
    from hassette.core.types import Predicate


SENTINEL = object()
T = typing.TypeVar("T")


def ensure_iterable(where: "Predicate | Iterable[Predicate]") -> Iterable["Predicate"]:
    if isinstance(where, Iterable) and not callable(where):
        flat_where = itertools.chain.from_iterable(w.preds if isinstance(w, AllOf | AnyOf) else (w,) for w in where)
        return flat_where

    return (where,)


@dataclass(frozen=True)
class Guard(typing.Generic[E_contra]):
    """Wraps a predicate function to be used in combinators.

    Allows for passing any callable as a predicate. Generic over E_contra to allow type checkers to understand the
    expected event type.
    """

    fn: "Predicate[E_contra]"

    async def __call__(self, event: "Event[E_contra]") -> bool:
        return await _eval(self.fn, event)


@dataclass(frozen=True)
class AllOf:
    preds: tuple["Predicate", ...]

    async def __call__(self, event: "Event") -> bool:
        for p in self.preds:
            if not await _eval(p, event):
                return False
        return True

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Iterable[Predicate]") -> "AllOf":
        # return cls((where,))
        return cls(tuple(ensure_iterable(where)))

    def __iter__(self):
        return iter(self.preds)


@dataclass(frozen=True)
class AnyOf:
    preds: tuple["Predicate", ...]

    async def __call__(self, event: "Event") -> bool:
        for p in self.preds:
            if await _eval(p, event):
                return True
        return False

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Iterable[Predicate]") -> "AnyOf":
        return cls(tuple(ensure_iterable(where)))


@dataclass(frozen=True)
class Not:
    pred: "Predicate"

    async def __call__(self, event: "Event") -> bool:
        return not await _eval(self.pred, event)


def normalize_where(
    where: "Predicate | Iterable[Predicate] | None",
) -> "Predicate | None":
    if where is None:
        return None

    if isinstance(where, Iterable) and not callable(where):
        return AllOf.ensure_iterable(where)

    return where


async def _eval(pred: "Predicate", event: "Event") -> bool:
    res = pred(event)
    if isawaitable(res):
        return await res
    return bool(res)
