import typing
from dataclasses import dataclass
from typing import Any

from hassette.const.misc import NOT_PROVIDED
from hassette.types import ChangeType, PredicateCallable
from hassette.utils.glob_utils import is_glob, matches_globs

if typing.TYPE_CHECKING:
    from hassette import StateChangeEvent, states


@dataclass(frozen=True)
class DomainMatches:
    """Predicate that evaluates to True if the event's domain matches the specified domain,
    including support for glob patterns.
    """

    domain: str

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload

        if data.domain is None:
            return False

        if is_glob(self.domain):
            return matches_globs(data.domain, (self.domain,))

        return data.domain == self.domain

    def __repr__(self) -> str:
        return f"DomainMatches(domain={self.domain!r})"


@dataclass(frozen=True)
class EntityMatches:
    """Predicate that evaluates to True if the event's entity_id matches the specified entity_id,
    including support for glob patterns.
    """

    entity_id: str

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload.data

        if data.entity_id is None:
            return False

        if is_glob(self.entity_id):
            return matches_globs(data.entity_id, (self.entity_id,))

        return data.entity_id == self.entity_id

    def __repr__(self) -> str:
        return f"EntityMatches(entity_id={self.entity_id!r})"


@dataclass(frozen=True)
class StateChanged:
    """Predicate that evaluates to True if the state of a specific entity has changed.

    `from_` and `to` can be used to further filter the changes. If `from_` is set, the state must have changed from
    that value. If `to` is set, the state must have changed to that value. These can be used together or separately.

    Alternatively, `from_` and `to` can be synchronous callables that take the old or new value respectively and return
    a boolean indicating whether the condition is met.

    If `from_` or `to` are not set, they will not be considered in the evaluation. `None` is a valid value for these
    fields.

    Example:

    .. code-block:: python

        # Trigger if the state changes to 'on'
        StateChanged(entity_id='light.living_room', to='on')

        # Trigger if the state changes from 'off' to 'on'
        StateChanged(entity_id='light.living_room', from_='off', to='on')

        # Trigger if to is >= 20
        StateChanged(entity_id='sensor.temperature', to=lambda new: new >= 20)
    """

    from_: ChangeType = NOT_PROVIDED
    to: ChangeType = NOT_PROVIDED

    def __call__(self, event: "StateChangeEvent[states.StateUnion]") -> bool:
        data = event.payload.data

        old_v = data.old_state.value if data.old_state else NOT_PROVIDED
        new_v = data.new_state.value if data.new_state else NOT_PROVIDED

        return check_from_to(self.from_, self.to, old_v, new_v)


@dataclass(frozen=True)
class AttrChanged:
    """Predicate that evaluates to True if a specific attribute of an entity has changed.

    `from_` and `to` can be used to further filter the changes. If `from_` is set, the attribute must have changed from
    that value. If `to` is set, the attribute must have changed to that value. These can be used together or separately.

    Alternatively, `from_` and `to` can be synchronous callables that take the old or new value respectively and return
    a boolean indicating whether the condition is met.

    If `from_` or `to` are not set, they will not be considered in the evaluation. `None` is a valid value for these
    fields.

    Example:

    .. code-block:: python

        # Trigger if the 'status' attribute changes to 'active'
        AttrChanged(name='status', to='active')

        # Trigger if the 'level' attribute changes from 10 to 20
        AttrChanged(name='level', from_=10, to=20)

        # Trigger if to is >= 20
        AttrChanged(name='level', to=lambda new: new >= 20)
    """

    name: str
    """The name of the attribute to monitor for changes."""

    from_: ChangeType = NOT_PROVIDED
    """The previous value of the attribute or a synchronous callable that takes the old value and returns a bool."""

    to: ChangeType = NOT_PROVIDED
    """The new value of the attribute or a synchronous callable that takes the new value and returns a bool."""

    def __call__(self, event: "StateChangeEvent[states.StateUnion]") -> bool:
        data = event.payload.data

        old_attrs = data.old_state.attributes.model_dump() if data.old_state else {}
        new_attrs = data.new_state.attributes.model_dump() if data.new_state else {}
        old_v = old_attrs.get(self.name, NOT_PROVIDED)
        new_v = new_attrs.get(self.name, NOT_PROVIDED)

        return check_from_to(self.from_, self.to, old_v, new_v)


def check_from_to(from_: ChangeType, to: ChangeType, old_v: Any, new_v: Any) -> bool:
    """Helper function to evaluate from_ and to conditions against old and new values."""

    # if the value hasn't changed, return False
    if old_v == new_v:
        return False

    # if we've defined a from_ value and there's no old value, return False
    if old_v is NOT_PROVIDED and from_ is not NOT_PROVIDED:
        return False

    # if we've defined a to value and there's no new value, return False
    if new_v is NOT_PROVIDED and to is not NOT_PROVIDED:
        return False

    # if we've defined a from value and it doesn't match, return False
    from_match_status = _compare_value(from_, old_v)
    if not from_match_status:
        return False

    # if we've defined a to value and it doesn't match, return False
    to_match_status = _compare_value(to, new_v)
    if not to_match_status:
        return False

    return True


def _compare_value(predicate: ChangeType, actual: Any) -> bool:
    """Helper function to compare a defined value or predicate against an actual value."""

    if predicate is NOT_PROVIDED:
        return True

    if not callable(predicate):
        return actual == predicate

    if isinstance(predicate, PredicateCallable):
        result = predicate(actual)
        if not isinstance(result, bool):
            raise TypeError(f"Predicate callable {predicate!r} did not return a boolean (returned {type(result)})")
        return result

    raise TypeError(f"Predicate {predicate!r} is not a valid type or callable ({type(predicate)})")
