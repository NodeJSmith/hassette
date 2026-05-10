from enum import IntFlag, StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class ColorMode(StrEnum):
    UNKNOWN = "unknown"
    ONOFF = "onoff"
    BRIGHTNESS = "brightness"
    COLOR_TEMP = "color_temp"
    HS = "hs"
    XY = "xy"
    RGB = "rgb"
    RGBW = "rgbw"
    RGBWW = "rgbww"
    WHITE = "white"


class LightEntityFeature(IntFlag):
    EFFECT = 4
    FLASH = 8
    TRANSITION = 32


class LightAttributes(AttributesBase):
    brightness: int | None = Field(default=None)
    color_mode: ColorMode | None = Field(default=None)
    color_temp_kelvin: int | None = Field(default=None)
    effect_list: list[str] | None = Field(default=None)
    effect: str | None = Field(default=None)
    hs_color: tuple[float, float] | None = Field(default=None)
    max_color_temp_kelvin: int | None = Field(default=None)
    min_color_temp_kelvin: int | None = Field(default=None)
    rgb_color: tuple[int, int, int] | None = Field(default=None)
    rgbw_color: tuple[int, int, int, int] | None = Field(default=None)
    rgbww_color: tuple[int, int, int, int, int] | None = Field(default=None)
    supported_color_modes: set[ColorMode] | None = Field(default=None)
    xy_color: tuple[float, float] | None = Field(default=None)

    @property
    def supports_effect(self) -> bool:
        return self._has_feature(LightEntityFeature.EFFECT)

    @property
    def supports_flash(self) -> bool:
        return self._has_feature(LightEntityFeature.FLASH)

    @property
    def supports_transition(self) -> bool:
        return self._has_feature(LightEntityFeature.TRANSITION)


class LightState(BoolBaseState):
    """Representation of a Home Assistant light state.

    See: https://www.home-assistant.io/integrations/light/
    """

    domain: Literal["light"]

    attributes: LightAttributes
