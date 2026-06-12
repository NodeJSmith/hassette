from typing import Literal

from hassette.models.states.base import DateTimeBaseState


class TimestampState(DateTimeBaseState):
    domain: Literal["timestamp"]
