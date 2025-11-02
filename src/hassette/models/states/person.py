from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class PersonState(StringBaseState):
    """Representation of a Home Assistant person state.

    See: https://www.home-assistant.io/integrations/person/
    """

    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)
        id: str | None = Field(default=None)
        device_trackers: list[str] | None = Field(default=None)
        source: str | None = Field(default=None)
        user_id: str | None = Field(default=None)
        entity_picture: str | None = Field(default=None)

    domain: Literal["person"]

    attributes: Attributes
