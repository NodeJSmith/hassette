from typing import Literal

from hassette.models.states import BaseState


class LightAttributes(BaseState):  # simplified for example
    pass


class LightState(BaseState):
    """State model for light entities."""

    domain: Literal["light"]
    attributes: LightAttributes
