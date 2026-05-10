from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class BinarySensorDeviceClass(StrEnum):
    BATTERY = "battery"
    BATTERY_CHARGING = "battery_charging"
    CO = "carbon_monoxide"
    COLD = "cold"
    CONNECTIVITY = "connectivity"
    DOOR = "door"
    GARAGE_DOOR = "garage_door"
    GAS = "gas"
    HEAT = "heat"
    LIGHT = "light"
    LOCK = "lock"
    MOISTURE = "moisture"
    MOTION = "motion"
    MOVING = "moving"
    OCCUPANCY = "occupancy"
    OPENING = "opening"
    PLUG = "plug"
    POWER = "power"
    PRESENCE = "presence"
    PROBLEM = "problem"
    RUNNING = "running"
    SAFETY = "safety"
    SMOKE = "smoke"
    SOUND = "sound"
    TAMPER = "tamper"
    UPDATE = "update"
    VIBRATION = "vibration"
    WINDOW = "window"


class BinarySensorAttributes(AttributesBase):
    device_class: BinarySensorDeviceClass | None = Field(default=None)
    is_on: bool | None = Field(default=None)
    state: None = Field(default=None)


class BinarySensorState(StringBaseState):
    """Representation of a Home Assistant binary_sensor state.

    See: https://www.home-assistant.io/integrations/binary_sensor/
    """

    domain: Literal["binary_sensor"]

    attributes: BinarySensorAttributes
