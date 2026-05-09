from typing import Literal

from .base import StringBaseState


class AssistSatelliteState(StringBaseState):
    """Representation of a Home Assistant assist_satellite state.

    See: https://www.home-assistant.io/integrations/assist_satellite/
    """

    domain: Literal["assist_satellite"]
