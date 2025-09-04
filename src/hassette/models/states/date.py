from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class DateState(DateTimeBaseState):
    domain: Literal["date"]

    attributes: AttributesBase | None = Field(default=None)
