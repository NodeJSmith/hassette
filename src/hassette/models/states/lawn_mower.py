from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class LawnMowerActivity(StrEnum):
    ERROR = "error"
    PAUSED = "paused"
    MOWING = "mowing"
    DOCKED = "docked"
    RETURNING = "returning"
    IDLE = "idle"


class LawnMowerEntityFeature(IntFlag):
    START_MOWING = 1
    PAUSE = 2
    DOCK = 4
    STOP = 8


class LawnMowerAttributes(AttributesBase):
    activity: LawnMowerActivity | None = Field(default=None)

    @property
    def supports_start_mowing(self) -> bool:
        return self.has_feature(LawnMowerEntityFeature.START_MOWING)

    @property
    def supports_pause(self) -> bool:
        return self.has_feature(LawnMowerEntityFeature.PAUSE)

    @property
    def supports_dock(self) -> bool:
        return self.has_feature(LawnMowerEntityFeature.DOCK)

    @property
    def supports_stop(self) -> bool:
        return self.has_feature(LawnMowerEntityFeature.STOP)


class LawnMowerState(StringBaseState):
    """Representation of a Home Assistant lawn_mower state.

    See: https://www.home-assistant.io/integrations/lawn_mower/
    """

    domain: Literal["lawn_mower"]

    attributes: LawnMowerAttributes
