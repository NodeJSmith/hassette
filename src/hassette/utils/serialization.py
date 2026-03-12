"""JSON serialization utilities."""

import json
from typing import Any


def safe_json_serialize(value: Any) -> str:
    """Serialize a value to a JSON string, never raising.

    Uses ``default=str`` to handle common non-serializable types such as
    ``Path``, ``datetime``, and enums.  Falls back to the sentinel string
    ``'"<NON_SERIALIZABLE>"'`` when even that conversion fails.

    Keys are always sorted for deterministic output.

    Args:
        value: Any value to serialize.

    Returns:
        A JSON string representation of *value*, or ``'"<NON_SERIALIZABLE>"'``
        if serialization is not possible.
    """
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except Exception:
        return '"<NON_SERIALIZABLE>"'
