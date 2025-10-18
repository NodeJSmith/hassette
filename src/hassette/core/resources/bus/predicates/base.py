import typing
from dataclasses import dataclass

from hassette.types import E_contra

from .utils import ensure_tuple, evaluate_predicate

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

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
        return await evaluate_predicate(self.fn, event)


@dataclass(frozen=True)
class AllOf:
    """Predicate that evaluates to True if all of the contained predicates evaluate to True."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    async def __call__(self, event: "Event") -> bool:
        for p in self.predicates:
            if not await evaluate_predicate(p, event):
                return False
        return True

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Iterable[Predicate]") -> "AllOf":
        return cls(ensure_tuple(where))

    def __iter__(self):
        return iter(self.predicates)


@dataclass(frozen=True)
class AnyOf:
    """Predicate that evaluates to True if any of the contained predicates evaluate to True."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    async def __call__(self, event: "Event") -> bool:
        for p in self.predicates:
            if await evaluate_predicate(p, event):
                return True
        return False

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Iterable[Predicate]") -> "AnyOf":
        return cls(ensure_tuple(where))


@dataclass(frozen=True)
class Not:
    """Negates the result of the predicate."""

    predicate: "Predicate"

    async def __call__(self, event: "Event") -> bool:
        return not await evaluate_predicate(self.predicate, event)
