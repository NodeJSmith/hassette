from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AssistSatelliteAttributes(AttributesBase):
    restored: bool | None = Field(default=None)


class AssistSatelliteState(StringBaseState):
    """Representation of a Home Assistant assist_satellite state.

    See: https://www.home-assistant.io/integrations/assist_satellite/
    """

    domain: Literal["assist_satellite"]

    attributes: AssistSatelliteAttributes
