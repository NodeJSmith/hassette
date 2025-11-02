from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class AssistSatelliteState(StringBaseState):
    """Representation of a Home Assistant assist_satellite state.

    See: https://www.home-assistant.io/integrations/assist_satellite/
    """

    class Attributes(AttributesBase):
        restored: bool | None = Field(default=None)

    domain: Literal["assist_satellite"]

    attributes: Attributes
