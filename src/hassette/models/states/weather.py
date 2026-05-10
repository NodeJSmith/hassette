from enum import IntFlag
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class WeatherEntityFeature(IntFlag):
    FORECAST_DAILY = 1
    FORECAST_HOURLY = 2
    FORECAST_TWICE_DAILY = 4


class WeatherAttributes(AttributesBase):
    condition: str | None = Field(default=None)
    humidity: float | None = Field(default=None)
    ozone: float | None = Field(default=None)
    cloud_coverage: int | None = Field(default=None)
    uv_index: float | None = Field(default=None)
    precision: float | None = Field(default=None)
    wind_bearing: float | str | None = Field(default=None)
    pressure: float | None = Field(default=None)
    pressure_unit: str | None = Field(default=None)
    apparent_temperature: float | None = Field(default=None)
    temperature: float | None = Field(default=None)
    temperature_unit: str | None = Field(default=None)
    visibility: float | None = Field(default=None)
    visibility_unit: str | None = Field(default=None)
    precipitation_unit: str | None = Field(default=None)
    wind_gust_speed: float | None = Field(default=None)
    wind_speed: float | None = Field(default=None)
    wind_speed_unit: str | None = Field(default=None)
    dew_point: float | None = Field(default=None)

    @property
    def supports_forecast_daily(self) -> bool:
        return self._has_feature(WeatherEntityFeature.FORECAST_DAILY)

    @property
    def supports_forecast_hourly(self) -> bool:
        return self._has_feature(WeatherEntityFeature.FORECAST_HOURLY)

    @property
    def supports_forecast_twice_daily(self) -> bool:
        return self._has_feature(WeatherEntityFeature.FORECAST_TWICE_DAILY)


class WeatherState(StringBaseState):
    """Representation of a Home Assistant weather state.

    See: https://www.home-assistant.io/integrations/weather/
    """

    domain: Literal["weather"]

    attributes: WeatherAttributes
