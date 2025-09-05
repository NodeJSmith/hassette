from typing import Literal

from pydantic import Field

from .base import AttributesBase, IntBaseState


class ZoneState(IntBaseState):
    class Attributes(AttributesBase):
        latitude: float | None = Field(default=None)
        longitude: float | None = Field(default=None)
        radius: float | None = Field(default=None)
        passive: bool | None = Field(default=None)
        persons: list[str] | None = Field(default=None)
        editable: bool | None = Field(default=None)

    domain: Literal["zone"]

    attributes: Attributes
