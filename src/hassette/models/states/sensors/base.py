from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from hassette.models.states.base import AttributesBase, BaseState, StateValueT


class Sensor_AttributesBase(AttributesBase):
    device_class: str | None
    state_class: str | None = Field(default=None)
    unit_of_measurement: str | None = Field(default=None)


class Sensor_BaseState(BaseState[StateValueT]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    domain: Literal["sensor"]
    attributes: Sensor_AttributesBase | None = Field(default=None)


class Sensor_NumericBaseState(Sensor_BaseState[float | int | None]):
    """Base class for numeric sensor states."""

    @field_validator("value", mode="before")
    @classmethod
    def validate_numeric_state(cls, value):
        return float(value) if value is not None else None


class Sensor_StringBaseState(Sensor_BaseState[str | None]):
    """Base class for string sensor states."""

    @field_validator("value", mode="before")
    @classmethod
    def validate_string_state(cls, value):
        return str(value) if value is not None else None


class Sensor_BooleanBaseState(Sensor_BaseState[bool | None]):
    """Base class for boolean sensor states."""

    @field_validator("value", mode="before")
    @classmethod
    def validate_boolean_state(cls, value):
        if isinstance(value, str):
            return value.lower() == "on"
        return bool(value) if value is not None else None


class Sensor_FallbackState(Sensor_StringBaseState):
    """Base class for fallback sensor states."""

    class Attributes(Sensor_AttributesBase):
        device_class: Any | None = Field(default=None)

    attributes: Attributes | None = Field(default=None)
