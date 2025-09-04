from typing import Literal

from pydantic import Field

from .base import AttributesBase, TimeBaseState


class TimeState(TimeBaseState):
    domain: Literal["time"]

    attributes: AttributesBase | None = Field(default=None)
