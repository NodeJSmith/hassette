from typing import Literal

from pydantic import Field, field_validator
from whenever import OffsetDateTime, SystemDateTime

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
        last_time_reachable: SystemDateTime | None = Field(default=None)
        reason: str | None = Field(default=None)
        ip: str | None = Field(default=None)
        host_name: str | None = Field(default=None)

        @field_validator("last_time_reachable", mode="before")
        @classmethod
        def parse_last_triggered(cls, value: SystemDateTime | str | None) -> SystemDateTime | None:
            if isinstance(value, str):
                return OffsetDateTime.parse_common_iso(value).to_system_tz()
            return value

    domain: Literal["device_tracker"]

    attributes: Attributes
