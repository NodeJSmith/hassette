"""Tests that TYPE_REGISTRY.convert passes values through unchanged when the target is Any."""

from typing import Any

import pytest

from hassette.conversion import TYPE_REGISTRY


@pytest.mark.parametrize("value", [5, "x", None, [1, 2]], ids=["int", "str", "none", "list"])
def test_convert_to_any_returns_value_unchanged(value: Any):
    """A target of Any short-circuits instead of falling through to the Any(value) constructor."""
    assert TYPE_REGISTRY.convert(value, Any) is value
