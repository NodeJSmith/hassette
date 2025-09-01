from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class InputTextState(StringBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)
        min: int | None = Field(default=None)
        max: int | None = Field(default=None)
        pattern: None = Field(default=None)
        mode: str | None = Field(default=None)

    domain: Literal["input_text"]

    attributes: Attributes | None = Field(default=None)
