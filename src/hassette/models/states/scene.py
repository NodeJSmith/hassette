from typing import Literal

from .base import DateTimeBaseState


class SceneState(DateTimeBaseState):
    """Representation of a Home Assistant scene state.

    See: https://www.home-assistant.io/integrations/scene/
    """

    domain: Literal["scene"]
