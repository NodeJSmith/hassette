from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class DateTimeAttributes(AttributesBase):
    device_class: None = Field(default=None)
    state: None = Field(default=None)
    native_value: ZonedDateTime | None = Field(default=None)

    @field_validator("native_value", mode="before")
    @classmethod
    def _parse_datetime_fields(cls, value: object) -> object:
        return convert_datetime_str_to_system_tz(value)


class DateTimeState(StringBaseState):
    """Representation of a Home Assistant datetime state.

    See: https://www.home-assistant.io/integrations/datetime/
    """

    domain: Literal["datetime"]

    attributes: DateTimeAttributes
