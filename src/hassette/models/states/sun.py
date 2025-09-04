from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SunState(StringBaseState):
    class Attributes(AttributesBase):
        next_dawn: str | None = Field(default=None)
        next_dusk: str | None = Field(default=None)
        next_midnight: str | None = Field(default=None)
        next_noon: str | None = Field(default=None)
        next_rising: str | None = Field(default=None)
        next_setting: str | None = Field(default=None)
        elevation: float | None = Field(default=None)
        azimuth: float | None = Field(default=None)
        rising: bool | None = Field(default=None)

    domain: Literal["sun"]

    attributes: Attributes
