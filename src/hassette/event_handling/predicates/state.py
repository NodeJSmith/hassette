"""State and attribute predicates for state-change events."""

import math
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from hassette.const import ANY_VALUE, MISSING_VALUE
from hassette.event_handling.accessors import (
    get_attr_new,
    get_attr_old,
    get_attr_old_new,
    get_state_object_new,
    get_state_value_new,
    get_state_value_old,
    get_state_value_old_new,
)
from hassette.event_handling.conditions import ARROW
from hassette.types import ChangeType, ComparisonCondition, EventT
from hassette.utils import date_utils
from hassette.utils.func_utils import callable_stable_name as callable_name

from .combinators import _PredicateOps, summarize_condition
from .comparison import compare_value

if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent

V = TypeVar("V")


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
        """Return True if the value ``source`` extracts satisfies ``condition``; ANY_VALUE always matches."""
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
                return f"value {summarize_condition(self.condition)} from {source_name}"
            return f"custom condition from {source_name}"
        return f"value is {self.condition} from {source_name}"


@dataclass(frozen=True)
class DidChange(_PredicateOps, Generic[EventT]):
    """Predicate that is True when two extracted values differ.

    Typical use is an accessor that returns (old_value, new_value).
    """

    source: Callable[[EventT], tuple[Any, Any]]

    def __call__(self, value: EventT, /) -> bool:
        """Return True if the (old, new) pair that ``source`` extracts from ``value`` holds two unequal values."""
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
        """Return True if ``source`` extracts something other than ``MISSING_VALUE`` from ``value``."""
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
        """Return True if ``source`` extracts ``MISSING_VALUE`` from ``value``."""
        return self.source(value) is MISSING_VALUE

    def summarize(self) -> str:
        """Return ``"is missing"``; matches when the extracted value is ``MISSING_VALUE``."""
        return "is missing"


@dataclass(frozen=True)
class StateFrom(_PredicateOps):
    """Checks if a value extracted from a RawStateChangeEvent satisfies a condition on the 'old' value."""

    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if the event's old state value satisfies ``condition``."""
        return ValueIs(source=get_state_value_old, condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"from <condition>"`` (e.g. ``"from off"``); matches on the old state value."""
        return f"from {summarize_condition(self.condition)}"


@dataclass(frozen=True)
class StateTo(_PredicateOps):
    """Checks if a value extracted from a RawStateChangeEvent satisfies a condition on the 'new' value."""

    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if the event's new state value satisfies ``condition``."""
        return ValueIs(source=get_state_value_new, condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"→ <condition>"`` (e.g. ``"→ on"``); matches on the new state value."""
        return f"{ARROW} {summarize_condition(self.condition)}"


@dataclass(frozen=True)
class StateComparison(_PredicateOps):
    """Checks if a comparison between from_state and to_state satisfies a condition."""

    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if isinstance(self.condition, type):
            name = self.condition.__name__
            raise TypeError(f"StateComparison was passed the class {name}; pass an instance instead, e.g. {name}().")

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return the result of calling ``condition`` with the event's old and new state values."""
        return self.condition(get_state_value_old(value), get_state_value_new(value))

    def summarize(self) -> str:
        """Return ``"state <condition>"`` (e.g. ``"state increased"``); compares old and new state."""
        return f"state {summarize_condition(self.condition)}"


@dataclass(frozen=True)
class AttrFrom(_PredicateOps):
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str
    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if attribute ``attr_name`` on the event's old state satisfies ``condition``."""
        return ValueIs(source=get_attr_old(self.attr_name), condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"attr <attr_name> from <condition>"`` (e.g. ``"attr brightness from 0"``)."""
        return f"attr {self.attr_name} from {summarize_condition(self.condition)}"


@dataclass(frozen=True)
class AttrTo(_PredicateOps):
    """Checks if a specific attribute changed in a RawStateChangeEvent."""

    attr_name: str
    condition: "ChangeType"

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if attribute ``attr_name`` on the event's new state satisfies ``condition``."""
        return ValueIs(source=get_attr_new(self.attr_name), condition=self.condition)(value)

    def summarize(self) -> str:
        """Return ``"attr <attr_name> → <condition>"`` (e.g. ``"attr brightness → 255"``)."""
        return f"attr {self.attr_name} {ARROW} {summarize_condition(self.condition)}"


@dataclass(frozen=True)
class AttrComparison(_PredicateOps):
    """Checks if a comparison between from_attr and to_attr satisfies a condition."""

    attr_name: str
    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if isinstance(self.condition, type):
            name = self.condition.__name__
            raise TypeError(f"AttrComparison was passed the class {name}; pass an instance instead, e.g. {name}().")

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return the result of calling ``condition`` with attribute ``attr_name``'s old and new values."""
        old_attr = get_attr_old(self.attr_name)(value)
        new_attr = get_attr_new(self.attr_name)(value)
        return self.condition(old_attr, new_attr)

    def summarize(self) -> str:
        """Return ``"attr <attr_name> <condition>"`` (e.g. ``"attr brightness increased"``)."""
        return f"attr {self.attr_name} {summarize_condition(self.condition)}"


@dataclass(frozen=True)
class StateDidChange(_PredicateOps):
    """Checks if the state changed in a RawStateChangeEvent."""

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if the event's old and new state values differ."""
        return DidChange(get_state_value_old_new)(value)

    def summarize(self) -> str:
        """Return ``"state changed"``; matches when the old and new state values differ."""
        return "state changed"


@dataclass(frozen=True)
class AttrDidChange(_PredicateOps):
    """Checks if a specific attribute changed in a RawStateChangeEvent.

    When ``old_state`` is None, the attribute is treated as having changed if it is present on ``new_state``.  This
    applies to synthetic immediate-fire/bootstrap events, the cancel handler's old_state stripping in DurationTimer,
    and real state-change events where there is no prior state yet (first observation / first-time state set).
    """

    attr_name: str

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if ``attr_name`` differs between old and new state; with no old state, if it exists on new."""
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
    """Checks that a button entity's state timestamp is within ``max_age`` seconds of its ``last_changed``.

    Home Assistant ``event`` entities (buttons, remotes) and ``input_button`` helpers store the time of their last event
    as their state value. When HA restarts it restores that state and broadcasts it as a new ``state_changed`` event, so
    an unguarded button listener re-runs on every restart. A real press writes its timestamp and ``last_changed``
    together; a restart replay pairs the old timestamp with a ``last_changed`` set at restart. Both values come from
    Home Assistant, so clock skew with the Hassette host and dispatch latency don't affect the result, and a
    ``duration=`` hold recheck of the cached state still passes.

    Fails open: a missing ``new_state`` or a state value or ``last_changed`` that is not an ISO 8601 timestamp
    (``unknown``, ``unavailable``) counts as fresh, so a real press is never dropped. A handler that acts without
    checking anything else, as an ``input_button`` handler usually does, also runs on those states during a restart
    and when the entity is removed. Compose the guard with ``P.IsPresent`` and ``~P.StateTo`` to drop them, as the
    second example shows. A restart within ``max_age`` of the last press still passes as a press.

    Examples:
        ```python
        await self.bus.on_state_change(
            "event.hallway_button",
            handler=self.on_press,
            where=P.EventEntityFresh(max_age=10),
            name="hallway_button",
        )

        await self.bus.on_state_change(
            "input_button.naptime",
            handler=self.on_press,
            where=(
                P.EventEntityFresh(max_age=10)
                & P.IsPresent(A.get_state_value_new)
                & ~P.StateTo("unavailable")
                & ~P.StateTo("unknown")
            ),
            name="naptime_button",
        )
        ```
    """

    max_age: float
    """Maximum seconds between the event timestamp and ``last_changed`` for the event to pass."""

    def __post_init__(self) -> None:
        if self.max_age <= 0 or math.isnan(self.max_age):
            raise ValueError(f"max_age must be positive, got {self.max_age!r}")

    def __call__(self, value: "RawStateChangeEvent", /) -> bool:
        """Return True if the event fired within ``max_age`` seconds of ``last_changed``, or if either is unparsable."""
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
