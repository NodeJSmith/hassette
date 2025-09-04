from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class PersonState(StringBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)
        id: str | None = Field(default=None)
        device_trackers: list[str] | None = Field(default=None)
        source: str | None = Field(default=None)
        user_id: str | None = Field(default=None)
        entity_picture: str | None = Field(default=None)

    domain: Literal["person"]

    attributes: Attributes
