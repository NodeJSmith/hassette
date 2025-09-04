from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class TextState(StringBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)
        min: int | float | None = Field(default=None)
        max: int | float | None = Field(default=None)
        pattern: Any | None = Field(default=None)
        mode: str | None = Field(default=None)

    domain: Literal["text"]

    attributes: Attributes
