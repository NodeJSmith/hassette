from typing import Literal

from pydantic import Field

from hassette.const.sensor import UNIT_OF_MEASUREMENT

from .base import AttributesBase, NumericBaseState


class AirQualityAttributes(AttributesBase):
    particulate_matter_2_5: float | None = Field(default=None)
    particulate_matter_10: float | None = Field(default=None)
    particulate_matter_0_1: float | None = Field(default=None)
    air_quality_index: float | None = Field(default=None)
    ozone: float | None = Field(default=None)
    carbon_monoxide: float | None = Field(default=None)
    carbon_dioxide: float | None = Field(default=None)
    sulphur_dioxide: float | None = Field(default=None)
    nitrogen_oxide: float | None = Field(default=None)
    nitrogen_monoxide: float | None = Field(default=None)
    nitrogen_dioxide: float | None = Field(default=None)
    unit_of_measurement: UNIT_OF_MEASUREMENT | str | None = Field(default=None)
    attribution: str | None = Field(default=None)


class AirQualityState(NumericBaseState):
    """Representation of a Home Assistant air_quality state.

    See: https://www.home-assistant.io/integrations/air_quality/
    """

    domain: Literal["air_quality"]

    attributes: AirQualityAttributes
