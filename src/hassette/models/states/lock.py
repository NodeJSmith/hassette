from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class LockStateValue(StrEnum):
    JAMMED = "jammed"
    OPENING = "opening"
    LOCKING = "locking"
    OPEN = "open"
    UNLOCKING = "unlocking"
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class LockEntityFeature(IntFlag):
    OPEN = 1


class LockAttributes(AttributesBase):
    changed_by: str | None = Field(default=None)
    code_format: str | None = Field(default=None)
    is_locked: bool | None = Field(default=None)
    is_locking: bool | None = Field(default=None)
    is_open: bool | None = Field(default=None)
    is_opening: bool | None = Field(default=None)
    is_unlocking: bool | None = Field(default=None)
    is_jammed: bool | None = Field(default=None)
    state: None = Field(default=None)

    @property
    def supports_open(self) -> bool:
        return self._has_feature(LockEntityFeature.OPEN)


class LockState(StringBaseState):
    """Representation of a Home Assistant lock state.

    See: https://www.home-assistant.io/integrations/lock/
    """

    domain: Literal["lock"]

    attributes: LockAttributes
