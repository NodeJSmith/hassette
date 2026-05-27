from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class VacuumActivity(StrEnum):
    CLEANING = "cleaning"
    DOCKED = "docked"
    IDLE = "idle"
    PAUSED = "paused"
    RETURNING = "returning"
    ERROR = "error"


class VacuumEntityFeature(IntFlag):
    TURN_ON = 1
    TURN_OFF = 2
    PAUSE = 4
    STOP = 8
    RETURN_HOME = 16
    FAN_SPEED = 32
    BATTERY = 64
    STATUS = 128
    SEND_COMMAND = 256
    LOCATE = 512
    CLEAN_SPOT = 1024
    MAP = 2048
    STATE = 4096
    START = 8192
    CLEAN_AREA = 16384


class VacuumAttributes(AttributesBase):
    battery_icon: str | None = Field(default=None)
    battery_level: int | None = Field(default=None)
    fan_speed: str | None = Field(default=None)
    fan_speed_list: list[str] | None = Field(default=None)
    activity: VacuumActivity | None = Field(default=None)

    @property
    def supports_turn_on(self) -> bool:
        return self.has_feature(VacuumEntityFeature.TURN_ON)

    @property
    def supports_turn_off(self) -> bool:
        return self.has_feature(VacuumEntityFeature.TURN_OFF)

    @property
    def supports_pause(self) -> bool:
        return self.has_feature(VacuumEntityFeature.PAUSE)

    @property
    def supports_stop(self) -> bool:
        return self.has_feature(VacuumEntityFeature.STOP)

    @property
    def supports_return_home(self) -> bool:
        return self.has_feature(VacuumEntityFeature.RETURN_HOME)

    @property
    def supports_fan_speed(self) -> bool:
        return self.has_feature(VacuumEntityFeature.FAN_SPEED)

    @property
    def supports_battery(self) -> bool:
        return self.has_feature(VacuumEntityFeature.BATTERY)

    @property
    def supports_status(self) -> bool:
        return self.has_feature(VacuumEntityFeature.STATUS)

    @property
    def supports_send_command(self) -> bool:
        return self.has_feature(VacuumEntityFeature.SEND_COMMAND)

    @property
    def supports_locate(self) -> bool:
        return self.has_feature(VacuumEntityFeature.LOCATE)

    @property
    def supports_clean_spot(self) -> bool:
        return self.has_feature(VacuumEntityFeature.CLEAN_SPOT)

    @property
    def supports_map(self) -> bool:
        return self.has_feature(VacuumEntityFeature.MAP)

    @property
    def supports_state(self) -> bool:
        return self.has_feature(VacuumEntityFeature.STATE)

    @property
    def supports_start(self) -> bool:
        return self.has_feature(VacuumEntityFeature.START)

    @property
    def supports_clean_area(self) -> bool:
        return self.has_feature(VacuumEntityFeature.CLEAN_AREA)


class VacuumState(StringBaseState):
    """Representation of a Home Assistant vacuum state.

    See: https://www.home-assistant.io/integrations/vacuum/
    """

    domain: Literal["vacuum"]

    attributes: VacuumAttributes
