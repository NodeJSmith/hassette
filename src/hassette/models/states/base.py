from logging import getLogger
from typing import Any, Generic, Literal, TypeVar, get_args

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from whenever import Date, PlainDateTime, Time, ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz, convert_utc_timestamp_to_system_tz

DomainLiteral = Literal[
    "ai_task",
    "air_quality",
    "alarm_control_panel",
    "assist_satellite",
    "automation",
    "binary_sensor",
    "button",
    "calendar",
    "camera",
    "climate",
    "conversation",
    "cover",
    "date",
    "datetime",
    "device_tracker",
    "event",
    "fan",
    "humidifier",
    "image_processing",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "light",
    "lock",
    "media_player",
    "notify",
    "number",
    "person",
    "remote",
    "scene",
    "script",
    "select",
    "sensor",
    "siren",
    "stt",
    "sun",
    "switch",
    "text",
    "time",
    "timer",
    "todo",
    "tts",
    "update",
    "vacuum",
    "valve",
    "water_heater",
    "weather",
    "zone",
]

type StrStateValue = str | None
"""Represents a string state value or None."""

type DateTimeStateValue = ZonedDateTime | PlainDateTime | Date | None
"""Represents a datetime state value or None."""

type TimeStateValue = Time | None
"""Represents a time state value or None."""

type BoolStateValue = bool | None
"""Represents a boolean state value or None."""

type IntStateValue = int | None
"""Represents an integer state value or None."""

type NumericStateValue = float | int | None
"""Represents a numeric state value or None."""

StateT = TypeVar("StateT", bound="BaseState", default="BaseState")
"""Represents a specific state type, e.g., LightState, CoverState, etc."""

StateValueT = TypeVar(
    "StateValueT",
    StrStateValue,
    DateTimeStateValue,
    TimeStateValue,
    BoolStateValue,
    IntStateValue,
    NumericStateValue,
    Any,
    default=Any,
)
"""Represents the type of the state attribute in a State model, e.g. bool for BinarySensorState."""


LOGGER = getLogger(__name__)


class Context(BaseModel):
    """Represents the context of a Home Assistant event."""

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

    last_changed: ZonedDateTime | None = Field(None)
    """Time the state changed in the state machine, not updated when only attributes change."""

    last_reported: ZonedDateTime | None = Field(None)
    """Time the state was written to the state machine, updated regardless of any changes to the state or
    state attributes.
    """

    last_updated: ZonedDateTime | None = Field(None)
    """Time the state or state attributes changed in the state machine, not updated if neither state nor state
    attributes changed.
    """

    context: Context = Field(repr=False)
    """The context of the state change."""

    is_unknown: bool = Field(default=False)
    """Whether the state is 'unknown'."""

    is_unavailable: bool = Field(default=False)
    """Whether the state is 'unavailable'."""

    value: StateValueT = Field(..., validation_alias=AliasChoices("state", "value"))
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

    @field_validator("last_changed", "last_reported", "last_updated", mode="before")
    @classmethod
    def _validate_datetime_fields(cls, value):
        if value is None:
            return None
        if isinstance(value, int | float):
            return convert_utc_timestamp_to_system_tz(value)
        if isinstance(value, str):
            # need to use OffsetDateTime since the value is +00:00, not Z or a timezone
            return convert_datetime_str_to_system_tz(value)

        return value

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

    @classmethod
    def get_domain(cls) -> str:
        """Returns the domain string for this state class, extracted from the domain field annotation."""

        fields = cls.model_fields
        domain_field = fields.get("domain")
        if not domain_field:
            raise ValueError(f"Domain not defined for state class {cls.__name__}")

        annotation = domain_field.annotation
        if annotation is None:
            raise ValueError(f"Domain annotation is None for state class {cls.__name__}")

        args = get_args(annotation)
        if not args:
            raise ValueError(f"Domain annotation has no args for state class {cls.__name__}")

        domain = args[0]
        if not isinstance(domain, str):
            raise ValueError(f"Domain is not a string for state class {cls.__name__}")

        return domain


class StringBaseState(BaseState[StrStateValue]):
    """Base class for string states."""


class DateTimeBaseState(BaseState[DateTimeStateValue]):
    """Base class for datetime states.

    Valid state values are ZonedDateTime, PlainDateTime, Date, or None.
    """

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: DateTimeStateValue | str) -> DateTimeStateValue:
        if value is None or isinstance(value, (ZonedDateTime, PlainDateTime, Date)):
            return value
        if isinstance(value, str):
            # Try parsing as OffsetDateTime first (most common case)
            try:
                return convert_datetime_str_to_system_tz(value)
            except ValueError:
                pass
            # Next try PlainDateTime
            try:
                return PlainDateTime.parse_iso(value)
            except ValueError:
                pass
            # Finally try Date
            try:
                return Date.parse_iso(value)
            except ValueError:
                pass
        raise ValueError(f"State must be a datetime, date, or None, got {value}")


class TimeBaseState(BaseState[TimeStateValue]):
    """Base class for Time states.

    Valid state values are Time or None.
    """


class BoolBaseState(BaseState[BoolStateValue]):
    """Base class for boolean states.

    Valids state values are True, False, or None.

    Will convert string values "on" and "off" to boolean True and False.
    """

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: bool | str | None) -> BoolStateValue:
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


class IntBaseState(BaseState[IntStateValue]):
    """Base class for integer states."""

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: str | int | None) -> IntStateValue:
        """Ensure the state value is an integer or None."""
        if value is None:
            return None
        return int(value)


class NumericBaseState(BaseState[NumericStateValue]):
    """Base class for numeric states.

    Will convert string values to float or int.
    Valid state values are int, float, or None.
    """

    @field_validator("value", mode="before")
    @classmethod
    def validate_state(cls, value: str | int | float | None) -> NumericStateValue:
        """Ensure the state value is a number or None."""
        if value is None:
            return None
        if isinstance(value, int | float):
            return value
        return float(value)
