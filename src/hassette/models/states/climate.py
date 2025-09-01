from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ClimateState(StringBaseState):
    class Attributes(AttributesBase):
        hvac_modes: list[str] | None = Field(default=None)
        min_temp: int | None = Field(default=None)
        max_temp: int | None = Field(default=None)
        fan_modes: list[str] | None = Field(default=None)
        preset_modes: list[str] | None = Field(default=None)
        current_temperature: int | None = Field(default=None)
        temperature: int | None = Field(default=None)
        target_temp_high: None = Field(default=None)
        target_temp_low: None = Field(default=None)
        current_humidity: float | None = Field(default=None)
        fan_mode: str | None = Field(default=None)
        hvac_action: str | None = Field(default=None)
        preset_mode: str | None = Field(default=None)

    domain: Literal["climate"]

    attributes: Attributes | None = Field(default=None)
