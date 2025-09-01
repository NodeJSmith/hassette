from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_Pm25State(Sensor_BaseState[str | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["pm25"]

    attributes: Attributes | None = Field(default=None)
