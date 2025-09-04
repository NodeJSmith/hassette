from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class RemoteState(StringBaseState):
    class Attributes(AttributesBase):
        activity_list: list | None = Field(default=None)
        current_activity: str | None = Field(default=None)

    domain: Literal["remote"]

    attributes: Attributes
