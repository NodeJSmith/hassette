from typing import Literal

from pydantic import Field

from .base import AttributesBase, DateTimeBaseState


class SceneState(DateTimeBaseState):
    """Representation of a Home Assistant scene state.

    See: https://www.home-assistant.io/integrations/scene/
    """

    class Attributes(AttributesBase):
        id: str | None = Field(default=None)

    domain: Literal["scene"]

    attributes: Attributes
