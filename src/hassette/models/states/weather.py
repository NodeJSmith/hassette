from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class WeatherState(StringBaseState):
    class Attributes(AttributesBase):
        temperature: int | None = Field(default=None)
        apparent_temperature: int | None = Field(default=None)
        dew_point: int | None = Field(default=None)
        temperature_unit: str | None = Field(default=None)
        humidity: int | None = Field(default=None)
        cloud_coverage: int | None = Field(default=None)
        pressure: float | None = Field(default=None)
        pressure_unit: str | None = Field(default=None)
        wind_bearing: int | None = Field(default=None)
        wind_speed: float | None = Field(default=None)
        wind_speed_unit: str | None = Field(default=None)
        visibility_unit: str | None = Field(default=None)
        precipitation_unit: str | None = Field(default=None)
        attribution: str | None = Field(default=None)

    domain: Literal["weather"]

    attributes: Attributes | None = Field(default=None)
