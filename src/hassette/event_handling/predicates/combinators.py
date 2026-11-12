"""Predicate composition: the ``&``/``|``/``~`` operators, the combinators, and summary rendering."""

import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Self, TypeVar

from hassette.event_handling.predicate_collections import ensure_tuple
from hassette.types import EventT
from hassette.utils.func_utils import callable_stable_name as callable_name

if typing.TYPE_CHECKING:
    from hassette.events import AnyEvent
    from hassette.types import Predicate

CombinatorT = TypeVar("CombinatorT", bound="_PredicateCombinator")


class _PredicateOps:
    """Adds ``&``, ``|``, and ``~`` composition to the predicate types in this package.

    ``a & b`` builds an `AllOf`, ``a | b`` builds an `AnyOf`, and ``~a`` builds a `Not`. The result is an ordinary
    predicate object, so it can be passed to ``where=`` or nested inside the explicit combinators.

    Chains flatten rather than nest: ``a & b & c`` produces ``AllOf((a, b, c))``, which keeps ``summarize()``
    identical to the explicit form.

    ``AllOf``, ``AnyOf``, and ``Not`` are defined further down this module; the operators resolve them at call time,
    not at class-definition time.

    Examples:
        ```python
        P.StateTo("on") & P.DomainMatches("light")
        P.StateTo("on") | P.StateTo("unavailable")
        ~P.StateTo("off")
        ```
    """

    if typing.TYPE_CHECKING:
        # Type-checking only, with no runtime counterpart: every class mixing this in defines its own __call__,
        # and declaring the signature here lets type checkers treat `self` as a Predicate in the combinators below.
        def __call__(self, value: Any, /) -> bool: ...

    def __and__(self, other: "Predicate") -> "AllOf":
        if not callable(other):
            return NotImplemented
        return _combine(AllOf, self, other)

    def __rand__(self, other: "Predicate") -> "AllOf":
        if not callable(other):
            return NotImplemented
        return _combine(AllOf, other, self)

    def __or__(self, other: "Predicate") -> "AnyOf":
        if not callable(other):
            return NotImplemented
        return _combine(AnyOf, self, other)

    def __ror__(self, other: "Predicate") -> "AnyOf":
        if not callable(other):
            return NotImplemented
        return _combine(AnyOf, other, self)

    def __invert__(self) -> "Not":
        return Not(self)


def _combine(combinator: type[CombinatorT], left: "Predicate", right: "Predicate") -> CombinatorT:
    """Build ``combinator`` from two operands, absorbing operands of the same combinator type.

    Absorption is what flattens chains, and it applies to explicitly constructed combinators too: ``AllOf((a, b)) & c``
    yields ``AllOf((a, b, c))``, not a nested pair. The two forms evaluate identically, so the grouping carries no
    meaning worth preserving.
    """
    predicates: list[Predicate] = []
    for operand in (left, right):
        if isinstance(operand, combinator):
            predicates.extend(operand.predicates)
        else:
            predicates.append(operand)
    return combinator(tuple(predicates))


@dataclass(frozen=True)
class Guard(_PredicateOps, typing.Generic[EventT]):
    """Wraps a predicate function to be used in combinators.

    Allows for passing any callable as a predicate. Generic over EventT to allow type checkers to understand the
    expected event type.
    """

    fn: "Predicate[EventT]"

    def __call__(self, value: "EventT") -> bool:
        """Return the wrapped function's result for ``value``."""
        return self.fn(value)

    def summarize(self) -> str:
        """Return ``"custom condition"``; an arbitrary callable has no inspectable meaning."""
        return "custom condition"


def _summarize(obj: Any, non_callable_fallback: Callable[[Any], str]) -> str:
    """Return a human-readable summary of a predicate or condition.

    Delegates to the object's ``summarize()`` method when available, falls back to a stable callable name for
    callables, or to ``non_callable_fallback`` otherwise.
    """
    if hasattr(obj, "summarize"):
        return obj.summarize()  # pyright: ignore[reportAttributeAccessIssue]
    if callable(obj):
        return callable_name(obj)
    return non_callable_fallback(obj)


def _summarize_predicate(predicate: "Predicate") -> str:
    """Return a human-readable summary of a predicate.

    Delegates to the predicate's ``summarize()`` method when available, otherwise falls back to a stable callable
    name, or ``repr()`` for non-callable values.
    """
    return _summarize(predicate, repr)


def summarize_condition(condition: Any) -> str:
    """Return a human-readable summary of a condition.

    Delegates to the condition's ``summarize()`` method when available, falls back to a stable callable name for
    callables, or ``str()`` for non-callable literals.
    """
    return _summarize(condition, str)


def _strip_outer_parens(s: str) -> str:
    """Strip balanced outer parentheses from a summary string.

    Only strips when the opening ``(`` at index 0 is matched by the closing ``)`` at the final index — i.e. the
    parens wrap the entire string.  Unbalanced or non-wrapping parens are left untouched.
    """
    if len(s) < 2 or s[0] != "(" or s[-1] != ")":
        return s
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and i < len(s) - 1:
            return s
    return s[1:-1]


def summarize_top_level(predicate: "Predicate") -> str:
    """Return a human-readable summary suitable for display as a top-level label.

    Calls ``summarize()`` on the predicate, then strips balanced outer parentheses so top-level combinators don't
    produce redundant wrapping.
    """
    return _strip_outer_parens(_summarize_predicate(predicate))


@dataclass(frozen=True)
class _PredicateCombinator(_PredicateOps):
    """Base for combinators that wrap a tuple of predicates.

    Provides the shared ``ensure_iterable`` constructor that flattens a single predicate
    or a (possibly nested) collection of predicates into the combinator's tuple form.
    """

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Sequence[Predicate]") -> Self:
        return cls(ensure_tuple(where))


@dataclass(frozen=True)
class AllOf(_PredicateCombinator):
    """Predicate that evaluates to True if all of the contained predicates evaluate to True."""

    def __call__(self, value: "AnyEvent") -> bool:
        """Return True if every contained predicate matches ``value``; an empty ``AllOf`` matches everything."""
        return all(p(value) for p in self.predicates)

    def summarize(self) -> str:
        """Describe the combination, which matches only when every contained predicate matches.

        Returns:
            Each contained predicate's summary joined with ``" and "``, wrapped in parentheses when there are
            two or more, e.g. ``"(domain light and state changed)"``.
        """
        joined = " and ".join(_summarize_predicate(p) for p in self.predicates)
        if len(self.predicates) >= 2:
            return f"({joined})"
        return joined


def flatten_all_of(predicate: "Predicate | None") -> tuple["Predicate", ...]:
    """Return the conjuncts of ``predicate``: the children of a top-level ``AllOf``, nested ``AllOf``s flattened.

    Any other predicate (including ``AnyOf`` and ``Not``) is a single conjunct, and ``None`` has none. Evaluating
    the conjuncts in order and stopping at the first false one is the same test as calling ``predicate``.
    """
    if predicate is None:
        return ()
    if isinstance(predicate, AllOf):
        return tuple(child for nested in predicate.predicates for child in flatten_all_of(nested))
    return (predicate,)


@dataclass(frozen=True)
class AnyOf(_PredicateCombinator):
    """Predicate that evaluates to True if any of the contained predicates evaluate to True."""

    def __call__(self, event: "AnyEvent") -> bool:
        """Return True if any contained predicate matches ``event``; an empty ``AnyOf`` matches nothing."""
        return any(p(event) for p in self.predicates)

    def summarize(self) -> str:
        """Describe the combination, which matches when at least one contained predicate matches.

        Returns:
            Each contained predicate's summary joined with ``" or "``, wrapped in parentheses when there are
            two or more, e.g. ``"(entity light.kitchen or entity light.hall)"``.
        """
        joined = " or ".join(_summarize_predicate(p) for p in self.predicates)
        if len(self.predicates) >= 2:
            return f"({joined})"
        return joined


@dataclass(frozen=True)
class Not(_PredicateOps):
    """Negates the result of the predicate."""

    predicate: "Predicate"

    def __call__(self, value: "AnyEvent", /) -> bool:
        """Return the inverse of the wrapped predicate's result for ``value``."""
        return not self.predicate(value)

    def summarize(self) -> str:
        """Return the wrapped predicate's summary prefixed with ``"not "``, e.g. ``"not domain light"``."""
        return "not " + _summarize_predicate(self.predicate)
