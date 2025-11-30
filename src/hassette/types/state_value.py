import typing

from whenever import Date, PlainDateTime, Time, ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

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

type StateType = (
    StrStateValue | DateTimeStateValue | TimeStateValue | BoolStateValue | IntStateValue | NumericStateValue
)
"""Represents any valid state value type."""


def to_date_time_state_value(value: DateTimeStateValue | str) -> DateTimeStateValue:
    """Convert the given value to a DateTimeStateValue."""
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


def to_time_state_value(value: TimeStateValue | str) -> TimeStateValue:
    """Convert the given value to a TimeStateValue."""
    if value is None or isinstance(value, Time):
        return value
    if isinstance(value, str):
        try:
            return Time.parse_iso(value)
        except ValueError:
            pass
    raise ValueError(f"State must be a Time or None, got {value}")


def to_bool_state_value(value: BoolStateValue | str) -> BoolStateValue:
    """Convert the given value to a BoolStateValue."""
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


def to_int_state_value(value: IntStateValue | str) -> IntStateValue:
    """Convert the given value to an IntStateValue."""
    if value is None:
        return None
    return int(value)


def to_numeric_state_value(value: NumericStateValue | str) -> NumericStateValue:
    """Convert the given value to a NumericStateValue."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return value
    return float(value)


def to_str_state_value(value: StrStateValue | str) -> StrStateValue:
    """Convert the given value to a StrStateValue."""
    if value is None:
        return None
    return str(value)


TYPE_ALIAS_TO_CONVERTER_MAP: dict[typing.TypeAliasType, typing.Callable[[typing.Any], typing.Any]] = {
    StrStateValue: to_str_state_value,
    DateTimeStateValue: to_date_time_state_value,
    TimeStateValue: to_time_state_value,
    BoolStateValue: to_bool_state_value,
    IntStateValue: to_int_state_value,
    NumericStateValue: to_numeric_state_value,
}


TYPE_TO_CONVERTER_MAP: dict[type, typing.Callable[[typing.Any], typing.Any]] = {
    str: to_str_state_value,
    ZonedDateTime: to_date_time_state_value,
    PlainDateTime: to_date_time_state_value,
    Date: to_date_time_state_value,
    Time: to_time_state_value,
    bool: to_bool_state_value,
    int: to_int_state_value,
    float: to_numeric_state_value,
    type(None): lambda v: v,
}
"""Mapping of desired state value types to their converter functions."""
