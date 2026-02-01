from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class LightAttributes(AttributesBase):
    effect_list: list[str] | None = Field(default=None)
    """The list of supported effects."""

    supported_color_modes: set[str] | None = Field(default=None)
    """Flag supported color modes."""

    effect: str | None = Field(default=None)
    """The current effect."""

    color_mode: str | None = Field(default=None)
    """The color mode of the light with backwards compatibility."""

    brightness: int | None = Field(default=None, gt=-1, lt=256)
    """The brightness of this light between 0..255."""

    color_temp_kelvin: int | None = Field(default=None)
    """The CT color value in Kelvin."""

    min_color_temp_kelvin: int | None = Field(default=None)
    """The warmest color_temp_kelvin that this light supports."""

    max_color_temp_kelvin: int | None = Field(default=None)
    """The coldest color_temp_kelvin that this light supports."""

    hs_color: tuple[float, float] | None = Field(default=None)
    """The hue and saturation color value."""

    rgb_color: tuple[int, int, int] | None = Field(default=None)
    """The rgb color value."""

    xy_color: list[float] | None = Field(default=None)
    """The x and y color value."""

    min_mireds: int | None = Field(default=None, deprecated=True)
    """Deprecated: The coldest color_temp that this light supports."""

    max_mireds: int | None = Field(default=None, deprecated=True)
    """Deprecated: The warmest color_temp that this light supports."""

    color_temp: int | None = Field(default=None, deprecated=True)
    """Deprecated: The CT color value in mireds."""


class LightState(StringBaseState):
    """Representation of a Home Assistant light state.

    See: https://www.home-assistant.io/integrations/light/
    """

    domain: Literal["light"]

    attributes: LightAttributes
