from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import orjson
from whenever import Date, Instant, PlainDateTime, ZonedDateTime


def orjson_dump(data: Any) -> str:
    """Serialize data to a JSON string with orjson, stringifying values it cannot encode natively."""
    return orjson.dumps(data, default=str).decode("utf-8")


def format_time_param(value: PlainDateTime | ZonedDateTime | Date | str) -> str:
    """Format a date or time value as a request parameter string.

    Returns:
        The value as a string; a ``ZonedDateTime`` is rendered with a fixed UTC offset instead of a timezone name.
    """
    if isinstance(value, ZonedDateTime):
        return str(value.to_fixed_offset())
    return str(value)


def clean_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Converts values to strings where needed and removes keys with None values."""

    def clean_value(val: Any) -> Any:
        if val is None:
            return None

        if isinstance(val, bool):
            return str(val).lower()

        if isinstance(val, ZonedDateTime):
            return str(val.to_fixed_offset())

        if isinstance(val, (PlainDateTime | Instant | Date)):
            return val.format_iso()

        if isinstance(val, (int | float | str)):
            if isinstance(val, str) and not val.strip():
                return None
            return val

        if isinstance(val, datetime):
            return val.isoformat()

        if isinstance(val, Mapping):
            return {k: clean_value(v) for k, v in val.items() if v is not None}

        if isinstance(val, Iterable) and not isinstance(val, str | bytes):
            return [clean_value(v) for v in val if v is not None]

        return str(val)

    return {k: cleaned for k, v in kwargs.items() if (cleaned := clean_value(v)) is not None}
