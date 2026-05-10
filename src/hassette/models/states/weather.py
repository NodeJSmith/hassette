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
    state: None = Field(default=None)
    wind_bearing: float | str | None = Field(default=None)
    native_pressure: float | None = Field(default=None)
    native_pressure_unit: str | None = Field(default=None)
    native_apparent_temperature: float | None = Field(default=None)
    native_temperature: float | None = Field(default=None)
    native_temperature_unit: str | None = Field(default=None)
    native_visibility: float | None = Field(default=None)
    native_visibility_unit: str | None = Field(default=None)
    native_precipitation_unit: str | None = Field(default=None)
    native_wind_gust_speed: float | None = Field(default=None)
    native_wind_speed: float | None = Field(default=None)
    native_wind_speed_unit: str | None = Field(default=None)
    native_dew_point: float | None = Field(default=None)

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
