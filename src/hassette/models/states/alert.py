from typing import Literal

from .base import AttributesBase, StringBaseState


class AlertAttributes(AttributesBase):
    pass


class AlertState(StringBaseState):
    """Representation of a Home Assistant alert state.

    See: https://www.home-assistant.io/integrations/alert/
    """

    domain: Literal["alert"]

    attributes: AlertAttributes
