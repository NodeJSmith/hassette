from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class DeviceTrackerState(StringBaseState):
    """Representation of a Home Assistant device_tracker state.

    See: https://www.home-assistant.io/integrations/device_tracker/
    """

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
        last_time_reachable: ZonedDateTime | None = Field(default=None)
        reason: str | None = Field(default=None)
        ip: str | None = Field(default=None)
        host_name: str | None = Field(default=None)

        @field_validator("last_time_reachable", mode="before")
        @classmethod
        def parse_last_triggered(cls, value: ZonedDateTime | str | None) -> ZonedDateTime | None:
            return convert_datetime_str_to_system_tz(value)

    domain: Literal["device_tracker"]

    attributes: Attributes
