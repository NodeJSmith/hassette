from typing import Literal

from .base import AttributesBase, DateTimeBaseState


class RadioFrequencyAttributes(AttributesBase):
    pass


class RadioFrequencyState(DateTimeBaseState):
    """Representation of a Home Assistant radio_frequency state.

    See: https://www.home-assistant.io/integrations/radio_frequency/
    """

    domain: Literal["radio_frequency"]

    attributes: RadioFrequencyAttributes
