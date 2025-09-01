from typing import Literal

from pydantic import Field
from whenever import Instant, PlainDateTime

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_TimestampState(Sensor_BaseState[Instant | PlainDateTime | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["timestamp"]

        local_time: Instant | PlainDateTime | None = Field(None, alias="Local Time")
        package: str | None = Field(None, alias="Package")
        time_in_milliseconds: int | None = Field(None, alias="Time in Milliseconds")
        next_alarm_status: str | None = Field(default=None)
        alarm_volume: int | None = Field(default=None)
        alarms: list | None = Field(default=None)
        next_timer_status: str | None = Field(default=None)
        timers: list | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
