from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

import orjson
from whenever import Date, Instant, PlainDateTime, ZonedDateTime


def orjson_dump(data: Any) -> str:
    return orjson.dumps(data, default=str).decode("utf-8")


def clean_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Converts values to strings where needed and removes keys with None values."""

    def clean_value(val: Any) -> Any:
        if val is None:
            return None

        if isinstance(val, bool):
            return str(val).lower()

        if isinstance(val, (PlainDateTime | ZonedDateTime | Instant | Date)):
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
