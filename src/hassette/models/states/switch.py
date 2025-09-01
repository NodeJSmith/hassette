from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SwitchState(StringBaseState):
    domain: Literal["switch"]

    attributes: AttributesBase | None = Field(default=None)
