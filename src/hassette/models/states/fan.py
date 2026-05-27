from enum import IntFlag
from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class FanEntityFeature(IntFlag):
    SET_SPEED = 1
    OSCILLATE = 2
    DIRECTION = 4
    PRESET_MODE = 8
    TURN_OFF = 16
    TURN_ON = 32


class FanAttributes(AttributesBase):
    direction: str | None = Field(default=None)
    oscillating: bool | None = Field(default=None)
    percentage: int | None = Field(default=None)
    preset_mode: str | None = Field(default=None)
    preset_modes: list[str] | None = Field(default=None)
    speed_count: int | None = Field(default=None)

    @property
    def supports_set_speed(self) -> bool:
        return self.has_feature(FanEntityFeature.SET_SPEED)

    @property
    def supports_oscillate(self) -> bool:
        return self.has_feature(FanEntityFeature.OSCILLATE)

    @property
    def supports_direction(self) -> bool:
        return self.has_feature(FanEntityFeature.DIRECTION)

    @property
    def supports_preset_mode(self) -> bool:
        return self.has_feature(FanEntityFeature.PRESET_MODE)

    @property
    def supports_turn_off(self) -> bool:
        return self.has_feature(FanEntityFeature.TURN_OFF)

    @property
    def supports_turn_on(self) -> bool:
        return self.has_feature(FanEntityFeature.TURN_ON)


class FanState(BoolBaseState):
    """Representation of a Home Assistant fan state.

    See: https://www.home-assistant.io/integrations/fan/
    """

    domain: Literal["fan"]

    attributes: FanAttributes
