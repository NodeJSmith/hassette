"""Predicates combine accessors and conditions to form reusable boolean functions.

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
import math
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from inspect import isawaitable
from logging import getLogger
from typing import Any, Generic, Self, TypeVar

from hassette.const import ANY_VALUE, MISSING_VALUE, NOT_PROVIDED
from hassette.types import ChangeType, ComparisonCondition, EventT
from hassette.types.types import WhereClause
from hassette.utils import date_utils
from hassette.utils.func_utils import callable_stable_name as callable_name
from hassette.utils.func_utils import is_async_callable
from hassette.utils.glob_utils import is_glob

from .accessors import (
    get_attr_new,
    get_attr_old,
    get_attr_old_new,
    get_domain,
    get_entity_id,
    get_path,
    get_service_data_key,
    get_state_object_new,
    get_state_value_new,
    get_state_value_old,
    get_state_value_old_new,
)
from .conditions import ARROW, Glob, Present
from .predicate_collections import ensure_tuple, is_predicate_collection

if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent
    from hassette.events import CallServiceEvent, Event, HassEvent
    from hassette.types import Predicate

V = TypeVar("V")
CombinatorT = TypeVar("CombinatorT", bound="_PredicateCombinator")

LOGGER = getLogger(__name__)


class _PredicateOps:
    """Adds ``&``, ``|``, and ``~`` composition to the predicate types in this module.

    ``a & b`` builds an `AllOf`, ``a | b`` builds an `AnyOf`, and ``~a`` builds a `Not`.
    The result is an ordinary predicate object, so it can be passed to ``where=`` or nested
    inside the explicit combinators.

    Chains flatten rather than nest: ``a & b & c`` produces ``AllOf((a, b, c))``, which keeps
    ``summarize()`` identical to the explicit form.

    ``AllOf``, ``AnyOf``, and ``Not`` are defined further down this module; the operators resolve
    them at call time, not at class-definition time.

    Examples:
        ```python
        P.StateTo("on") & P.DomainMatches("light")
        P.StateTo("on") | P.StateTo("unavailable")
        ~P.StateTo("off")
        ```
    """

    if typing.TYPE_CHECKING:
        # Type-checking only, with no runtime counterpart: every class mixing this in defines
        # its own __call__, and declaring the signature here lets type checkers treat `self`
        # as a Predicate when building the combinators below.
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

    Absorption is what flattens chains, and it applies to explicitly constructed combinators too:
    ``AllOf((a, b)) & c`` yields ``AllOf((a, b, c))``, not a nested pair. The two forms evaluate
    identically, so the grouping carries no meaning worth preserving.
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
        return self.fn(value)

    def summarize(self) -> str:
        """Return ``"custom condition"``; an arbitrary callable has no inspectable meaning."""
        return "custom condition"


def _summarize(obj: Any, non_callable_fallback: Callable[[Any], str]) -> str:
    """Return a human-readable summary of a predicate or condition.

    Delegates to the object's ``summarize()`` method when available, falls back to a
    stable callable name for callables, or to ``non_callable_fallback`` otherwise.
    """
    if hasattr(obj, "summarize"):
        return obj.summarize()  # pyright: ignore[reportAttributeAccessIssue]
    if callable(obj):
        return callable_name(obj)
    return non_callable_fallback(obj)


def _summarize_predicate(predicate: "Predicate") -> str:
    """Return a human-readable summary of a predicate.

    Delegates to the predicate's ``summarize()`` method when available,
    otherwise falls back to a stable callable name, or ``repr()`` for
    non-callable values.
    """
    return _summarize(predicate, repr)


def _summarize_condition(condition: Any) -> str:
    """Return a human-readable summary of a condition.

    Delegates to the condition's ``summarize()`` method when available,
    falls back to a stable callable name for callables, or ``str()``
    for non-callable literals.
    """
    return _summarize(condition, str)


def _strip_outer_parens(s: str) -> str:
    """Strip balanced outer parentheses from a summary string.

    Only strips when the opening ``(`` at index 0 is matched by the
    closing ``)`` at the final index — i.e. the parens wrap the entire
    string.  Unbalanced or non-wrapping parens are left untouched.
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

    Calls ``summarize()`` on the predicate, then strips balanced outer
    parentheses so top-level combinators don't produce redundant wrapping.
    """
    return _strip_outer_parens(_summarize_predicate(predicate))


def _glob_or_literal(value: str) -> "str | Glob":
    """Wrap ``value`` in a Glob condition if it contains glob syntax, else return it as-is."""
    return Glob(value) if is_glob(value) else value


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

    def __call__(self, value: "Event") -> bool:
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


@dataclass(frozen=True)
class AnyOf(_PredicateCombinator):
    """Predicate that evaluates to True if any of the contained predicates evaluate to True."""

    def __call__(self, event: "Event") -> bool:
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

    def __call__(self, value: "Event", /) -> bool:
        return not self.predicate(value)

    def summarize(self) -> str:
        """Return the wrapped predicate's summary prefixed with ``"not "``, e.g. ``"not domain light"``."""
        return "not " + _summarize_predicate(self.predicate)


@dataclass(frozen=True)
class ValueIs(_PredicateOps, Generic[EventT, V]):
    """Checks whether a value extracted from an event satisfies a condition.

    Args:
        source: Callable that extracts the value to compare from the event.
        condition: A literal or callable tested against the extracted value. If ANY_VALUE, always True.
    """

    source: Callable[[EventT], V]
    condition: "ChangeType" = ANY_VALUE

    def __call__(self, value: EventT, /) -> bool:
        if self.condition is ANY_VALUE:
            return True
        extracted = self.source(value)
        return compare_value(extracted, self.condition)

    def summarize(self) -> str:
        """Describe the check, which matches when the value extracted by ``source`` satisfies ``condition``.

        When ``condition`` is ``ANY_VALUE``, the predicate matches every event without calling ``source``.

        Returns:
            For a literal condition, ``"value is <condition> from <source>"``; for a condition object with
            its own ``summarize()`` (such as ``Glob``), ``"value <summary> from <source>"``, e.g.
            ``"value matches light.* from get_entity_id"``; for any other callable condition,
            ``"custom condition from <source>"``. ``<source>`` is the extractor's callable name.
            An ``ANY_VALUE`` condition renders as a literal, e.g. ``"value is <ANY_VALUE> from <source>"``.
        """
        source_name = callable_name(self.source)
        if callable(self.condition):
            if hasattr(self.condition, "summarize"):
                return f"value {_summarize_condition(self.condition)} from {source_name}"
            return f"custom condition from {source_name}"
        return f"value is {self.condition} from {source_name}"


@dataclass(frozen=True)
class DidChange(_PredicateOps, Generic[EventT]):
    """Predicate that is True when two extracted values differ.

    Typical use is an accessor that returns (old_value, new_value).
    """

    source: Callable[[EventT], tuple[Any, Any]]

    def __call__(self, value: EventT, /) -> bool:
        old_v, new_v = self.source(value)
        return old_v != new_v

    def summarize(self) -> str:
        """Return ``"changed"``; matches when the (old, new) pair extracted by ``source`` differs."""
        return "changed"


@dataclass(frozen=True)
class IsPresent(_PredicateOps):
    """Checks if a value extracted from an event is present (not MISSING_VALUE).

    This will generally be used when comparing state changes, where either the old or new state may be missing.

    """

    source: Callable[[Any], Any]

    def __call__(self, value: Any, /) -> bool:
        return self.source(value) is not MISSING_VALUE

    def summarize(self) -> str:
        """Return ``"is present"``; matches when the extracted value is not ``MISSING_VALUE``."""
        return "is present"


@dataclass(frozen=True)
class IsMissing(_PredicateOps):
    """Checks if a value extracted from an event is missing (MISSING_VALUE).

    This will generally be used when comparing state changes, where either the old or new state may be missing.

    """

    source: Callable[[Any], Any]

    def __call__(self, value: Any, /) -> bool:
        return self.source(value) is MISSING_VALUE

    def summarize(self) -> str:
        """Return ``"is missing"``; matches when the extracted value is ``MISSING_VALUE``."""
        return "is missing"


@dataclass(frozen=True)
class StateFrom(_PredicateOps):
    """Checks if a value extracted from a RawStateChangeEvent satisfies a condition on the 'old' value."""

    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        return ValueIs(source=get_state_value_old, condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"from <condition>"`` (e.g. ``"from off"``); matches on the old state value."""
        return f"from {_summarize_condition(self.condition)}"


@dataclass(frozen=True)
class StateTo(_PredicateOps):
    """Checks if a value extracted from a RawStateChangeEvent satisfies a condition on the 'new' value."""

    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        return ValueIs(source=get_state_value_new, condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"→ <condition>"`` (e.g. ``"→ on"``); matches on the new state value."""
        return f"{ARROW} {_summarize_condition(self.condition)}"


@dataclass(frozen=True)
class StateComparison(_PredicateOps):
    """Checks if a comparison between from_state and to_state satisfies a condition."""

    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if inspect.isclass(self.condition):
            LOGGER.warning("StateComparison was passed a class instead of an instance.", stacklevel=2)
            object.__setattr__(self, "condition", self.condition())

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        return self.condition(get_state_value_old(value), get_state_value_new(value))

    def summarize(self) -> str:
        """Return ``"state <condition>"`` (e.g. ``"state increased"``); compares old and new state."""
        return f"state {_summarize_condition(self.condition)}"


@dataclass(frozen=True)
class AttrFrom(_PredicateOps):
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str
    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        return ValueIs(source=get_attr_old(self.attr_name), condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"attr <attr_name> from <condition>"`` (e.g. ``"attr brightness from 0"``)."""
        return f"attr {self.attr_name} from {_summarize_condition(self.condition)}"


@dataclass(frozen=True)
class AttrTo(_PredicateOps):
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str
    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        return ValueIs(source=get_attr_new(self.attr_name), condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"attr <attr_name> → <condition>"`` (e.g. ``"attr brightness → 255"``)."""
        return f"attr {self.attr_name} {ARROW} {_summarize_condition(self.condition)}"


@dataclass(frozen=True)
class AttrComparison(_PredicateOps):
    """Checks if a comparison between from_attr and to_attr satisfies a condition."""

    attr_name: str
    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if inspect.isclass(self.condition):
            LOGGER.warning("AttrComparison was passed a class instead of an instance.", stacklevel=2)
            object.__setattr__(self, "condition", self.condition())

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        old_attr = get_attr_old(self.attr_name)(value)
        new_attr = get_attr_new(self.attr_name)(value)
        return self.condition(old_attr, new_attr)

    def summarize(self) -> str:
        """Return ``"attr <attr_name> <condition>"`` (e.g. ``"attr brightness increased"``)."""
        return f"attr {self.attr_name} {_summarize_condition(self.condition)}"


@dataclass(frozen=True)
class StateDidChange(_PredicateOps):
    """Checks if the state changed in a RawStateChangeEvent."""

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        return DidChange(get_state_value_old_new)(value)

    def summarize(self) -> str:
        """Return ``"state changed"``; matches when the old and new state values differ."""
        return "state changed"


@dataclass(frozen=True)
class AttrDidChange(_PredicateOps):
    """Checks if a specific attribute changed in a RawStateChangeEvent.

    When ``old_state`` is None, the attribute is treated as having changed
    if it is present on ``new_state``.  This applies to synthetic
    immediate-fire/bootstrap events, the cancel handler's old_state stripping
    in DurationTimer, and real state-change events where there is no prior
    state yet (first observation / first-time state set).
    """

    attr_name: str

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        # old_state=None arises in two paths: (1) synthetic immediate-fire events
        # and (2) the cancel handler's old_state stripping in DurationTimer.
        # Both need "attribute present = changed" semantics — but only if the
        # attribute actually exists on new_state.
        if value.payload.data.old_state is None:
            return get_attr_new(self.attr_name)(value) is not MISSING_VALUE
        return DidChange(get_attr_old_new(self.attr_name))(value)

    def summarize(self) -> str:
        """Describe the check, which matches when attribute ``attr_name`` differs between the old and new state.

        When ``old_state`` is None, it matches if the attribute is present on ``new_state``.

        Returns:
            ``"attr <attr_name> changed"``, e.g. ``"attr brightness changed"``.
        """
        return f"attr {self.attr_name} changed"


@dataclass(frozen=True)
class EventEntityFresh(_PredicateOps):
    """Checks that an ``event.*`` entity's state timestamp is within ``max_age`` seconds of its ``last_changed``.

    Home Assistant ``event`` entities (buttons, remotes) store the time of their last event as
    their state value. When HA restarts it restores that state and broadcasts it as a new
    ``state_changed`` event, so an unguarded button listener re-runs on every restart. A real
    press writes its timestamp and ``last_changed`` together; a restart replay pairs the old
    timestamp with a ``last_changed`` set at restart. Both values come from Home Assistant, so
    clock skew with the Hassette host and dispatch latency don't affect the result, and a
    ``duration=`` hold recheck of the cached state still passes.

    Fails open: a missing ``new_state`` or a state value or ``last_changed`` that is not an
    ISO 8601 timestamp (``unknown``, ``unavailable``) counts as fresh, so a real press is
    never dropped.

    Examples:
        ```python
        await self.bus.on_state_change(
            "event.hallway_button",
            handler=self.on_press,
            where=P.EventEntityFresh(max_age=10),
            name="hallway_button",
        )
        ```
    """

    max_age: float
    """Maximum seconds between the event timestamp and ``last_changed`` for the event to pass."""

    def __post_init__(self) -> None:
        if self.max_age <= 0 or math.isnan(self.max_age):
            raise ValueError(f"max_age must be positive, got {self.max_age!r}")

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        new_state = get_state_object_new(value)
        if new_state is None:
            return True
        fired = date_utils.try_parse_iso(new_state.get("state"))
        changed = date_utils.try_parse_iso(new_state.get("last_changed"))
        if fired is None or changed is None:
            return True
        return (changed.to_instant() - fired.to_instant()).total("seconds") <= self.max_age

    def summarize(self) -> str:
        """Return ``"event within <max_age>s"`` (e.g. ``"event within 10s"``)."""
        return f"event within {self.max_age:g}s"


@dataclass(frozen=True)
class DomainMatches(_PredicateOps):
    """Checks if the event domain matches a specific value."""

    domain: str

    def __call__(self, value: "HassEvent", /) -> bool:
        return ValueIs(source=get_domain, condition=_glob_or_literal(self.domain))(value)

    def summarize(self) -> str:
        """Return ``"domain <domain>"`` (e.g. ``"domain light"``); glob patterns are allowed."""
        return f"domain {self.domain}"

    def __repr__(self) -> str:
        return f"DomainMatches(domain={self.domain!r})"


@dataclass(frozen=True)
class EntityMatches(_PredicateOps):
    """Checks if the event entity_id matches a specific value."""

    entity_id: str

    def __call__(self, value: "HassEvent", /) -> bool:
        return ValueIs(source=get_entity_id, condition=_glob_or_literal(self.entity_id))(value)

    def summarize(self) -> str:
        """Return ``"entity <entity_id>"`` (e.g. ``"entity light.*"``); glob patterns are allowed."""
        return f"entity {self.entity_id}"

    def __repr__(self) -> str:
        return f"EntityMatches(entity_id={self.entity_id!r})"


@dataclass(frozen=True)
class ServiceMatches(_PredicateOps):
    """Checks if the event service matches a specific value."""

    service: str

    def __call__(self, value: "HassEvent", /) -> bool:
        return ValueIs(source=get_path("payload.data.service"), condition=_glob_or_literal(self.service))(value)

    def summarize(self) -> str:
        """Return ``"service <service>"`` (e.g. ``"service turn_on"``); glob patterns are allowed."""
        return f"service {self.service}"

    def __repr__(self) -> str:
        return f"ServiceMatches(service={self.service!r})"


@dataclass(frozen=True)
class ServiceDataWhere(_PredicateOps):
    """Predicate that applies a mapping of service_data conditions to a CallServiceEvent.

    Examples:
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

    def __call__(self, value: "CallServiceEvent", /) -> bool:
        return all(p(value) for p in self._predicates)

    def summarize(self) -> str:
        """Describe the check, which matches when every key in ``spec`` satisfies its condition in the service data.

        Returns:
            Comma-separated ``"<key> = <condition>"`` pairs, e.g. ``"entity_id = light.*, brightness = 200"``.
        """

        def _fmt(v: Any) -> str:
            if callable(v):
                return _summarize_condition(v) if hasattr(v, "summarize") else callable_name(v)
            return str(v)

        parts = [f"{k} = {_fmt(v)}" for k, v in self.spec.items()]
        return ", ".join(parts)

    @classmethod
    def from_kwargs(cls, *, auto_glob: bool = True, **spec: "ChangeType") -> "ServiceDataWhere":
        """Ergonomic constructor for literal kwargs.

        Example:
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

    Note:
        This function does not handle collections any differently than other literals — it compares
        them for equality only. Use specific conditions like IsIn/NotIn/Intersects for collection membership tests.
    """
    if condition is NOT_PROVIDED:
        return True

    if not callable(condition):
        return actual == condition

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
