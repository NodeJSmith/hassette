from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ValveState(StringBaseState):
    domain: Literal["valve"]

    attributes: AttributesBase | None = Field(default=None)
