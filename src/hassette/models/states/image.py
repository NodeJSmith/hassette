from typing import Literal

from pydantic import Field
from whenever import ZonedDateTime

from .base import AttributesBase, StringBaseState


class ImageAttributes(AttributesBase):
    content_type: str = Field(default=None)
    image_last_updated: ZonedDateTime | None = Field(default=None)
    image_url: str | None | object = Field(default=None)
    should_poll: bool = Field(default=None)
    state: None = Field(default=None)


class ImageState(StringBaseState):
    """Representation of a Home Assistant image state.

    See: https://www.home-assistant.io/integrations/image/
    """

    domain: Literal["image"]

    attributes: ImageAttributes
