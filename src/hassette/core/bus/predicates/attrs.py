import typing
from dataclasses import dataclass
from typing import Any

from .base import SENTINEL

if typing.TYPE_CHECKING:
    from hassette.core.events import StateChangeEvent


@dataclass(frozen=True)
class AttrChanged:
    name: str
    from_: Any = SENTINEL
    to: Any = SENTINEL

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload.data

        old_attrs = getattr(data.old_state, "attributes", None)
        new_attrs = getattr(data.new_state, "attributes", None)
        old_v = getattr(old_attrs, self.name, SENTINEL)
        new_v = getattr(new_attrs, self.name, SENTINEL)

        if old_v is SENTINEL or new_v is SENTINEL or old_v == new_v:
            return False

        if self.from_ is not SENTINEL and old_v != self.from_:
            return False

        return not (self.to is not SENTINEL and new_v != self.to)
