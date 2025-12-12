"""
Predicates combine accessors and conditions to form reusable boolean functions.

A predicate takes a ``source`` callable that extracts a value from an event, and a ``condition`` that
tests the extracted value. The condition may be a literal value, a callable, or a more complex condition object.
Conditions can be composed of other conditions to form complex logic.

Examples:
    Basic value comparison

    ```python
    ValueIs(source=get_entity_id, condition="light.kitchen")
    ```

    With a callable condition

    ```python
    def is_kitchen_light(entity_id: str) -> bool:
        return entity_id == "light.kitchen"

    ValueIs(source=get_entity_id, condition=is_kitchen_light)
    ```

    With a condition object

    ```python
    ValueIs(
        source=get_entity_id,
        condition=C.IsIn(collection=["light.kitchen", "light.living"]),
    )
    ```

    Combining multiple predicates

    ```python
    P.AllOf(predicates=[
        P.DomainMatches("light"),
        P.EntityMatches("light.kitchen"),
        P.StateTo("on"),
    ])
    ```
"""

import inspect
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from inspect import isawaitable, iscoroutinefunction
from logging import getLogger
from typing import Any, Generic, TypeGuard, TypeVar

from boltons.iterutils import is_collection

from hassette.const import ANY_VALUE, MISSING_VALUE, NOT_PROVIDED
from hassette.events.base import EventT
from hassette.types import ChangeType, ComparisonCondition
from hassette.utils.glob_utils import is_glob

from .accessors import (
    get_attr_new,
    get_attr_old,
    get_attr_old_new,
    get_domain,
    get_entity_id,
    get_path,
    get_service_data_key,
    get_state_value_new,
    get_state_value_old,
    get_state_value_old_new,
)
from .conditions import Glob, Present

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.types import ChangeType, Predicate


if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent
    from hassette.events import CallServiceEvent, Event, HassEvent
    from hassette.types import Predicate

V = TypeVar("V")

LOGGER = getLogger(__name__)


@dataclass(frozen=True)
class Guard(typing.Generic[EventT]):
    """Wraps a predicate function to be used in combinators.

    Allows for passing any callable as a predicate. Generic over EventT to allow type checkers to understand the
    expected event type.
    """

    fn: "Predicate[EventT]"

    def __call__(self, event: "EventT") -> bool:
        return self.fn(event)


@dataclass(frozen=True)
class AllOf:
    """Predicate that evaluates to True if all of the contained predicates evaluate to True."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    def __call__(self, event: "Event") -> bool:
        return all(p(event) for p in self.predicates)

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Sequence[Predicate] | list[Predicate]") -> "AllOf":
        return cls(ensure_tuple(where))


@dataclass(frozen=True)
class AnyOf:
    """Predicate that evaluates to True if any of the contained predicates evaluate to True."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    def __call__(self, event: "Event") -> bool:
        return any(p(event) for p in self.predicates)

    @classmethod
    def ensure_iterable(cls, where: "Predicate | Sequence[Predicate]") -> "AnyOf":
        return cls(ensure_tuple(where))


@dataclass(frozen=True)
class Not:
    """Negates the result of the predicate."""

    predicate: "Predicate"

    def __call__(self, event: "Event") -> bool:
        return not self.predicate(event)


@dataclass(frozen=True)
class ValueIs(Generic[EventT, V]):
    """Checks whether a value extracted from an event satisfies a condition.

    Args:
        source: Callable that extracts the value to compare from the event.
        condition: A literal or callable tested against the extracted value. If ANY_VALUE, always True.
    """

    source: Callable[[EventT], V]
    condition: "ChangeType" = ANY_VALUE

    def __call__(self, event: EventT) -> bool:
        if self.condition is ANY_VALUE:
            return True
        value = self.source(event)
        return compare_value(value, self.condition)


@dataclass(frozen=True)
class DidChange(Generic[EventT]):
    """Predicate that is True when two extracted values differ.

    Typical use is an accessor that returns (old_value, new_value).
    """

    source: Callable[[EventT], tuple[Any, Any]]

    def __call__(self, event: EventT) -> bool:
        old_v, new_v = self.source(event)
        return old_v != new_v


@dataclass(frozen=True)
class IsPresent:
    """Checks if a value extracted from an event is present (not MISSING_VALUE).

    This will generally be used when comparing state changes, where either the old or new state may be missing.

    """

    source: Callable[[Any], Any]

    def __call__(self, event) -> bool:
        return self.source(event) is not MISSING_VALUE


@dataclass(frozen=True)
class IsMissing:
    """Checks if a value extracted from an event is missing (MISSING_VALUE).

    This will generally be used when comparing state changes, where either the old or new state may be missing.

    """

    source: Callable[[Any], Any]

    def __call__(self, event) -> bool:
        return self.source(event) is MISSING_VALUE


@dataclass(frozen=True)
class StateFrom:
    """Checks if a value extracted from a RawStateChangeEvent satisfies a condition on the 'old' value."""

    condition: "ChangeType"

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return ValueIs(source=get_state_value_old, condition=self.condition)(event)


@dataclass(frozen=True)
class StateTo:
    """Checks if a value extracted from a RawStateChangeEvent satisfies a condition on the 'new' value."""

    condition: "ChangeType"

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return ValueIs(source=get_state_value_new, condition=self.condition)(event)


@dataclass(frozen=True)
class StateComparison:
    """Checks if a comparison between from_state and to_state satisfies a condition."""

    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if inspect.isclass(self.condition):
            LOGGER.warning("StateComparison was passed a class instead of an instance.", stacklevel=2)
            object.__setattr__(self, "condition", self.condition())

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return self.condition(get_state_value_old(event), get_state_value_new(event))


@dataclass(frozen=True)
class AttrFrom:
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str
    condition: "ChangeType"

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return ValueIs(source=get_attr_old(self.attr_name), condition=self.condition)(event)


@dataclass(frozen=True)
class AttrTo:
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str
    condition: "ChangeType"

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return ValueIs(source=get_attr_new(self.attr_name), condition=self.condition)(event)


@dataclass(frozen=True)
class AttrComparison:
    """Checks if a comparison between from_attr and to_attr satisfies a condition."""

    attr_name: str
    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if inspect.isclass(self.condition):
            LOGGER.warning("AttrComparison was passed a class instead of an instance.", stacklevel=2)
            object.__setattr__(self, "condition", self.condition())

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        old_attr = get_attr_old(self.attr_name)(event)
        new_attr = get_attr_new(self.attr_name)(event)
        return self.condition(old_attr, new_attr)


@dataclass(frozen=True)
class StateDidChange:
    """Checks if the state changed in a RawStateChangeEvent."""

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return DidChange(get_state_value_old_new)(event)


@dataclass(frozen=True)
class AttrDidChange:
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str

    def __call__(self, event: "RawStateChangeEvent") -> bool:
        return DidChange(get_attr_old_new(self.attr_name))(event)


@dataclass(frozen=True)
class DomainMatches:
    """Checks if the event domain matches a specific value."""

    domain: str

    def __call__(self, event: "HassEvent") -> bool:
        cond = Glob(self.domain) if is_glob(self.domain) else self.domain
        return ValueIs(source=get_domain, condition=cond)(event)

    def __repr__(self) -> str:
        return f"DomainMatches(domain={self.domain!r})"


@dataclass(frozen=True)
class EntityMatches:
    """Checks if the event entity_id matches a specific value."""

    entity_id: str

    def __call__(self, event: "HassEvent") -> bool:
        cond = Glob(self.entity_id) if is_glob(self.entity_id) else self.entity_id
        return ValueIs(source=get_entity_id, condition=cond)(event)

    def __repr__(self) -> str:
        return f"EntityMatches(entity_id={self.entity_id!r})"


@dataclass(frozen=True)
class ServiceMatches:
    """Checks if the event service matches a specific value."""

    service: str

    def __call__(self, event: "HassEvent") -> bool:
        cond = Glob(self.service) if is_glob(self.service) else self.service
        return ValueIs(source=get_path("payload.data.service"), condition=cond)(event)

    def __repr__(self) -> str:
        return f"ServiceMatches(service={self.service!r})"


@dataclass(frozen=True)
class ServiceDataWhere:
    """Predicate that applies a mapping of service_data conditions to a CallServiceEvent.

    Examples
    --------
    Exact matches only

        ServiceDataWhere({"entity_id": "light.kitchen", "transition": 1})

    With a callable condition

        ServiceDataWhere({"brightness": lambda v: isinstance(v, int) and v >= 150})

    With globs (auto-wrapped)

        ServiceDataWhere({"entity_id": "light.*"})

    Using conditions

        ServiceDataWhere({"entity_id": Glob("switch.*")})

        ServiceDataWhere({"brightness": IsIn([100, 200, 255])})
    """

    spec: Mapping[str, "ChangeType"]
    auto_glob: bool = True
    _predicates: tuple["Predicate[CallServiceEvent]", ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from hassette.types import ChangeType

        preds: list[Predicate[CallServiceEvent]] = []

        for k, cond in self.spec.items():
            source = get_service_data_key(k)
            c: ChangeType
            # presence check
            if cond is ANY_VALUE:
                c = Present()
            # auto-glob wrapping
            elif self.auto_glob and isinstance(cond, str) and is_glob(cond):
                c = Glob(cond)
            # literal or callable condition
            else:
                c = cond
            preds.append(ValueIs(source=source, condition=c))

        object.__setattr__(self, "_predicates", tuple(preds))

    def __call__(self, event: "CallServiceEvent") -> bool:
        return all(p(event) for p in self._predicates)

    @classmethod
    def from_kwargs(cls, *, auto_glob: bool = True, **spec: "ChangeType") -> "ServiceDataWhere":
        """Ergonomic constructor for literal kwargs.

        Example
        -------
        >>> ServiceDataWhere.from_kwargs(entity_id="light.*", brightness=200)
        """
        return cls(spec=spec, auto_glob=auto_glob)


def compare_value(actual: Any, condition: "ChangeType") -> bool:
    """Compare an actual value against a condition.

    Args:
        actual: The actual value to compare.
        condition: The condition to compare against. Can be a literal value or a callable.

    Returns:
        True if the actual value matches the condition, False otherwise.

    Behavior:
        - If condition is NOT_PROVIDED, treat as 'no constraint' (True).
        - If condition is a non-callable, compare for equality only.
        - If condition is a callable, call and ensure bool.
        - Async/coroutine predicates are explicitly disallowed (raise).

    Warnings:
        - This function does not handle collections any differently than other literals, it will compare
            them for equality only. Use specific conditions like IsIn/NotIn/Intersects for collection membership tests.
    """
    if condition is NOT_PROVIDED:
        return True

    if not callable(condition):
        return actual == condition

    # Disallow async predicates to keep filters pure/fast.
    if iscoroutinefunction(condition):
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


def ensure_tuple(where: "Predicate | Sequence[Predicate]") -> tuple["Predicate", ...]:
    """Ensure the 'where' is a flat tuple of predicates, flattening *only* predicate collections.

    Recurses into list/tuple/set/frozenset; leaves Mapping, strings/bytes, and callables intact.
    """
    if is_predicate_collection(where):
        out: list[Predicate] = []
        # mypy/pyright: guarded by _is_predicate_collection, so safe to iterate
        for item in typing.cast("Sequence[Predicate | Sequence[Predicate]]", where):
            out.extend(ensure_tuple(item))
        return tuple(out)

    return (typing.cast("Predicate", where),)


def is_predicate_collection(obj: Any) -> TypeGuard[Sequence["Predicate"]]:
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
    if is_predicate_collection(where):
        return AllOf.ensure_iterable(where)

    # help the type checker know that `where` is not an Sequence here
    if typing.TYPE_CHECKING:
        assert not isinstance(where, Sequence)

    return where  # single predicate or mapping gets handled by the caller
