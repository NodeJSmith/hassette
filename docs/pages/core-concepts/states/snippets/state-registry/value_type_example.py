from typing import Any, ClassVar, Literal

from hassette.models.states import BaseState


class BoolBaseState(BaseState[bool | None]):
    """Base class for boolean states.

    Valid state values are True, False, or None.
    Converts the strings "on" and "off" to True and False.
    """

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (bool, type(None))


class BinarySensorState(BoolBaseState):
    """Representation of a Home Assistant binary_sensor state.

    See: https://www.home-assistant.io/integrations/binary_sensor/
    """

    domain: Literal["binary_sensor"]
