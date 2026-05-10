from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class HVACMode(StrEnum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    HEAT_COOL = "heat_cool"
    AUTO = "auto"
    DRY = "dry"
    FAN_ONLY = "fan_only"


class HVACAction(StrEnum):
    COOLING = "cooling"
    DEFROSTING = "defrosting"
    DRYING = "drying"
    FAN = "fan"
    HEATING = "heating"
    IDLE = "idle"
    OFF = "off"
    PREHEATING = "preheating"


class ClimateEntityFeature(IntFlag):
    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    TARGET_HUMIDITY = 4
    FAN_MODE = 8
    PRESET_MODE = 16
    SWING_MODE = 32
    TURN_OFF = 128
    TURN_ON = 256
    SWING_HORIZONTAL_MODE = 512


class ClimateAttributes(AttributesBase):
    current_humidity: float | None = Field(default=None)
    current_temperature: float | None = Field(default=None)
    fan_mode: str | None = Field(default=None)
    fan_modes: list[str] | None = Field(default=None)
    hvac_action: HVACAction | None = Field(default=None)
    hvac_mode: HVACMode | None = Field(default=None)
    hvac_modes: list[HVACMode] | None = Field(default=None)
    max_humidity: float = Field(default=None)
    max_temp: float | None = Field(default=None)
    min_humidity: float = Field(default=None)
    min_temp: float | None = Field(default=None)
    precision: float | None = Field(default=None)
    preset_mode: str | None = Field(default=None)
    preset_modes: list[str] | None = Field(default=None)
    swing_mode: str | None = Field(default=None)
    swing_modes: list[str] | None = Field(default=None)
    swing_horizontal_mode: str | None = Field(default=None)
    swing_horizontal_modes: list[str] | None = Field(default=None)
    target_humidity: float | None = Field(default=None)
    target_humidity_step: int | None = Field(default=None)
    target_temperature_high: float | None = Field(default=None)
    target_temperature_low: float | None = Field(default=None)
    target_temperature_step: float | None = Field(default=None)
    target_temperature: float | None = Field(default=None)
    temperature_unit: str | None = Field(default=None)

    @property
    def supports_target_temperature(self) -> bool:
        return self._has_feature(ClimateEntityFeature.TARGET_TEMPERATURE)

    @property
    def supports_target_temperature_range(self) -> bool:
        return self._has_feature(ClimateEntityFeature.TARGET_TEMPERATURE_RANGE)

    @property
    def supports_target_humidity(self) -> bool:
        return self._has_feature(ClimateEntityFeature.TARGET_HUMIDITY)

    @property
    def supports_fan_mode(self) -> bool:
        return self._has_feature(ClimateEntityFeature.FAN_MODE)

    @property
    def supports_preset_mode(self) -> bool:
        return self._has_feature(ClimateEntityFeature.PRESET_MODE)

    @property
    def supports_swing_mode(self) -> bool:
        return self._has_feature(ClimateEntityFeature.SWING_MODE)

    @property
    def supports_turn_off(self) -> bool:
        return self._has_feature(ClimateEntityFeature.TURN_OFF)

    @property
    def supports_turn_on(self) -> bool:
        return self._has_feature(ClimateEntityFeature.TURN_ON)

    @property
    def supports_swing_horizontal_mode(self) -> bool:
        return self._has_feature(ClimateEntityFeature.SWING_HORIZONTAL_MODE)


class ClimateState(StringBaseState):
    """Representation of a Home Assistant climate state.

    See: https://www.home-assistant.io/integrations/climate/
    """

    domain: Literal["climate"]

    attributes: ClimateAttributes
