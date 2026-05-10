from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, BoolBaseState


class SwitchDeviceClass(StrEnum):
    OUTLET = "outlet"
    SWITCH = "switch"


class SwitchAttributes(AttributesBase):
    device_class: SwitchDeviceClass | None = Field(default=None)


class SwitchState(BoolBaseState):
    """Representation of a Home Assistant switch state.

    See: https://www.home-assistant.io/integrations/switch/
    """

    domain: Literal["switch"]

    attributes: SwitchAttributes
