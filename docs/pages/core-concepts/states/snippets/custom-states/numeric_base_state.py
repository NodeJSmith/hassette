from typing import Literal

from hassette.models.states.base import NumericBaseState


class CustomSensorState(NumericBaseState):
    domain: Literal["custom_sensor"]
