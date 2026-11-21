from typing import overload

from whenever import SYSTEM_TZ, Instant, OffsetDateTime, PlainDateTime, ZonedDateTime

_configured_tz: str | None = None


def configure(tz: str | None) -> None:
    """Set the timezone used by all date utility functions.

    Called once during Hassette startup with the value from ``HassetteConfig.timezone``.
    When ``tz`` is ``None``, functions fall back to the system process timezone.
    """
    global _configured_tz
    _configured_tz = tz


# whenever types its tz parameters as ``str | SYSTEM_TZ``; the sentinel is a value, so the annotation stays a string
# and pyright, which doesn't model sentinel types yet, needs the ignore.
def active_tz() -> "str | SYSTEM_TZ":  # pyright: ignore[reportInvalidTypeForm]
    """Return the configured timezone, or ``SYSTEM_TZ`` (the system process timezone) when none is set."""
    return SYSTEM_TZ if _configured_tz is None else _configured_tz


def convert_utc_timestamp_to_tz(timestamp: int | float) -> ZonedDateTime:
    """Convert a UTC timestamp to a ZonedDateTime in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    return Instant.from_timestamp(timestamp).to_tz(active_tz())


@overload
def convert_datetime_str_to_tz(value: str | ZonedDateTime) -> ZonedDateTime: ...


@overload
def convert_datetime_str_to_tz(value: None) -> None: ...


def convert_datetime_str_to_tz(value: str | ZonedDateTime | None) -> ZonedDateTime | None:
    """Convert an ISO 8601 datetime string to a ZonedDateTime in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    if value is None or isinstance(value, ZonedDateTime):
        return value
    return OffsetDateTime.parse_iso(value).to_tz(active_tz())


def assume_tz(dt: PlainDateTime) -> ZonedDateTime:
    """Interpret a naive datetime in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    return dt.assume_tz(active_tz(), disambiguation="compatible")


def now() -> ZonedDateTime:
    """Get the current time in the configured timezone.

    Uses the configured timezone if set, otherwise the system process timezone.
    """
    return ZonedDateTime.now(active_tz())


def try_parse_iso(value: object) -> OffsetDateTime | None:
    """Parse an ISO 8601 timestamp string, returning ``None`` for non-strings and unparseable values."""
    if not isinstance(value, str):
        return None
    try:
        return OffsetDateTime.parse_iso(value)
    except ValueError:
        return None
