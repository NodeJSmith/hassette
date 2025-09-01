from typing import Literal

from pydantic import Field

from hassette.models.states.sensors.base import Sensor_AttributesBase, Sensor_NumericBaseState


class Sensor_TemperatureState(Sensor_NumericBaseState):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["temperature"]

        attribution: str | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
