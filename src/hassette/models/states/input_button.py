from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class InputButtonState(DateTimeBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)

    domain: Literal["input_button"]

    attributes: Attributes
