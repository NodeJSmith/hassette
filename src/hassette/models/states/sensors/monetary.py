from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_MonetaryState(Sensor_BaseState[int | float | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["monetary"]

    attributes: Attributes | None = Field(default=None)
