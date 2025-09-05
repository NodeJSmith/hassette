from typing import Literal

from pydantic import Field
from whenever import Instant

from .base import AttributesBase, StringBaseState


class AutomationState(StringBaseState):
    class Attributes(AttributesBase):
        id: str | None = Field(default=None)
        last_triggered: Instant | None = Field(default=None)
        mode: str | None = Field(default=None)
        current: int | float | None = Field(default=None)
        max: int | float | None = Field(default=None)

    domain: Literal["automation"]

    attributes: Attributes
