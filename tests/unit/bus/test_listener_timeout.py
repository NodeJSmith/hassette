"""Tests for Listener timeout fields."""

from unittest.mock import MagicMock

import pytest

from hassette.bus.listeners import Listener


def _make_listener(*, timeout: float | None = None, timeout_disabled: bool = False) -> Listener:
    """Create a Listener via create() with timeout parameters."""
    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    return Listener.create(
        task_bucket=task_bucket,
        owner_id="test_owner",
        topic="test.topic",
        handler=lambda: None,
        timeout=timeout,
        timeout_disabled=timeout_disabled,
    )


class TestListenerTimeout:
    def test_listener_create_with_timeout(self) -> None:
        """Listener.create(..., timeout=5.0) stores timeout=5.0."""
        listener = _make_listener(timeout=5.0)
        assert listener.timeout == 5.0

    def test_listener_create_default_timeout(self) -> None:
        """Default timeout is None."""
        listener = _make_listener()
        assert listener.timeout is None

    def test_listener_create_timeout_disabled(self) -> None:
        """timeout_disabled=True stores correctly."""
        listener = _make_listener(timeout_disabled=True)
        assert listener.timeout_disabled is True

    def test_listener_create_default_timeout_disabled(self) -> None:
        """Default timeout_disabled is False."""
        listener = _make_listener()
        assert listener.timeout_disabled is False

    def test_listener_timeout_validation_rejects_zero(self) -> None:
        """timeout=0 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            _make_listener(timeout=0)

    def test_listener_timeout_validation_rejects_negative(self) -> None:
        """timeout=-1 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            _make_listener(timeout=-1.0)

    def test_listener_timeout_validation_rejects_bool(self) -> None:
        """timeout=True (bool) raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            _make_listener(timeout=True)  # pyright: ignore[reportArgumentType]

    def test_listener_timeout_in_equality(self) -> None:
        """Two listeners with different timeout are not equal."""
        listener_a = _make_listener(timeout=5.0)
        listener_b = _make_listener(timeout=10.0)
        assert listener_a != listener_b

    def test_listener_timeout_disabled_in_equality(self) -> None:
        """Two listeners with different timeout_disabled are not equal."""
        listener_a = _make_listener(timeout_disabled=False)
        listener_b = _make_listener(timeout_disabled=True)
        assert listener_a != listener_b
