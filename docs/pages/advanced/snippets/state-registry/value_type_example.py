from typing import Any, ClassVar, Literal

from whenever import Time

from hassette.models.states import BaseState


class TimeBaseState(BaseState[Time | None]):
    """Base class for Time states.

    Valid state values are Time or None.
    """

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (Time, type(None))


class TimeState(TimeBaseState):
    """Representation of a Home Assistant time state.

    See: https://www.home-assistant.io/integrations/time/
    """

    domain: Literal["time"]
