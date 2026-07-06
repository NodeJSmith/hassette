from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class WeatherEntityStateAttribute(StrEnum):
    TEMPERATURE = "temperature"
    APPARENT_TEMPERATURE = "apparent_temperature"
    DEW_POINT = "dew_point"
    TEMPERATURE_UNIT = "temperature_unit"
    HUMIDITY = "humidity"
    OZONE = "ozone"
    CLOUD_COVERAGE = "cloud_coverage"
    UV_INDEX = "uv_index"
    PRESSURE = "pressure"
    PRESSURE_UNIT = "pressure_unit"
    WIND_BEARING = "wind_bearing"
    WIND_GUST_SPEED = "wind_gust_speed"
    WIND_SPEED = "wind_speed"
    WIND_SPEED_UNIT = "wind_speed_unit"
    VISIBILITY = "visibility"
    VISIBILITY_UNIT = "visibility_unit"
    PRECIPITATION_UNIT = "precipitation_unit"


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
        return self.has_feature(WeatherEntityFeature.FORECAST_DAILY)

    @property
    def supports_forecast_hourly(self) -> bool:
        return self.has_feature(WeatherEntityFeature.FORECAST_HOURLY)

    @property
    def supports_forecast_twice_daily(self) -> bool:
        return self.has_feature(WeatherEntityFeature.FORECAST_TWICE_DAILY)


class WeatherState(StringBaseState):
    """Representation of a Home Assistant weather state.

    See: https://www.home-assistant.io/integrations/weather/
    """

    domain: Literal["weather"]

    attributes: WeatherAttributes
