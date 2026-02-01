from typing import Literal

from pydantic import Field

from hassette.const.sensor import UNIT_OF_MEASUREMENT

from .base import AttributesBase, NumericBaseState


class NumberAttributes(AttributesBase):
    min: int | float | None = Field(default=None)
    max: int | float | None = Field(default=None)
    step: int | float | None = Field(default=None)
    mode: str | None = Field(default=None)
    unit_of_measurement: UNIT_OF_MEASUREMENT | str | None = Field(default=None)


class NumberState(NumericBaseState):
    """Representation of a Home Assistant number state.

    See: https://www.home-assistant.io/integrations/number/
    """

    domain: Literal["number"]

    attributes: NumberAttributes
