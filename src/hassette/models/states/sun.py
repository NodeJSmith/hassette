from typing import Literal

from pydantic import Field, field_validator
from whenever import SystemDateTime

from hassette.utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class SunState(StringBaseState):
    class Attributes(AttributesBase):
        next_dawn: SystemDateTime | None = Field(default=None)
        next_dusk: SystemDateTime | None = Field(default=None)
        next_midnight: SystemDateTime | None = Field(default=None)
        next_noon: SystemDateTime | None = Field(default=None)
        next_rising: SystemDateTime | None = Field(default=None)
        next_setting: SystemDateTime | None = Field(default=None)
        elevation: float | None = Field(default=None)
        azimuth: float | None = Field(default=None)
        rising: bool | None = Field(default=None)

        @field_validator(
            "next_dawn", "next_dusk", "next_midnight", "next_noon", "next_rising", "next_setting", mode="before"
        )
        @classmethod
        def parse_datetime_fields(cls, value: SystemDateTime | str | None) -> SystemDateTime | None:
            return convert_datetime_str_to_system_tz(value)

    domain: Literal["sun"]

    attributes: Attributes
