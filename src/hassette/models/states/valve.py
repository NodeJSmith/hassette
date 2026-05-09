from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ValveAttributes(AttributesBase):
    is_closed: bool | None = Field(default=None)
    current_position: int | None = Field(default=None)


class ValveState(StringBaseState):
    """Representation of a Home Assistant valve state.

    See: https://www.home-assistant.io/integrations/valve/
    """

    domain: Literal["valve"]

    attributes: ValveAttributes
