from typing import ClassVar

from hassette.models.states import BaseState


class LightAttributes(BaseState):  # simplified for example
    pass


class LightState(BaseState):
    """State model for light entities."""

    domain: ClassVar[str] = "light"
    attributes: LightAttributes
