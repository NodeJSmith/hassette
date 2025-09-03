from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class InputSelectState(StringBaseState):
    class Attributes(AttributesBase):
        editable: bool | None = Field(default=None)
        options: list[str] = Field(default_factory=list)

    domain: Literal["input_select"]

    attributes: Attributes | None = Field(default=None)

    def model_post_init(self, context: Any) -> None:
        return super().model_post_init(context)
