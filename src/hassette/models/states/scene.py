from typing import Literal

from pydantic import Field

from .base import AttributesBase, InstantBaseState


class SceneState(InstantBaseState):
    class Attributes(AttributesBase):
        entity_id: list[str] | None = Field(default=None)
        id: str | None = Field(default=None)

    domain: Literal["scene"]

    attributes: Attributes
