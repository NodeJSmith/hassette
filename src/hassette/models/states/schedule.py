from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_tz

from .base import AttributesBase, StringBaseState


class ScheduleAttributes(AttributesBase):
    next_event: ZonedDateTime | None = Field(default=None)

    @field_validator("next_event", mode="before")
    @classmethod
    def _parse_datetime_fields(cls, value: str | ZonedDateTime | None) -> ZonedDateTime | None:
        return convert_datetime_str_to_tz(value)


class ScheduleState(StringBaseState):
    """Representation of a Home Assistant schedule state.

    See: https://www.home-assistant.io/integrations/schedule/
    """

    domain: Literal["schedule"]

    attributes: ScheduleAttributes
