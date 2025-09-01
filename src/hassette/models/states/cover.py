from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class CoverState(StringBaseState):
    class Attributes(AttributesBase):
        device_class: str | None = Field(default=None)

    domain: Literal["cover"]

    attributes: Attributes | None = Field(default=None)
