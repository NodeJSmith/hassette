from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_WindDirectionState(Sensor_BaseState[int | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["wind_direction"]

        attribution: str | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
