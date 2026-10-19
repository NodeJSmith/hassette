from typing import Literal

from .base import AttributesBase, DateTimeBaseState


class InfraredAttributes(AttributesBase):
    pass


class InfraredState(DateTimeBaseState):
    """Representation of a Home Assistant infrared state.

    See: https://www.home-assistant.io/integrations/infrared/
    """

    domain: Literal["infrared"]

    attributes: InfraredAttributes
