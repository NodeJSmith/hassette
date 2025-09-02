from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class InputSelectState(StringBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)

    domain: Literal["input_select"]

    attributes: Attributes | None = Field(default=None)
