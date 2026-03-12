"""Unit tests for safe_json_serialize in hassette.utils.serialization."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from hassette.utils.serialization import safe_json_serialize


class _Color(Enum):
    RED = "red"
    BLUE = "blue"


class _Unserializable:
    """An object that cannot be serialized even with default=str override."""

    def __repr__(self) -> str:
        raise ValueError("cannot repr")

    def __str__(self) -> str:
        raise ValueError("cannot str")


def test_serialize_simple_types() -> None:
    """Basic JSON-serializable types round-trip correctly."""
    result = safe_json_serialize({"b": 2, "a": 1})
    assert json.loads(result) == {"a": 1, "b": 2}

    result = safe_json_serialize([1, 2, 3])
    assert json.loads(result) == [1, 2, 3]

    assert json.loads(safe_json_serialize("hello")) == "hello"
    assert json.loads(safe_json_serialize(42)) == 42


def test_serialize_with_default_str() -> None:
    """Types that need default=str fallback serialize without error."""
    path_result = safe_json_serialize(Path("/tmp/test"))
    assert isinstance(path_result, str)
    assert "/tmp/test" in path_result

    dt = datetime(2026, 1, 15, 12, 0, 0)
    dt_result = safe_json_serialize(dt)
    assert isinstance(dt_result, str)
    assert "2026" in dt_result

    enum_result = safe_json_serialize(_Color.RED)
    assert isinstance(enum_result, str)


def test_serialize_non_serializable() -> None:
    """Completely unserializable objects return the sentinel string."""
    result = safe_json_serialize(_Unserializable())
    assert result == '"<NON_SERIALIZABLE>"'


def test_serialize_sort_keys() -> None:
    """Keys are sorted in the JSON output."""
    data = {"z": 1, "a": 2, "m": 3}
    result = json.loads(safe_json_serialize(data))
    keys = list(result.keys())
    assert keys == sorted(keys)
