from logging import getLogger
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from whenever import Date, Instant, PlainDateTime, Time

DomainLiteral = Literal[
    "automation",
    "binary_sensor",
    "button",
    "calendar",
    "climate",
    "conversation",
    "cover",
    "device_tracker",
    "event",
    "fan",
    "humidifier",
    "input_boolean",
    "input_datetime",
    "input_number",
    "input_text",
    "light",
    "media_player",
    "number",
    "person",
    "remote",
    "scene",
    "script",
    "select",
    "sensor",
    "stt",
    "sun",
    "switch",
    "timer",
    "tts",
    "update",
    "weather",
    "zone",
]


StateT = TypeVar("StateT", bound="BaseState")
"""Represents a specific state type, e.g., LightState, Sensor_TemperatureState, etc."""

StateValueT = TypeVar("StateValueT")
"""Represents the type of the state attribute in a State model, e.g. bool for BinarySensorState."""


LOGGER = getLogger(__name__)


class Context(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str | None = Field(default=None)
    """The context ID of the event."""

    parent_id: str | None = Field(default=None)
    """The parent context ID of the event, if any."""

    user_id: str | None = Field(default=None)
    """The user ID for who triggered the event."""


class AttributesBase(BaseModel):
    """Represents the attributes of a HomeAssistant state."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True, coerce_numbers_to_str=True, frozen=True)

    icon: str | None = Field(default=None, repr=False)
    """The icon of the entity."""

    friendly_name: str | None = Field(default=None)
    """A friendly name for the entity."""

    device_class: str | None = Field(default=None)
    """The device class of the entity."""

    entity_id: list[str] | None = Field(default=None)
    """List of entity IDs if this is a group entity."""

    supported_features: int | float | None = Field(default=None)
    """Bitfield of supported features."""


class BaseState(BaseModel, Generic[StateValueT]):
    """Represents a Home Assistant state object."""

    # Note: HA docs mention object_id and name, but I personally haven't seen these in practice.
    # Leaving them off unless we find a use case or get a feature request for them.
    # https://www.home-assistant.io/docs/configuration/state_object/#about-the-state-object

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True, coerce_numbers_to_str=True, frozen=True)

    domain: DomainLiteral | str = Field(...)
    """The domain of the entity, e.g. 'light', 'sensor', etc."""

    entity_id: str = Field(...)
    """The full entity ID, e.g. 'light.living_room'."""

    last_changed: Instant | None = Field(None, repr=False)
    """Time the state changed in the state machine, not updated when only attributes change."""

    last_reported: Instant | None = Field(None, repr=False)
    """Time the state was written to the state machine, updated regardless of any changes to the state or
    state attributes.
    """

    last_updated: Instant | None = Field(None, repr=False)
    """Time the state or state attributes changed in the state machine, not updated if neither state nor state
    attributes changed.
    """

    context: Context = Field(repr=False)
    """The context of the state change."""

    is_unknown: bool = Field(default=False)
    """Whether the state is 'unknown'."""

    is_unavailable: bool = Field(default=False)
    """Whether the state is 'unavailable'."""

    value: StateValueT = Field(..., validation_alias="state")
    """The state value, e.g. 'on', 'off', 23.5, etc."""

    attributes: AttributesBase = Field(...)
    """The attributes of the state."""

    @property
    def is_group(self) -> bool:
        """Whether this entity is a group entity (i.e. has multiple entity_ids)."""
        if not self.attributes:
            return False

        if not hasattr(self.attributes, "entity_id"):
            return False

        if not isinstance(self.attributes.entity_id, list):  # type: ignore
            return False

        return len(self.attributes.entity_id) > 1  # type: ignore

    @model_validator(mode="before")
    @classmethod
    def _validate_domain_and_state(cls, values):
        if not isinstance(values, dict):
            LOGGER.warning("Expected values to be a dict, got %s", type(values).__name__, stacklevel=2)
            return values

        entity_id = values.get("entity_id")
        if entity_id:
            domain = entity_id.split(".")[0]
            values["domain"] = domain

        state = values.get("state")
        if state == "unknown":
            values["is_unknown"] = True
            values["state"] = None
        elif state == "unavailable":
            values["is_unavailable"] = True
            values["state"] = None

        return values


class StringBaseState(BaseState[str | None]):
    """Base class for string states."""


class DateTimeBaseState(BaseState[Instant | PlainDateTime | Date | None]):
    """Base class for datetime states.

    Valid state values are Instant, PlainDateTime, Date, or None.
    """


class TimestampBaseState(BaseState[Instant | PlainDateTime | None]):
    """Base class for timestamp states.

    Valid state values are Instant, PlainDateTime, or None.
    """


class InstantBaseState(BaseState[Instant | None]):
    """Base class for Instant states.

    Valid state values are Instant or None.
    """


class TimeBaseState(BaseState[Time | None]):
    """Base class for Time states.

    Valid state values are Time or None.
    """


class BoolBaseState(BaseState[bool | None]):
    """Base class for boolean states.

    Valids state values are True, False, or None.

    Will convert string values "on" and "off" to boolean True and False.
    """

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            if value.lower() == "on":
                return True
            if value.lower() == "off":
                return False
            raise ValueError(f"Invalid state value: {value}")
        if isinstance(value, bool):
            return value
        raise ValueError(f"State must be a boolean or 'on'/'off' string, got {value}")


class IntBaseState(BaseState[int | None]):
    """Base class for integer states."""

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: int | None) -> int | None:
        """Ensure the state value is an integer or None."""
        if value is None:
            return None
        return int(value)


class NumericBaseState(BaseState[float | int | None]):
    """Base class for numeric states.

    Will convert string values to float or int.
    Valid state values are int, float, or None.
    """

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: int | float | None) -> int | float | None:
        """Ensure the state value is a number or None."""
        if value is None:
            return None
        if isinstance(value, int | float):
            return value
        return float(value)
