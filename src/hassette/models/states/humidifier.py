from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class HumidifierState(StringBaseState):
    class Attributes(AttributesBase):
        min_humidity: int | None = Field(default=None)
        max_humidity: int | None = Field(default=None)
        available_modes: list[str] | None = Field(default=None)
        current_humidity: int | None = Field(default=None)
        humidity: int | None = Field(default=None)
        mode: str | None = Field(default=None)

    domain: Literal["humidifier"]

    attributes: Attributes | None = Field(default=None)
