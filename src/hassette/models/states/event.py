from typing import Literal

from pydantic import Field

from .base import AttributesBase, InstantBaseState


class EventState(InstantBaseState):
    class Attributes(AttributesBase):
        event_types: list[str] | None = Field(default=None)
        event_type: str | None = Field(default=None)
        button: str | None = Field(default=None)

    domain: Literal["event"]

    attributes: Attributes
