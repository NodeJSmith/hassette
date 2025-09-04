from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class HumidifierState(StringBaseState):
    class Attributes(AttributesBase):
        min_humidity: float | None = Field(default=None)
        max_humidity: float | None = Field(default=None)
        available_modes: list[str] | None = Field(default=None)
        current_humidity: float | None = Field(default=None)
        humidity: float | None = Field(default=None)
        mode: str | None = Field(default=None)
        action: str | None = Field(default=None)

    domain: Literal["humidifier"]

    attributes: Attributes
