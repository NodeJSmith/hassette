from typing import Literal

from pydantic import Field

from .base import AttributesBase, BaseState


class NumberState(BaseState[int | float | None]):
    class Attributes(AttributesBase):
        min: int | float | None = Field(default=None)
        max: int | float | None = Field(default=None)
        step: int | float | None = Field(default=None)
        mode: str | None = Field(default=None)
        unit_of_measurement: str | None = Field(default=None)

    domain: Literal["number"]

    attributes: Attributes
