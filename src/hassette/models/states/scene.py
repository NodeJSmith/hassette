from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class SceneState(DateTimeBaseState):
    class Attributes(AttributesBase):
        id: str | None = Field(default=None)

    domain: Literal["scene"]

    attributes: Attributes
