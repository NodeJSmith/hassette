from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_PrecipitationIntensityState(Sensor_BaseState[str | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["precipitation_intensity"]

        attribution: str | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
