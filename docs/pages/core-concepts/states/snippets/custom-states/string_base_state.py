from typing import Literal

from hassette.models.states.base import StringBaseState


class LauncherState(StringBaseState):
    domain: Literal["launcher"]
