from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class DateTimeState(DateTimeBaseState):
    domain: Literal["datetime"]

    attributes: AttributesBase | None = Field(default=None)
