from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class WaterHeaterState(StringBaseState):
    class Attributes(AttributesBase):
        min_temp: float | None = Field(default=None)
        max_temp: float | None = Field(default=None)
        target_temp_step: float | None = Field(default=None)
        operation_list: list[str] | None = Field(default=None)
        current_temperature: float | None = Field(default=None)
        temperature: float | None = Field(default=None)
        target_temp_high: float | None = Field(default=None)
        target_temp_low: float | None = Field(default=None)
        operation_mode: str | None = Field(default=None)
        away_mode: str | None = Field(default=None)

    domain: Literal["water_heater"]

    attributes: Attributes
