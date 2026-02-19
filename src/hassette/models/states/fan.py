from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState
from .features import FanEntityFeature


class FanAttributes(AttributesBase):
    preset_modes: list[str] | None = Field(default=None)
    oscillating: bool | None = Field(default=None)
    percentage: int | float | None = Field(default=None)
    percentage_step: float | None = Field(default=None)
    preset_mode: str | None = Field(default=None)
    temperature: int | float | None = Field(default=None)
    model: str | None = Field(default=None)
    sn: str | None = Field(default=None)
    screen_status: bool | None = Field(default=None)
    child_lock: bool | None = Field(default=None)
    night_light: str | None = Field(default=None)
    mode: str | None = Field(default=None)

    @property
    def supports_set_speed(self) -> bool:
        """Whether this fan supports setting speed."""
        return self._has_feature(FanEntityFeature.SET_SPEED)

    @property
    def supports_oscillate(self) -> bool:
        """Whether this fan supports oscillation."""
        return self._has_feature(FanEntityFeature.OSCILLATE)

    @property
    def supports_direction(self) -> bool:
        """Whether this fan supports direction."""
        return self._has_feature(FanEntityFeature.DIRECTION)

    @property
    def supports_preset_mode(self) -> bool:
        """Whether this fan supports preset mode."""
        return self._has_feature(FanEntityFeature.PRESET_MODE)

    @property
    def supports_turn_off(self) -> bool:
        """Whether this fan supports turning off."""
        return self._has_feature(FanEntityFeature.TURN_OFF)

    @property
    def supports_turn_on(self) -> bool:
        """Whether this fan supports turning on."""
        return self._has_feature(FanEntityFeature.TURN_ON)


class FanState(StringBaseState):
    """Representation of a Home Assistant fan state.

    See: https://www.home-assistant.io/integrations/fan/
    """

    domain: Literal["fan"]

    attributes: FanAttributes
