from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class DoorbellEventType(StrEnum):
    RING = "ring"


class EventDeviceClass(StrEnum):
    DOORBELL = "doorbell"
    BUTTON = "button"
    MOTION = "motion"


class EventAttributes(AttributesBase):
    device_class: EventDeviceClass | None = Field(default=None)
    event_types: list[str] | None = Field(default=None)
    state: None = Field(default=None)


class EventState(StringBaseState):
    """Representation of a Home Assistant event state.

    See: https://www.home-assistant.io/integrations/event/
    """

    domain: Literal["event"]

    attributes: EventAttributes
