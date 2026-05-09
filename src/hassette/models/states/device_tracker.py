from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class DeviceTrackerAttributes(AttributesBase):
    source_type: str | None = Field(default=None)
    battery_level: int | float | None = Field(default=None)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    gps_accuracy: int | float | None = Field(default=None)
    in_zones: list[str] | None = Field(default=None)
    ip: str | None = Field(default=None)
    mac: str | None = Field(default=None)
    host_name: str | None = Field(default=None)


class DeviceTrackerState(StringBaseState):
    """Representation of a Home Assistant device_tracker state.

    See: https://www.home-assistant.io/integrations/device_tracker/
    """

    domain: Literal["device_tracker"]

    attributes: DeviceTrackerAttributes
