from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class WeatherAttributes(AttributesBase):
    temperature: float | None = Field(default=None)
    apparent_temperature: float | None = Field(default=None)
    dew_point: float | None = Field(default=None)
    temperature_unit: str | None = Field(default=None)
    humidity: float | None = Field(default=None)
    cloud_coverage: float | None = Field(default=None)
    pressure: float | None = Field(default=None)
    pressure_unit: str | None = Field(default=None)
    wind_bearing: float | None = Field(default=None)
    wind_speed: float | None = Field(default=None)
    wind_speed_unit: str | None = Field(default=None)
    visibility_unit: str | None = Field(default=None)
    precipitation_unit: str | None = Field(default=None)
    attribution: str | None = Field(default=None)

    ozone: float | None = Field(default=None)
    """Ozone level."""

    uv_index: float | None = Field(default=None)
    """UV index."""

    wind_gust_speed: float | None = Field(default=None)
    """Wind gust speed."""

    visibility: float | None = Field(default=None)
    """Visibility distance."""


class WeatherState(StringBaseState):
    """Representation of a Home Assistant weather state.

    See: https://www.home-assistant.io/integrations/weather/
    """

    domain: Literal["weather"]

    attributes: WeatherAttributes
