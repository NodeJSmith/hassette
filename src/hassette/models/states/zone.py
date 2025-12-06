from typing import Literal

from pydantic import Field

from .base import AttributesBase, NumericBaseState


class ZoneState(NumericBaseState):
    """Representation of a Home Assistant zone state.

    See: https://www.home-assistant.io/integrations/zone/
    """

    class Attributes(AttributesBase):
        latitude: float | None = Field(default=None)
        longitude: float | None = Field(default=None)
        radius: float | None = Field(default=None)
        passive: bool | None = Field(default=None)
        persons: list[str] | None = Field(default=None)
        editable: bool | None = Field(default=None)

    domain: Literal["zone"]

    attributes: Attributes
