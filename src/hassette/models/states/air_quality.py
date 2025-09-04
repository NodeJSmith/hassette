from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AirQualityState(StringBaseState):
    class Attributes(AttributesBase):
        nitrogen_oxide: float | None = Field(default=None)
        particulate_matter_10: float | None = Field(default=None)
        particulate_matter_2_5: float | None = Field(default=None)
        unit_of_measurement: str | None = Field(default=None)
        attribution: str | None = Field(default=None)

    domain: Literal["air_quality"]

    attributes: Attributes
