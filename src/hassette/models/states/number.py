from typing import Literal

from pydantic import Field

from .base import AttributesBase, BaseState


class NumberState(BaseState[int | float | None]):
    class Attributes(AttributesBase):
        min: int | None = Field(default=None)
        max: int | None = Field(default=None)
        step: int | float | None = Field(default=None)
        mode: str | None = Field(default=None)
        unit_of_measurement: str | None = Field(default=None)
        device_class: str | None = Field(default=None)

    domain: Literal["number"]

    attributes: Attributes | None = Field(default=None)
