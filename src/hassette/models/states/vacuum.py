from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class VacuumState(StringBaseState):
    class Attributes(AttributesBase):
        fan_speed_list: list[str] | None = Field(default=None)
        battery_level: int | float | None = Field(default=None)
        battery_icon: str | None = Field(default=None)
        fan_speed: str | None = Field(default=None)
        cleaned_area: int | float | None = Field(default=None)

    domain: Literal["vacuum"]

    attributes: Attributes
