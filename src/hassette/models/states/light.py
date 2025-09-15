from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class LightState(StringBaseState):
    class Attributes(AttributesBase):
        min_color_temp_kelvin: int | float | None = Field(default=None)
        max_color_temp_kelvin: int | float | None = Field(default=None)
        min_mireds: int | float | None = Field(default=None)
        max_mireds: int | float | None = Field(default=None)
        effect_list: list[str] | None = Field(default=None)
        supported_color_modes: list[str] | None = Field(default=None)
        effect: Any | None = Field(default=None)
        color_mode: str | None = Field(default=None)
        brightness: int | float | None = Field(default=None)
        color_temp_kelvin: int | float | None = Field(default=None)
        color_temp: int | float | None = Field(default=None)
        hs_color: list[float] | None = Field(default=None)
        rgb_color: list[int] | None = Field(default=None)
        xy_color: list[float] | None = Field(default=None)

    domain: Literal["light"]

    attributes: Attributes
