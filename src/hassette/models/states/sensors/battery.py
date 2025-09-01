from typing import Literal

from pydantic import Field

from hassette.models.states.sensors.base import Sensor_AttributesBase, Sensor_NumericBaseState


class Sensor_BatteryState(Sensor_NumericBaseState):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["battery"]

    attributes: Attributes | None = Field(default=None)
