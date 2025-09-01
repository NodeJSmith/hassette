from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ConversationState(StringBaseState):
    domain: Literal["conversation"]

    attributes: AttributesBase | None = Field(default=None)
