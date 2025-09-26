from typing import Literal

from pydantic import Field, field_validator
from whenever import OffsetDateTime, SystemDateTime

from .base import AttributesBase, StringBaseState


class ScriptState(StringBaseState):
    class Attributes(AttributesBase):
        last_triggered: SystemDateTime | None = Field(default=None)
        mode: str | None = Field(default=None)
        current: int | float | None = Field(default=None)

        @field_validator("last_triggered", mode="before")
        @classmethod
        def parse_last_triggered(cls, value: SystemDateTime | str | None) -> SystemDateTime | None:
            if isinstance(value, str):
                return OffsetDateTime.parse_common_iso(value).to_system_tz()
            return value

    domain: Literal["script"]

    attributes: Attributes
