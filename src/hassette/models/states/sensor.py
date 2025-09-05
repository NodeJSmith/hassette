from typing import Literal

from pydantic import Field

from hassette.const.sensor import DEVICE_CLASS, STATE_CLASS, UNIT_OF_MEASUREMENT

from .base import AttributesBase, StringBaseState


class SensorAttributes(AttributesBase):
    device_class: DEVICE_CLASS | str | None = Field(default=None)

    state_class: STATE_CLASS | None | str = Field(default=None)
    unit_of_measurement: UNIT_OF_MEASUREMENT | str | None = Field(default=None)

    options: list[str] | None = Field(default=None)


class SensorState(StringBaseState):
    domain: Literal["sensor"]
    attributes: SensorAttributes
