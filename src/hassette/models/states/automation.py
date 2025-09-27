from typing import Literal

from pydantic import Field, field_validator
from whenever import SystemDateTime

from hassette.utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class AutomationState(StringBaseState):
    class Attributes(AttributesBase):
        id: str | None = Field(default=None)
        last_triggered: SystemDateTime | None = Field(default=None)
        mode: str | None = Field(default=None)
        current: int | float | None = Field(default=None)
        max: int | float | None = Field(default=None)

        @field_validator("last_triggered", mode="before")
        @classmethod
        def parse_last_triggered(cls, value: SystemDateTime | str | None) -> SystemDateTime | None:
            return convert_datetime_str_to_system_tz(value)

    domain: Literal["automation"]

    attributes: Attributes
