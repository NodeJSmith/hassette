from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AlarmControlPanelStateValue(StrEnum):
    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"
    ARMED_AWAY = "armed_away"
    ARMED_NIGHT = "armed_night"
    ARMED_VACATION = "armed_vacation"
    ARMED_CUSTOM_BYPASS = "armed_custom_bypass"
    PENDING = "pending"
    ARMING = "arming"
    DISARMING = "disarming"
    TRIGGERED = "triggered"


class CodeFormat(StrEnum):
    TEXT = "text"
    NUMBER = "number"


class AlarmControlPanelEntityFeature(IntFlag):
    ARM_HOME = 1
    ARM_AWAY = 2
    ARM_NIGHT = 4
    TRIGGER = 8
    ARM_CUSTOM_BYPASS = 16
    ARM_VACATION = 32


class AlarmControlPanelAttributes(AttributesBase):
    alarm_state: AlarmControlPanelStateValue | None = Field(default=None)
    changed_by: str | None = Field(default=None)
    code_arm_required: bool = Field(default=None)
    code_format: CodeFormat | None = Field(default=None)

    @property
    def supports_arm_home(self) -> bool:
        return self._has_feature(AlarmControlPanelEntityFeature.ARM_HOME)

    @property
    def supports_arm_away(self) -> bool:
        return self._has_feature(AlarmControlPanelEntityFeature.ARM_AWAY)

    @property
    def supports_arm_night(self) -> bool:
        return self._has_feature(AlarmControlPanelEntityFeature.ARM_NIGHT)

    @property
    def supports_trigger(self) -> bool:
        return self._has_feature(AlarmControlPanelEntityFeature.TRIGGER)

    @property
    def supports_arm_custom_bypass(self) -> bool:
        return self._has_feature(AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS)

    @property
    def supports_arm_vacation(self) -> bool:
        return self._has_feature(AlarmControlPanelEntityFeature.ARM_VACATION)


class AlarmControlPanelState(StringBaseState):
    """Representation of a Home Assistant alarm_control_panel state.

    See: https://www.home-assistant.io/integrations/alarm_control_panel/
    """

    domain: Literal["alarm_control_panel"]

    attributes: AlarmControlPanelAttributes
