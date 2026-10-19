from typing import Literal

from .base import AttributesBase, DateTimeBaseState


class WakeWordAttributes(AttributesBase):
    pass


class WakeWordState(DateTimeBaseState):
    """Representation of a Home Assistant wake_word state.

    See: https://www.home-assistant.io/integrations/wake_word/
    """

    domain: Literal["wake_word"]

    attributes: WakeWordAttributes
