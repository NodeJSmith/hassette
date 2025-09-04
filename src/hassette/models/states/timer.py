from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class TimerState(StringBaseState):
    class Attributes(AttributesBase):
        duration: str | None = Field(default=None)
        editable: bool | None = Field(default=None)
        restore: bool | None = Field(default=None)

    domain: Literal["timer"]

    attributes: Attributes
