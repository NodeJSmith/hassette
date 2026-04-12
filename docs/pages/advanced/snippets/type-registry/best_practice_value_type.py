from typing import ClassVar

from hassette.models.states import BaseState


class CustomState(BaseState):
    # Explicitly define expected types
    value_type: ClassVar[type | tuple[type, ...]] = int
