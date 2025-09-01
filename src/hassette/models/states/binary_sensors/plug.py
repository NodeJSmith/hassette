from typing import Literal

from pydantic import Field

from ..sensors.base import Sensor_AttributesBase
from .base import BinarySensor_BaseState


class BinarySensor_PlugState(BinarySensor_BaseState):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["plug"]

    domain: Literal["binary_sensor"]

    attributes: Attributes | None = Field(default=None)
