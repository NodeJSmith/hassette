from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class SceneAttributes(AttributesBase):
    id: str | None = Field(default=None)


class SceneState(DateTimeBaseState):
    """Representation of a Home Assistant scene state.

    See: https://www.home-assistant.io/integrations/scene/
    """

    domain: Literal["scene"]

    attributes: SceneAttributes
