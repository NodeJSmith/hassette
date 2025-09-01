from typing import Literal

from pydantic import Field

from ..sensors.base import Sensor_AttributesBase
from .base import BinarySensor_BaseState


class BinarySensor_MotionState(BinarySensor_BaseState):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["motion"]

    domain: Literal["binary_sensor"]

    attributes: Attributes | None = Field(default=None)
