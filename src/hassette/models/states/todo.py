from typing import Literal

from pydantic import Field

from .base import AttributesBase, BaseState


class TodoState(BaseState[int | float | None]):
    domain: Literal["todo"]

    attributes: AttributesBase | None = Field(default=None)
