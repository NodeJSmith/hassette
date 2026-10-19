from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class TagAttributes(AttributesBase):
    tag_id: str | None = Field(default=None)
    last_scanned_by_device_id: str | None = Field(default=None)


class TagState(DateTimeBaseState):
    """Representation of a Home Assistant tag state.

    See: https://www.home-assistant.io/integrations/tag/
    """

    domain: Literal["tag"]

    attributes: TagAttributes
