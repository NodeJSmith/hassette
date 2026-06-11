from typing import Literal

from hassette.models.states.base import BoolBaseState


class CustomBinaryState(BoolBaseState):
    domain: Literal["custom_binary"]
