from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class EventEntityCapabilityAttribute(StrEnum):
    EVENT_TYPES = "event_types"


class EventEntityStateAttribute(StrEnum):
    EVENT_TYPE = "event_type"


class DoorbellEventType(StrEnum):
    RING = "ring"


class ButtonEventType(StrEnum):
    PRESS_START = "press_start"
    PRESS_END = "press_end"
    LONG_PRESS_START = "long_press_start"
    LONG_PRESS_END = "long_press_end"
    MULTI_PRESS_ONGOING = "multi_press_ongoing"
    MULTI_PRESS_END = "multi_press_end"


class EventDeviceClass(StrEnum):
    DOORBELL = "doorbell"
    BUTTON = "button"
    MOTION = "motion"


class EventAttributes(AttributesBase):
    device_class: EventDeviceClass | None = Field(default=None)
    event_types: list[str] | None = Field(default=None)


class EventState(StringBaseState):
    """Representation of a Home Assistant event state.

    See: https://www.home-assistant.io/integrations/event/
    """

    domain: Literal["event"]

    attributes: EventAttributes
