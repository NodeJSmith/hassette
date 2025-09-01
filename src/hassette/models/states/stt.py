from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SttState(StringBaseState):
    domain: Literal["stt"]

    attributes: AttributesBase | None = Field(default=None)
