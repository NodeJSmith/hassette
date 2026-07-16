from typing import overload

from whenever import OffsetDateTime, ZonedDateTime

_configured_tz: str | None = None


def configure(tz: str | None) -> None:
    """Set the timezone used by all date utility functions.

    Called once during Hassette startup with the value from ``HassetteConfig.timezone``.
    When ``tz`` is ``None``, functions fall back to the system process timezone.
    """
    global _configured_tz
    _configured_tz = tz


def convert_utc_timestamp_to_system_tz(timestamp: int | float) -> ZonedDateTime:
    """Convert a UTC timestamp to a ZonedDateTime in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    if _configured_tz is not None:
        return ZonedDateTime.from_timestamp(timestamp, tz=_configured_tz)
    return ZonedDateTime.from_timestamp(timestamp, tz="UTC").to_system_tz()


@overload
def convert_datetime_str_to_system_tz(value: str | ZonedDateTime) -> ZonedDateTime: ...


@overload
def convert_datetime_str_to_system_tz(value: None) -> None: ...


def convert_datetime_str_to_system_tz(value: str | ZonedDateTime | None) -> ZonedDateTime | None:
    """Convert an ISO 8601 datetime string to a ZonedDateTime in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    if value is None or isinstance(value, ZonedDateTime):
        return value
    if _configured_tz is not None:
        return OffsetDateTime.parse_iso(value).to_tz(_configured_tz)
    return OffsetDateTime.parse_iso(value).to_system_tz()


def now() -> ZonedDateTime:
    """Get the current time in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    if _configured_tz is not None:
        return ZonedDateTime.now(_configured_tz)
    return ZonedDateTime.now_in_system_tz()
