from typing import Literal

from pydantic import Field
from whenever import Date

from .base import AttributesBase, StringBaseState


class DateAttributes(AttributesBase):
    native_value: Date | None = Field(default=None)


class DateState(StringBaseState):
    """Representation of a Home Assistant date state.

    See: https://www.home-assistant.io/integrations/date/
    """

    domain: Literal["date"]

    attributes: DateAttributes
