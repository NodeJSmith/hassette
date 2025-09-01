from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AutomationState(StringBaseState):
    class Attributes(AttributesBase):
        id: str | None = Field(default=None)
        last_triggered: str | None = Field(default=None)
        mode: str | None = Field(default=None)
        current: int | None = Field(default=None)
        max: int | None = Field(default=None)

    domain: Literal["automation"]

    attributes: Attributes | None = Field(default=None)
