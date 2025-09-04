from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class FanState(StringBaseState):
    class Attributes(AttributesBase):
        preset_modes: list[str] | None = Field(default=None)
        oscillating: bool | None = Field(default=None)
        percentage: int | float | None = Field(default=None)
        percentage_step: float | None = Field(default=None)
        preset_mode: str | None = Field(default=None)
        temperature: int | float | None = Field(default=None)
        model: str | None = Field(default=None)
        sn: str | None = Field(default=None)
        screen_status: bool | None = Field(default=None)
        child_lock: bool | None = Field(default=None)
        night_light: str | None = Field(default=None)
        mode: str | None = Field(default=None)

    domain: Literal["fan"]

    attributes: Attributes
