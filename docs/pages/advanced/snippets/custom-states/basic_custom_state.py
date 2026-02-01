from typing import Literal

from hassette.models.states.base import StringBaseState


class MyCustomState(StringBaseState):
    """State class for my_custom_domain entities."""

    domain: Literal["my_custom_domain"]
