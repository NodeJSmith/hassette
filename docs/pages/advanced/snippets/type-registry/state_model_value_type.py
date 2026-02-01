from typing import ClassVar

from hassette.models.states.base import BaseState


class SensorState(BaseState):
    """State model for sensor entities."""

    value_type: ClassVar[type | tuple[type, ...]] = (str, int, float)
