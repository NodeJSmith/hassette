from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState
from .features import VacuumEntityFeature


class VacuumAttributes(AttributesBase):
    fan_speed_list: list[str] | None = Field(default=None)
    battery_level: int | float | None = Field(default=None)
    battery_icon: str | None = Field(default=None)
    fan_speed: str | None = Field(default=None)
    cleaned_area: int | float | None = Field(default=None)

    @property
    def supports_pause(self) -> bool:
        """Whether this vacuum supports pausing."""
        return self._has_feature(VacuumEntityFeature.PAUSE)

    @property
    def supports_stop(self) -> bool:
        """Whether this vacuum supports stopping."""
        return self._has_feature(VacuumEntityFeature.STOP)

    @property
    def supports_return_home(self) -> bool:
        """Whether this vacuum supports returning home."""
        return self._has_feature(VacuumEntityFeature.RETURN_HOME)

    @property
    def supports_fan_speed(self) -> bool:
        """Whether this vacuum supports fan speed control."""
        return self._has_feature(VacuumEntityFeature.FAN_SPEED)

    @property
    def supports_send_command(self) -> bool:
        """Whether this vacuum supports sending commands."""
        return self._has_feature(VacuumEntityFeature.SEND_COMMAND)

    @property
    def supports_locate(self) -> bool:
        """Whether this vacuum supports locating."""
        return self._has_feature(VacuumEntityFeature.LOCATE)

    @property
    def supports_clean_spot(self) -> bool:
        """Whether this vacuum supports spot cleaning."""
        return self._has_feature(VacuumEntityFeature.CLEAN_SPOT)

    @property
    def supports_start(self) -> bool:
        """Whether this vacuum supports starting."""
        return self._has_feature(VacuumEntityFeature.START)

    @property
    def supports_clean_area(self) -> bool:
        """Whether this vacuum supports area cleaning."""
        return self._has_feature(VacuumEntityFeature.CLEAN_AREA)


class VacuumState(StringBaseState):
    """Representation of a Home Assistant vacuum state.

    See: https://www.home-assistant.io/integrations/vacuum/
    """

    domain: Literal["vacuum"]

    attributes: VacuumAttributes
