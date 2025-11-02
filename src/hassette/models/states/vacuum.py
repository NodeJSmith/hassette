from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class VacuumState(StringBaseState):
    """Representation of a Home Assistant vacuum state.

    See: https://www.home-assistant.io/integrations/vacuum/
    """

    class Attributes(AttributesBase):
        fan_speed_list: list[str] | None = Field(default=None)
        battery_level: int | float | None = Field(default=None)
        battery_icon: str | None = Field(default=None)
        fan_speed: str | None = Field(default=None)
        cleaned_area: int | float | None = Field(default=None)

    domain: Literal["vacuum"]

    attributes: Attributes
