"""Event-matching predicates: domain, entity, service, and service data."""

import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hassette.const import ANY_VALUE
from hassette.event_handling.accessors import get_domain, get_entity_id, get_path, get_service_data_key
from hassette.event_handling.conditions import Glob, Present
from hassette.utils.func_utils import callable_stable_name as callable_name
from hassette.utils.glob_utils import is_glob

from .combinators import _PredicateOps, summarize_condition
from .state import ValueIs

if typing.TYPE_CHECKING:
    from hassette.events import CallServiceEvent, HassEvent
    from hassette.types import ChangeType, Predicate


def _glob_or_literal(value: str) -> "str | Glob":
    """Wrap ``value`` in a Glob condition if it contains glob syntax, else return it as-is."""
    return Glob(value) if is_glob(value) else value


@dataclass(frozen=True)
class DomainMatches(_PredicateOps):
    """Checks if the event domain matches a specific value."""

    domain: str

    def __call__(self, value: "HassEvent", /) -> bool:
        """Return True if the event's domain matches ``domain``, as a glob when it contains glob syntax."""
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
        """Return True if the event's entity_id matches ``entity_id``, as a glob when it contains glob syntax."""
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
        """Return True if the event's service name matches ``service``, as a glob when it contains glob syntax."""
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
    _predicates: tuple["Predicate[CallServiceEvent]", ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Snapshot the caller's mapping: equality compares ``spec``, so it must match what ``_predicates`` compiled.
        object.__setattr__(self, "spec", dict(self.spec))
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
        """Return True if every key in ``spec`` satisfies its condition in the event's service data."""
        return all(p(value) for p in self._predicates)

    def summarize(self) -> str:
        """Describe the check, which matches when every key in ``spec`` satisfies its condition in the service data.

        Returns:
            Comma-separated ``"<key> = <condition>"`` pairs, e.g. ``"entity_id = light.*, brightness = 200"``.
        """

        def _fmt(v: Any) -> str:
            if callable(v):
                return summarize_condition(v) if hasattr(v, "summarize") else callable_name(v)
            return str(v)

        parts = [f"{k} = {_fmt(v)}" for k, v in self.spec.items()]
        return ", ".join(parts)

    @classmethod
    def from_kwargs(cls, *, auto_glob: bool = True, **spec: "ChangeType") -> "ServiceDataWhere":
        """Ergonomic constructor for literal kwargs.

        Example:
        >>> ServiceDataWhere.from_kwargs(entity_id="light.*", brightness=200)
        """
        return cls(spec=spec, auto_glob=auto_glob)
