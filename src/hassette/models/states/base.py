from decimal import Decimal
from inspect import get_annotations
from logging import getLogger
from typing import ClassVar, Generic, TypeVar, get_args

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from whenever import Date, PlainDateTime, Time, ZonedDateTime

from hassette.exceptions import NoDomainAnnotationError
from hassette.types.value_converters import (
    BaseValueConverter,
    BoolValueConverter,
    DateTimeValueConverter,
    NumericValueConverter,
    StrValueConverter,
    TimeValueConverter,
)
from hassette.utils.date_utils import (
    convert_datetime_str_to_system_tz,
    convert_utc_timestamp_to_system_tz,
)

StateT = TypeVar("StateT", bound="BaseState", covariant=True)
"""Represents a specific state type, e.g., LightState, CoverState, etc."""


StateValueT = TypeVar(
    "StateValueT",
    str | None,
    ZonedDateTime | PlainDateTime | Date | None,
    Time | None,
    bool | None,
    int | float | Decimal | None,
    covariant=True,
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

    value_converter: ClassVar[type[BaseValueConverter]] = BaseValueConverter
    """The converter class used to convert raw state values."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True, coerce_numbers_to_str=True, frozen=True)

    domain: str
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
            values["state"] = state = None
        elif state == "unavailable":
            values["is_unavailable"] = True
            values["state"] = state = None

        if isinstance(state, BaseValueConverter):
            values["state"] = state.to_python()

        values["state"] = cls.value_converter.from_raw(state).to_python()

        return values

    @classmethod
    def get_domain(cls) -> str:
        """Returns the domain string for this state class, extracted from the domain field annotation."""

        fields = cls.model_fields
        domain_field = fields.get("domain")
        if not domain_field:
            raise NoDomainAnnotationError(cls)

        annotations = get_annotations(cls)
        annotation = annotations.get("domain")
        if annotation is None:
            raise NoDomainAnnotationError(cls)

        args = get_args(annotation)
        if not args:
            raise NoDomainAnnotationError(cls)

        domain = args[0]
        if not isinstance(domain, str):
            raise NoDomainAnnotationError(cls)

        return domain


class StringBaseState(BaseState[str | None]):
    """Base class for string states."""

    value_converter: ClassVar[type[BaseValueConverter]] = StrValueConverter
    """The converter class used to convert raw state values."""


class DateTimeBaseState(BaseState[ZonedDateTime | PlainDateTime | Date | None]):
    """Base class for datetime states.

    Valid state values are ZonedDateTime, PlainDateTime, Date, or None.
    """

    value_converter: ClassVar[type[BaseValueConverter]] = DateTimeValueConverter
    """The converter class used to convert raw state values."""


class TimeBaseState(BaseState[Time | None]):
    """Base class for Time states.

    Valid state values are Time or None.
    """

    value_converter: ClassVar[type[BaseValueConverter]] = TimeValueConverter
    """The converter class used to convert raw state values."""


class BoolBaseState(BaseState[bool | None]):
    """Base class for boolean states.

    Valid state values are True, False, or None.

    Will convert string values "on" and "off" to boolean True and False.
    """

    value_converter: ClassVar[type[BaseValueConverter]] = BoolValueConverter
    """The converter class used to convert raw state values."""


class NumericBaseState(BaseState[int | float | Decimal | None]):
    """Base class for numeric states.

    Will convert string values to float, int, or Decimal.
    Valid state values are int, float, Decimal, or None.
    """

    value_converter: ClassVar[type[BaseValueConverter]] = NumericValueConverter
    """The type of the state value."""
