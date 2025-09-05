from typing import Literal

from pydantic import Field
from whenever import Instant

from .base import AttributesBase, StringBaseState


class ScriptState(StringBaseState):
    class Attributes(AttributesBase):
        last_triggered: Instant | None = Field(default=None)
        mode: str | None = Field(default=None)
        current: int | float | None = Field(default=None)

    domain: Literal["script"]

    attributes: Attributes
