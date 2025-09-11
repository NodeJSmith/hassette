import typing
from dataclasses import dataclass
from typing import Any

if typing.TYPE_CHECKING:
    from hassette.core.events import StateChangeEvent


@dataclass(frozen=True)
class Changed:
    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload.data

        return data.has_new_state and data.has_old_state and data.new_state_value != data.old_state_value


@dataclass(frozen=True)
class ChangedTo:
    value: Any

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload.data

        return data.new_state_value == self.value


@dataclass(frozen=True)
class ChangedFrom:
    value: Any

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload.data

        return data.old_state_value == self.value
