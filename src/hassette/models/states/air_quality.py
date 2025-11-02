from typing import Literal

from pydantic import Field

from hassette.const.sensor import UNIT_OF_MEASUREMENT

from .base import AttributesBase, StringBaseState


class AirQualityState(StringBaseState):
    """Representation of a Home Assistant air_quality state.

    See: https://www.home-assistant.io/integrations/air_quality/
    """

    class Attributes(AttributesBase):
        nitrogen_oxide: float | None = Field(default=None)
        particulate_matter_10: float | None = Field(default=None)
        particulate_matter_2_5: float | None = Field(default=None)
        unit_of_measurement: UNIT_OF_MEASUREMENT | str | None = Field(default=None)
        attribution: str | None = Field(default=None)

    domain: Literal["air_quality"]

    attributes: Attributes
