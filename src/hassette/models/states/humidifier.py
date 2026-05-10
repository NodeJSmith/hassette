from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class HumidifierAction(StrEnum):
    HUMIDIFYING = "humidifying"
    DRYING = "drying"
    IDLE = "idle"
    OFF = "off"


class HumidifierDeviceClass(StrEnum):
    HUMIDIFIER = "humidifier"
    DEHUMIDIFIER = "dehumidifier"


class HumidifierEntityFeature(IntFlag):
    MODES = 1


class HumidifierAttributes(AttributesBase):
    action: HumidifierAction | None = Field(default=None)
    available_modes: list[str] | None = Field(default=None)
    current_humidity: float | None = Field(default=None)
    device_class: HumidifierDeviceClass | None = Field(default=None)
    max_humidity: float = Field(default=None)
    min_humidity: float = Field(default=None)
    mode: str | None = Field(default=None)
    target_humidity: float | None = Field(default=None)
    target_humidity_step: float | None = Field(default=None)

    @property
    def supports_modes(self) -> bool:
        return self._has_feature(HumidifierEntityFeature.MODES)


class HumidifierState(BoolBaseState):
    """Representation of a Home Assistant humidifier state.

    See: https://www.home-assistant.io/integrations/humidifier/
    """

    domain: Literal["humidifier"]

    attributes: HumidifierAttributes
