from typing import Literal

from pydantic import field_validator

from hassette.models.states.base import BaseState


class BinarySensorState(BaseState[bool | None]):
    domain: Literal["binary_sensor"]

    @field_validator("value")
    @classmethod
    def validate_state(cls, value):
        if value is None:
            return value

        if isinstance(value, str):
            if value.lower() == "on":
                return True
            if value.lower() == "off":
                return False
            raise ValueError(f"Invalid state value: {value}")
        if isinstance(value, bool):
            return value
        raise ValueError(f"State must be a boolean or 'on'/'off' string, got {value}")
