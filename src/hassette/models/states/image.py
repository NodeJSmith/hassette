from typing import Literal

from pydantic import Field, field_validator
from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

from .base import AttributesBase, StringBaseState


class ImageAttributes(AttributesBase):
    content_type: str = Field(default=None)
    image_last_updated: ZonedDateTime | None = Field(default=None)
    image_url: str | None | object = Field(default=None)
    should_poll: bool = Field(default=None)

    @field_validator("image_last_updated", mode="before")
    @classmethod
    def _parse_datetime_fields(cls, value: object) -> object:
        return convert_datetime_str_to_system_tz(value)


class ImageState(StringBaseState):
    """Representation of a Home Assistant image state.

    See: https://www.home-assistant.io/integrations/image/
    """

    domain: Literal["image"]

    attributes: ImageAttributes
