from whenever import OffsetDateTime, SystemDateTime, ZonedDateTime


def convert_utc_timestamp_to_system_tz(timestamp: int | float) -> SystemDateTime:
    """Convert a UTC timestamp to SystemDateTime in system timezone.

    Args:
        timestamp (int | float): The UTC timestamp.

    Returns:
        SystemDateTime: The converted SystemDateTime.
    """
    return ZonedDateTime.from_timestamp(timestamp, tz="UTC").to_system_tz()


def convert_datetime_str_to_system_tz(value: str | SystemDateTime | None) -> SystemDateTime | None:
    """Convert an ISO 8601 datetime string to SystemDateTime in system timezone.

    Args:
        value (str | SystemDateTime | None): The ISO 8601 datetime string.

    Returns:
        SystemDateTime | None: The converted SystemDateTime or None if input is None.
    """
    if value is None or isinstance(value, SystemDateTime):
        return value
    return OffsetDateTime.parse_common_iso(value).to_system_tz()


def now() -> SystemDateTime:
    """Get the current time.

    This exists to avoid direct calls to SystemDateTime.now() in the codebase, in case we need to change
    the implementation later.
    """
    return SystemDateTime.now()
