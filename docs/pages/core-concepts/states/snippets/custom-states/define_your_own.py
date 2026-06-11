from enum import StrEnum
from typing import Any, ClassVar, Literal

from hassette.models.states.base import BaseState


class MyValueType(StrEnum):
    OPTION_A = "option_a"
    OPTION_B = "option_b"
    OPTION_C = "option_c"


class MyCustomState(BaseState[MyValueType]):
    domain: Literal["my_custom_domain"]

    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (
        MyValueType,
        type(None),
    )
