from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class InputBooleanState(BoolBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)

    domain: Literal["input_boolean"]

    attributes: Attributes
