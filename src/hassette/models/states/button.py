from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ButtonDeviceClass(StrEnum):
    IDENTIFY = "identify"
    RESTART = "restart"
    UPDATE = "update"


class ButtonAttributes(AttributesBase):
    device_class: ButtonDeviceClass | None = Field(default=None)
    state: None = Field(default=None)


class ButtonState(StringBaseState):
    """Representation of a Home Assistant button state.

    See: https://www.home-assistant.io/integrations/button/
    """

    domain: Literal["button"]

    attributes: ButtonAttributes
