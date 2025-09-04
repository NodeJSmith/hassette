from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class NotifyState(StringBaseState):
    domain: Literal["notify"]

    attributes: AttributesBase | None = Field(default=None)
