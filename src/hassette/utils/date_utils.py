from typing import overload

from whenever import OffsetDateTime, ZonedDateTime


def convert_utc_timestamp_to_system_tz(timestamp: int | float) -> ZonedDateTime:
    """Convert a UTC timestamp to ZonedDateTime in system timezone.

    Args:
        timestamp: The UTC timestamp.

    Returns:
        The converted ZonedDateTime.
    """
    return ZonedDateTime.from_timestamp(timestamp, tz="UTC").to_system_tz()


@overload
def convert_datetime_str_to_system_tz(value: str | ZonedDateTime) -> ZonedDateTime: ...


@overload
def convert_datetime_str_to_system_tz(value: None) -> None: ...


def convert_datetime_str_to_system_tz(value: str | ZonedDateTime | None) -> ZonedDateTime | None:
    """Convert an ISO 8601 datetime string to ZonedDateTime in system timezone.

    Args:
        value: The ISO 8601 datetime string.

    Returns:
        ZonedDateTime | None: The converted ZonedDateTime or None if input is None.
    """
    if value is None or isinstance(value, ZonedDateTime):
        return value
    return OffsetDateTime.parse_iso(value).to_system_tz()


def now() -> ZonedDateTime:
    """Get the current time.

    This exists to avoid direct calls to ZonedDateTime.now_in_system_tz() in the codebase, in case we need to change
    the implementation later.
    """
    return ZonedDateTime.now_in_system_tz()
