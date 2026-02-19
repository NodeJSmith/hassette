from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState
from .features import ClimateEntityFeature


class ClimateAttributes(AttributesBase):
    hvac_modes: list[str] | None = Field(default=None)
    min_temp: int | float | None = Field(default=None)
    max_temp: int | float | None = Field(default=None)
    fan_modes: list[str] | None = Field(default=None)
    preset_modes: list[str] | None = Field(default=None)
    current_temperature: int | float | None = Field(default=None)
    temperature: int | float | None = Field(default=None)
    target_temp_high: float | None = Field(default=None)
    target_temp_low: float | None = Field(default=None)
    current_humidity: float | None = Field(default=None)
    fan_mode: str | None = Field(default=None)
    hvac_action: str | None = Field(default=None)
    preset_mode: str | None = Field(default=None)
    swing_mode: str | None = Field(default=None)
    swing_modes: list[str] | None = Field(default=None)

    @property
    def supports_target_temperature(self) -> bool:
        """Whether this climate entity supports target temperature."""
        return self._has_feature(ClimateEntityFeature.TARGET_TEMPERATURE)

    @property
    def supports_target_temperature_range(self) -> bool:
        """Whether this climate entity supports target temperature range."""
        return self._has_feature(ClimateEntityFeature.TARGET_TEMPERATURE_RANGE)

    @property
    def supports_target_humidity(self) -> bool:
        """Whether this climate entity supports target humidity."""
        return self._has_feature(ClimateEntityFeature.TARGET_HUMIDITY)

    @property
    def supports_fan_mode(self) -> bool:
        """Whether this climate entity supports fan mode."""
        return self._has_feature(ClimateEntityFeature.FAN_MODE)

    @property
    def supports_preset_mode(self) -> bool:
        """Whether this climate entity supports preset mode."""
        return self._has_feature(ClimateEntityFeature.PRESET_MODE)

    @property
    def supports_swing_mode(self) -> bool:
        """Whether this climate entity supports swing mode."""
        return self._has_feature(ClimateEntityFeature.SWING_MODE)

    @property
    def supports_turn_off(self) -> bool:
        """Whether this climate entity supports turning off."""
        return self._has_feature(ClimateEntityFeature.TURN_OFF)

    @property
    def supports_turn_on(self) -> bool:
        """Whether this climate entity supports turning on."""
        return self._has_feature(ClimateEntityFeature.TURN_ON)

    @property
    def supports_swing_horizontal_mode(self) -> bool:
        """Whether this climate entity supports horizontal swing mode."""
        return self._has_feature(ClimateEntityFeature.SWING_HORIZONTAL_MODE)


class ClimateState(StringBaseState):
    """Representation of a Home Assistant climate state.

    See: https://www.home-assistant.io/integrations/climate/
    """

    domain: Literal["climate"]

    attributes: ClimateAttributes
