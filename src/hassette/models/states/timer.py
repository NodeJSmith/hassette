from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class TimerAttributes(AttributesBase):
    duration: str | None = Field(default=None)
    editable: bool | None = Field(default=None)
    restore: bool | None = Field(default=None)


class TimerState(StringBaseState):
    """Representation of a Home Assistant timer state.

    See: https://www.home-assistant.io/integrations/timer/
    """

    domain: Literal["timer"]

    attributes: TimerAttributes
