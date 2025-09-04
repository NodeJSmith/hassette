from typing import Literal

from pydantic import Field
from whenever import Instant, PlainDateTime

from .base import AttributesBase, StringBaseState


class DeviceTrackerState(StringBaseState):
    class Attributes(AttributesBase):
        source_type: str | None = Field(default=None)
        battery_level: int | float | None = Field(default=None)
        latitude: float | None = Field(default=None)
        longitude: float | None = Field(default=None)
        gps_accuracy: int | float | None = Field(default=None)
        altitude: float | None = Field(default=None)
        vertical_accuracy: int | float | None = Field(default=None)
        course: int | float | None = Field(default=None)
        speed: int | float | None = Field(default=None)
        scanner: str | None = Field(default=None)
        area: str | None = Field(default=None)
        mac: str | None = Field(default=None)
        last_time_reachable: Instant | PlainDateTime | None = Field(default=None)
        reason: str | None = Field(default=None)
        ip: str | None = Field(default=None)
        host_name: str | None = Field(default=None)

    domain: Literal["device_tracker"]

    attributes: Attributes
