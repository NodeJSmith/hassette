"""Unit tests for hassette.cache._helpers free functions."""

import logging
import sys
import types

import pytest

from hassette.cache._helpers import DESERIALIZE_FAILED, deserialize, resolve_ttl, serialize, validate_key


def test_resolve_ttl_uses_per_call_ttl_when_given() -> None:
    """A non-None per-call ttl wins over the instance default."""
    assert resolve_ttl(30, 60) == 30


def test_resolve_ttl_falls_back_to_default_when_ttl_none() -> None:
    """ttl=None falls back to the instance default_ttl."""
    assert resolve_ttl(None, 60) == 60


def test_resolve_ttl_returns_none_when_both_none() -> None:
    """When both ttl and default_ttl are None, the value persists indefinitely."""
    assert resolve_ttl(None, None) is None


def test_resolve_ttl_passes_through_zero() -> None:
    """ttl=0 is passed through unchanged -- callers special-case deletion."""
    assert resolve_ttl(0, 60) == 0


def test_serialize_deserialize_round_trip() -> None:
    """A simple value survives a serialize/deserialize round trip."""
    blob = serialize({"a": 1, "b": [1, 2, 3]})
    assert deserialize(blob, "mykey") == {"a": 1, "b": [1, 2, 3]}


def test_deserialize_missing_class_returns_sentinel_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Unpickling a class that no longer exists returns the failure sentinel and warns."""
    module_name = "hassette_cache_test_fake_module"
    fake_module = types.ModuleType(module_name)

    class Thing:
        pass

    Thing.__module__ = module_name
    Thing.__qualname__ = "Thing"
    fake_module.Thing = Thing
    sys.modules[module_name] = fake_module

    try:
        blob = serialize(Thing())
        del fake_module.Thing  # simulate the class being renamed/moved between restarts

        with caplog.at_level(logging.WARNING, logger="hassette.cache._helpers"):
            result = deserialize(blob, "renamed-class-key")

        assert result is DESERIALIZE_FAILED
        assert "renamed-class-key" in caplog.text
    finally:
        del sys.modules[module_name]


def test_deserialize_garbage_bytes_returns_sentinel_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Unpickling garbage bytes returns the failure sentinel and logs a warning naming the key."""
    with caplog.at_level(logging.WARNING, logger="hassette.cache._helpers"):
        result = deserialize(b"not a pickle", "garbage-key")

    assert result is DESERIALIZE_FAILED
    assert "garbage-key" in caplog.text


def test_deserialize_returns_legitimate_none_without_sentinel() -> None:
    """A successfully-unpickled ``None`` value is distinct from the failure sentinel."""
    blob = serialize(None)
    result = deserialize(blob, "none-key")

    assert result is None
    assert result is not DESERIALIZE_FAILED


def test_validate_key_accepts_non_empty_string() -> None:
    """A non-empty string key passes validation without raising."""
    validate_key("valid-key")


def test_validate_key_rejects_empty_string() -> None:
    """An empty string key raises ValueError."""
    with pytest.raises(ValueError, match="non-empty string"):
        validate_key("")


def test_validate_key_rejects_non_string() -> None:
    """A non-string key raises ValueError."""
    with pytest.raises(ValueError, match="non-empty string"):
        validate_key(123)  # pyright: ignore[reportArgumentType]
