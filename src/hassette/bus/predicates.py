"""
Predicates combine accessors and conditions to form reusable boolean functions.

A predicate takes a ``source`` callable that extracts a value from an event, and a ``condition`` that
tests the extracted value. The condition may be a literal value, a callable, or a more complex condition object.
Conditions can be composed of other conditions to form complex logic.

Examples
--------

**Basic value comparison**

.. code-block:: python

    ValueIs(source=get_entity_id, condition="light.kitchen")

**With a callable condition**

.. code-block:: python

    def is_kitchen_light(entity_id: str) -> bool:
        return entity_id == "light.kitchen"

    ValueIs(source=get_entity_id, condition=is_kitchen_light)

**With a condition object**

.. code-block:: python

    ValueIs(
        source=get_entity_id,
        condition=C.IsIn(collection=["light.kitchen", "light.living"]),
    )

**Combining multiple predicates**

.. code-block:: python

    P.AllOf(predicates=[
        P.DomainMatches("light"),
        P.EntityMatches("light.kitchen"),
        P.StateTo("on"),
    ])
"""

import inspect
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, Generic, TypeVar

from hassette.const import MISSING_VALUE, NOT_PROVIDED
from hassette.events import CallServiceEvent
from hassette.events.base import EventT
from hassette.models.states import StateT
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
from .utils import compare_value, ensure_tuple

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

    from hassette import StateChangeEvent
    from hassette.events import Event, HassEvent
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
    """Predicate that checks whether a value extracted from an event satisfies a condition.

    Args:
        source: Callable that extracts the value to compare from the event.
        condition: A literal or callable tested against the extracted value. If NOT_PROVIDED, always True.
    """

    source: Callable[[EventT], V]
    condition: ChangeType = NOT_PROVIDED

    def __call__(self, event: EventT) -> bool:
        if self.condition is NOT_PROVIDED:
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
    """Predicate that checks if a value extracted from an event is present (not MISSING_VALUE).

    This will generally be used when comparing state changes, where either the old or new state may be missing.

    """

    source: Callable[[Any], Any]

    def __call__(self, event) -> bool:
        return self.source(event) is not MISSING_VALUE


@dataclass(frozen=True)
class IsMissing:
    """Predicate that checks if a value extracted from an event is missing (MISSING_VALUE).

    This will generally be used when comparing state changes, where either the old or new state may be missing.

    """

    source: Callable[[Any], Any]

    def __call__(self, event) -> bool:
        return self.source(event) is MISSING_VALUE


@dataclass(frozen=True)
class StateFrom(Generic[StateT]):
    """Predicate that checks if a value extracted from a StateChangeEvent satisfies a condition on the 'old' value."""

    condition: ChangeType

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return ValueIs(source=get_state_value_old, condition=self.condition)(event)


@dataclass(frozen=True)
class StateTo(Generic[StateT]):
    """Predicate that checks if a value extracted from a StateChangeEvent satisfies a condition on the 'new' value."""

    condition: ChangeType

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return ValueIs(source=get_state_value_new, condition=self.condition)(event)


@dataclass(frozen=True)
class StateComparison(Generic[StateT]):
    """Predicate that checks if a comparison between from_state and to_state satisfies a condition."""

    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if inspect.isclass(self.condition):
            LOGGER.warning("StateComparison was passed a class instead of an instance.", stacklevel=2)
            object.__setattr__(self, "condition", self.condition())

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return self.condition(get_state_value_old(event), get_state_value_new(event))


@dataclass(frozen=True)
class AttrFrom(Generic[StateT]):
    """Predicate that checks if a specific attribute changed in a StateChangeEvent."""

    attr_name: str
    condition: ChangeType

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return ValueIs(source=get_attr_old(self.attr_name), condition=self.condition)(event)


@dataclass(frozen=True)
class AttrTo(Generic[StateT]):
    """Predicate that checks if a specific attribute changed in a StateChangeEvent."""

    attr_name: str
    condition: ChangeType

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return ValueIs(source=get_attr_new(self.attr_name), condition=self.condition)(event)


@dataclass(frozen=True)
class AttrComparison(Generic[StateT]):
    """Predicate that checks if a comparison between from_attr and to_attr satisfies a condition."""

    attr_name: str
    condition: ComparisonCondition

    def __post_init__(self) -> None:
        if inspect.isclass(self.condition):
            LOGGER.warning("AttrComparison was passed a class instead of an instance.", stacklevel=2)
            object.__setattr__(self, "condition", self.condition())

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        old_attr = get_attr_old(self.attr_name)(event)
        new_attr = get_attr_new(self.attr_name)(event)
        return self.condition(old_attr, new_attr)


@dataclass(frozen=True)
class StateDidChange(Generic[StateT]):
    """Predicate that checks if the state changed in a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return DidChange(get_state_value_old_new)(event)


@dataclass(frozen=True)
class AttrDidChange(Generic[StateT]):
    """Predicate that checks if a specific attribute changed in a StateChangeEvent."""

    attr_name: str

    def __call__(self, event: "StateChangeEvent[StateT]") -> bool:
        return DidChange(get_attr_old_new(self.attr_name))(event)


@dataclass(frozen=True)
class DomainMatches:
    """Predicate that checks if the event domain matches a specific value."""

    domain: str

    def __call__(self, event: "HassEvent") -> bool:
        cond = Glob(self.domain) if is_glob(self.domain) else self.domain
        return ValueIs(source=get_domain, condition=cond)(event)

    def __repr__(self) -> str:
        return f"DomainMatches(domain={self.domain!r})"


@dataclass(frozen=True)
class EntityMatches:
    """Predicate that checks if the event entity_id matches a specific value."""

    entity_id: str

    def __call__(self, event: "HassEvent") -> bool:
        cond = Glob(self.entity_id) if is_glob(self.entity_id) else self.entity_id
        return ValueIs(source=get_entity_id, condition=cond)(event)

    def __repr__(self) -> str:
        return f"EntityMatches(entity_id={self.entity_id!r})"


@dataclass(frozen=True)
class ServiceMatches:
    """Predicate that checks if the event service matches a specific value."""

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
    Exact matches only::

        ServiceDataWhere({"entity_id": "light.kitchen", "transition": 1})

    With a callable condition::

        ServiceDataWhere({"brightness": lambda v: isinstance(v, int) and v >= 150})

    With globs (auto-wrapped)::

        ServiceDataWhere({"entity_id": "light.*"})

    Using conditions::

        ServiceDataWhere({"entity_id": Glob("switch.*")})

        ServiceDataWhere({"brightness": IsIn([100, 200, 255])})
    """

    spec: Mapping[str, ChangeType]
    auto_glob: bool = True
    _predicates: tuple["Predicate[CallServiceEvent]", ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        preds: list[Predicate[CallServiceEvent]] = []

        for k, cond in self.spec.items():
            source = get_service_data_key(k)
            # presence check
            if cond is NOT_PROVIDED:
                c: ChangeType = Present()
            # auto-glob wrapping
            elif self.auto_glob and isinstance(cond, str) and is_glob(cond):
                c = Glob(cond)
            # literal or callable condition
            else:
                c = cond
            preds.append(ValueIs(source=source, condition=c))

        object.__setattr__(self, "_predicates", tuple(preds))

    def __call__(self, event: CallServiceEvent) -> bool:
        return all(p(event) for p in self._predicates)

    @classmethod
    def from_kwargs(cls, *, auto_glob: bool = True, **spec: ChangeType) -> "ServiceDataWhere":
        """Ergonomic constructor for literal kwargs.

        Example
        -------
        >>> ServiceDataWhere.from_kwargs(entity_id="light.*", brightness=200)
        """
        return cls(spec=spec, auto_glob=auto_glob)
