from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class SunState(StringBaseState):
    """Representation of a Home Assistant sun state.

    See: https://www.home-assistant.io/integrations/sun/
    """

    class Attributes(AttributesBase):
        next_dawn: ZonedDateTime | None = Field(default=None)
        next_dusk: ZonedDateTime | None = Field(default=None)
        next_midnight: ZonedDateTime | None = Field(default=None)
        next_noon: ZonedDateTime | None = Field(default=None)
        next_rising: ZonedDateTime | None = Field(default=None)
        next_setting: ZonedDateTime | None = Field(default=None)
        elevation: float | None = Field(default=None)
        azimuth: float | None = Field(default=None)
        rising: bool | None = Field(default=None)

        @field_validator(
            "next_dawn", "next_dusk", "next_midnight", "next_noon", "next_rising", "next_setting", mode="before"
        )
        @classmethod
        def parse_datetime_fields(cls, value: ZonedDateTime | str | None) -> ZonedDateTime | None:
            return convert_datetime_str_to_system_tz(value)

    domain: Literal["sun"]

    attributes: Attributes
