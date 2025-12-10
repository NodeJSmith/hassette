from contextlib import suppress
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from whenever import Date, Instant, OffsetDateTime, PlainDateTime, Time, ZonedDateTime

from hassette.core.type_registry import register_simple_type_converter, register_type_converter_fn
from hassette.utils.date_utils import convert_datetime_str_to_system_tz

# stdlib classes
register_simple_type_converter(Decimal, float)
register_simple_type_converter(Decimal, int)
register_simple_type_converter(float, Decimal, error_types=(ValueError, InvalidOperation))
register_simple_type_converter(float, int)
register_simple_type_converter(float, str)
register_simple_type_converter(int, float)
register_simple_type_converter(bool, str)
register_simple_type_converter(int, str)
register_simple_type_converter(str, Decimal, error_types=(ValueError, InvalidOperation))
register_simple_type_converter(str, float)
register_simple_type_converter(str, int)


# non-stdlib classes
register_simple_type_converter(str, Date, fn=Date.parse_iso)
register_simple_type_converter(str, Time, fn=Time.parse_iso)
register_simple_type_converter(str, OffsetDateTime, fn=OffsetDateTime.parse_iso)
register_simple_type_converter(str, PlainDateTime, fn=PlainDateTime.parse_iso)
register_simple_type_converter(Time, time, fn=Time.py_time)
register_simple_type_converter(Time, str, fn=Time.format_iso)
register_simple_type_converter(ZonedDateTime, Instant, fn=ZonedDateTime.to_instant)
register_simple_type_converter(ZonedDateTime, PlainDateTime, fn=ZonedDateTime.to_plain)
register_simple_type_converter(ZonedDateTime, str, fn=ZonedDateTime.format_iso)

# more complex converters


@register_type_converter_fn(error_message="String must be a datetime-like value, got {from_type}")
def from_string_to_zoned_date_time(value: str) -> ZonedDateTime:
    with suppress(ValueError):
        return convert_datetime_str_to_system_tz(value)
    with suppress(ValueError):
        return PlainDateTime.parse_iso(value).assume_system_tz()
    with suppress(ValueError):
        return Date.parse_iso(value).at(Time(0, 0, 0, nanosecond=0)).assume_system_tz()
    raise ValueError


@register_type_converter_fn(error_message="String must be a time-like value, got {from_type}")
def from_string_to_stdlib_time(value: str) -> time:
    return Time.parse_iso(value).py_time()


@register_type_converter_fn(error_message="String must be a date-like value, got {from_type}")
def from_string_to_stdlib_date(value: str) -> date:
    return Date.parse_iso(value).py_date()


@register_type_converter_fn(error_message="String must be a datetime-like value, got {from_type}")
def from_string_to_stdlib_datetime(value: str) -> datetime:
    return from_string_to_zoned_date_time(value).py_datetime()


@register_type_converter_fn(error_message="String must be a boolean-like value, got {from_type}")
def from_string_to_bool(value: str) -> bool:
    lower_val = value.lower()
    match lower_val:
        case "on" | "true" | "yes" | "1":
            return True
        case "off" | "false" | "no" | "0":
            return False
        case _:
            raise ValueError
