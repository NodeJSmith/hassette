from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_DurationState(Sensor_BaseState[str | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["duration"]

        end: int | None = Field(default=None)
        start: int | None = Field(default=None)
        status: str | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
