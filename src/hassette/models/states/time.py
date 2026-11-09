from enum import StrEnum
from typing import Literal

from pydantic import Field
from whenever import Time

from .base import AttributesBase, StringBaseState


class TimeService(StrEnum):
    SET_VALUE = "set_value"


class TimeServiceArgument(StrEnum):
    TIME = "time"


class TimeAttributes(AttributesBase):
    native_value: Time | None = Field(default=None)


class TimeState(StringBaseState):
    """Representation of a Home Assistant time state.

    See: https://www.home-assistant.io/integrations/time/
    """

    domain: Literal["time"]

    attributes: TimeAttributes
