from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_EnergyState(Sensor_BaseState[int | float | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["energy"]

    attributes: Attributes | None = Field(default=None)
