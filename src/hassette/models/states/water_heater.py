from enum import IntFlag
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class WaterHeaterEntityFeature(IntFlag):
    TARGET_TEMPERATURE = 1
    OPERATION_MODE = 2
    AWAY_MODE = 4
    ON_OFF = 8


class WaterHeaterAttributes(AttributesBase):
    current_operation: str | None = Field(default=None)
    current_temperature: float | None = Field(default=None)
    is_away_mode_on: bool | None = Field(default=None)
    max_temp: float | None = Field(default=None)
    min_temp: float | None = Field(default=None)
    operation_list: list[str] | None = Field(default=None)
    precision: float | None = Field(default=None)
    target_temperature_high: float | None = Field(default=None)
    target_temperature_low: float | None = Field(default=None)
    target_temperature: float | None = Field(default=None)
    temperature_unit: str | None = Field(default=None)
    target_temperature_step: float | None = Field(default=None)

    @property
    def supports_target_temperature(self) -> bool:
        return self.has_feature(WaterHeaterEntityFeature.TARGET_TEMPERATURE)

    @property
    def supports_operation_mode(self) -> bool:
        return self.has_feature(WaterHeaterEntityFeature.OPERATION_MODE)

    @property
    def supports_away_mode(self) -> bool:
        return self.has_feature(WaterHeaterEntityFeature.AWAY_MODE)

    @property
    def supports_on_off(self) -> bool:
        return self.has_feature(WaterHeaterEntityFeature.ON_OFF)


class WaterHeaterState(StringBaseState):
    """Representation of a Home Assistant water_heater state.

    See: https://www.home-assistant.io/integrations/water_heater/
    """

    domain: Literal["water_heater"]

    attributes: WaterHeaterAttributes
