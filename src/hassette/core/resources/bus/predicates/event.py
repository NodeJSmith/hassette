import typing
from dataclasses import dataclass
from typing import Any

from hassette.const.misc import NOT_PROVIDED
from hassette.events import CallServiceEvent
from hassette.types import ChangeType, PredicateCallable
from hassette.utils.glob_utils import is_glob, matches_globs

if typing.TYPE_CHECKING:
    from hassette import Predicate


@dataclass
class CallServiceEventWrapper:
    """Wraps a CallServiceEvent to allow predicates to evaluate its service_data."""

    predicates: tuple["Predicate", ...]
    """The predicates to evaluate."""

    def __call__(self, event: CallServiceEvent) -> bool:
        data = event.payload.data.service_data

        return all(p(data) for p in self.predicates)


@dataclass(frozen=True)
class KeyValueMatches:
    """Predicate that evaluates to True if the event's data contains the specified key-value pair.

    Supports glob patterns for string values and callable predicates for more complex matching.
    """

    key: str
    value: "ChangeType | type[Any]" = NOT_PROVIDED
    """The value to match. If NOT_PROVIDED or Any, only the presence of the key is checked."""

    def __call__(self, data: dict[str, Any]) -> bool:
        if self.key not in data:
            return False

        actual_value = data[self.key]

        if self.value is NOT_PROVIDED or self.value is Any:
            return True  # key exists, value doesn't matter

        if isinstance(self.value, PredicateCallable):
            return self.value(actual_value)

        if isinstance(self.value, str) and is_glob(self.value):
            if not isinstance(actual_value, str):
                return False
            return matches_globs(actual_value, (self.value,))

        return actual_value == self.value

    def __repr__(self) -> str:
        return f"KeyValueMatches(key={self.key!r}, value={self.value!r})"
