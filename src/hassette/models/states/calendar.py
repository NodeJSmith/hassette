from typing import Literal

from pydantic import Field
from whenever import Instant, PlainDateTime, ZonedDateTime

from .base import AttributesBase, StringBaseState


class CalendarState(StringBaseState):
    """Representation of a Home Assistant calendar state.

    See: https://www.home-assistant.io/integrations/calendar/
    """

    class Attributes(AttributesBase):
        message: str | None = Field(default=None)
        all_day: bool | None = Field(default=None)
        start_time: Instant | PlainDateTime | ZonedDateTime | None = Field(default=None)
        end_time: Instant | PlainDateTime | ZonedDateTime | None = Field(default=None)
        location: str | None = Field(default=None)
        description: str | None = Field(default=None)
        offset_reached: bool | None = Field(default=None)

    domain: Literal["calendar"]

    attributes: Attributes
