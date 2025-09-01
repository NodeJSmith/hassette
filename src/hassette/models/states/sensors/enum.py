from typing import Literal

from pydantic import Field

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_EnumState(Sensor_BaseState[str | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["enum"]

        options: list[str] | None = Field(default=None)
        still: int | None = Field(default=None)
        unknown: int | None = Field(default=None)
        metered: bool | None = Field(default=None)
        advertise_mode: str | None = Field(None, alias="Advertise mode")
        measured_power: int | None = Field(None, alias="Measured power")
        supports_transmitter: bool | None = Field(None, alias="Supports transmitter")
        transmitting_power: str | None = Field(None, alias="Transmitting power")
        id: str | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
