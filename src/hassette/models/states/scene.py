from typing import Literal

from pydantic import Field
from whenever import Instant

from .base import AttributesBase, BaseState


class SceneState(BaseState[Instant | None]):
    class Attributes(AttributesBase):
        entity_id: list[str] | None = Field(default=None)
        id: str | None = Field(default=None)

    domain: Literal["scene"]

    attributes: Attributes
