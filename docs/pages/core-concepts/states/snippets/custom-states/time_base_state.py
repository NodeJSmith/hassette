from typing import Literal

from hassette.models.states.base import TimeBaseState


class TimeOnlyState(TimeBaseState):
    domain: Literal["time_only"]
