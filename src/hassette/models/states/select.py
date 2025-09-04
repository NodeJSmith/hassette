from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SelectState(StringBaseState):
    class Attributes(AttributesBase):
        options: list[str] | None = Field(default=None)

    domain: Literal["select"]

    attributes: Attributes
