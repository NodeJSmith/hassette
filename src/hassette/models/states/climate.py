from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ClimateState(StringBaseState):
    class Attributes(AttributesBase):
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

    domain: Literal["climate"]

    attributes: Attributes
