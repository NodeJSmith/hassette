from typing import Literal

from pydantic import Field

from .base import AttributesBase, InstantBaseState


class SceneState(InstantBaseState):
    class Attributes(AttributesBase):
        id: str | None = Field(default=None)

    domain: Literal["scene"]

    attributes: Attributes
