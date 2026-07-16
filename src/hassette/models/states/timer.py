from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_tz

from .base import AttributesBase, StringBaseState


class TimerAttributes(AttributesBase):
    duration: str | None = Field(default=None)
    editable: bool | None = Field(default=None)
    last_transition: ZonedDateTime | None = Field(default=None)
    finishes_at: ZonedDateTime | None = Field(default=None)
    remaining: str | None = Field(default=None)
    restore: bool | None = Field(default=None)

    @field_validator("last_transition", "finishes_at", mode="before")
    @classmethod
    def _parse_datetime_fields(cls, value: str | ZonedDateTime | None) -> ZonedDateTime | None:
        return convert_datetime_str_to_tz(value)


class TimerState(StringBaseState):
    """Representation of a Home Assistant timer state.

    See: https://www.home-assistant.io/integrations/timer/
    """

    domain: Literal["timer"]

    attributes: TimerAttributes
