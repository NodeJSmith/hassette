from typing import Literal

from pydantic import Field
from whenever import Time

from .base import AttributesBase, StringBaseState


class TimeAttributes(AttributesBase):
    native_value: Time | None = Field(default=None)
    device_class: None = Field(default=None)
    state: None = Field(default=None)


class TimeState(StringBaseState):
    """Representation of a Home Assistant time state.

    See: https://www.home-assistant.io/integrations/time/
    """

    domain: Literal["time"]

    attributes: TimeAttributes
