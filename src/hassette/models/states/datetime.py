from typing import Literal

from pydantic import Field
from whenever import ZonedDateTime

from .base import AttributesBase, StringBaseState


class DateTimeAttributes(AttributesBase):
    device_class: None = Field(default=None)
    state: None = Field(default=None)
    native_value: ZonedDateTime | None = Field(default=None)


class DateTimeState(StringBaseState):
    """Representation of a Home Assistant datetime state.

    See: https://www.home-assistant.io/integrations/datetime/
    """

    domain: Literal["datetime"]

    attributes: DateTimeAttributes
