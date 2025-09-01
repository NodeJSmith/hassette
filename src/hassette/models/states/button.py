from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ButtonState(StringBaseState):
    class Attributes(AttributesBase):
        device_class: str | None = Field(default=None)

    domain: Literal["button"]

    attributes: Attributes | None = Field(default=None)
