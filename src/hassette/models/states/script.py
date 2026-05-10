from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, BoolBaseState


class ScriptAttributes(AttributesBase):
    last_triggered: ZonedDateTime | None = Field(default=None)
    mode: str | None = Field(default=None)
    current: int | float | None = Field(default=None)
    max: int | float | None = Field(default=None)
    last_action: str | None = Field(default=None)

    @field_validator("last_triggered", mode="before")
    @classmethod
    def _parse_datetime_fields(cls, value: str | ZonedDateTime | None) -> ZonedDateTime | None:
        return convert_datetime_str_to_system_tz(value)


class ScriptState(BoolBaseState):
    """Representation of a Home Assistant script state.

    See: https://www.home-assistant.io/integrations/script/
    """

    domain: Literal["script"]

    attributes: ScriptAttributes
