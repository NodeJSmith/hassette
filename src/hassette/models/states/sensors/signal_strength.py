from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_SignalStrengthState(Sensor_BaseState[int | float | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["signal_strength"]

    attributes: Attributes | None = Field(default=None)
