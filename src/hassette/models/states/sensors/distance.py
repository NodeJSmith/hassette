from typing import Literal

from pydantic import Field, field_validator

from .base import Sensor_AttributesBase, Sensor_BaseState


class Sensor_DistanceState(Sensor_BaseState[int | float | None]):
    class Attributes(Sensor_AttributesBase):
        device_class: Literal["distance"]

        attribution: str | None = Field(default=None)
        current_mac: str | None = Field(default=None)
        restored: bool | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: int | float | None) -> int | float | None:
        """Ensure the state value is a number or None."""
        if value is None:
            return None
        if isinstance(value, int | float):
            return value
        return float(value)
