from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AiTaskState(StringBaseState):
    domain: Literal["ai_task"]

    attributes: AttributesBase | None = Field(default=None)
