"""Tests for Listener timeout fields."""

import pytest

from hassette.test_utils.helpers import create_listener


class TestListenerTimeout:
    def test_listener_create_with_timeout(self) -> None:
        """Listener.create(..., timeout=5.0) stores timeout=5.0."""
        listener = create_listener(topic="test.topic", timeout=5.0)
        assert listener.options.timeout == 5.0

    def test_listener_create_default_timeout(self) -> None:
        """Default timeout is None."""
        listener = create_listener(topic="test.topic")
        assert listener.options.timeout is None

    def test_listener_create_timeout_disabled(self) -> None:
        """timeout_disabled=True stores correctly."""
        listener = create_listener(topic="test.topic", timeout_disabled=True)
        assert listener.options.timeout_disabled is True

    def test_listener_create_default_timeout_disabled(self) -> None:
        """Default timeout_disabled is False."""
        listener = create_listener(topic="test.topic")
        assert listener.options.timeout_disabled is False

    def test_listener_timeout_validation_rejects_zero(self) -> None:
        """timeout=0 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            create_listener(topic="test.topic", timeout=0)

    def test_listener_timeout_validation_rejects_negative(self) -> None:
        """timeout=-1 raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            create_listener(topic="test.topic", timeout=-1.0)

    def test_listener_timeout_validation_rejects_bool(self) -> None:
        """timeout=True (bool) raises ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            create_listener(topic="test.topic", timeout=True)  # pyright: ignore[reportArgumentType]

    def test_listener_timeout_in_equality(self) -> None:
        """Two listeners with different timeout are not equal."""
        listener_a = create_listener(topic="test.topic", timeout=5.0)
        listener_b = create_listener(topic="test.topic", timeout=10.0)
        assert listener_a != listener_b

    def test_listener_timeout_disabled_in_equality(self) -> None:
        """Two listeners with different timeout_disabled are not equal."""
        listener_a = create_listener(topic="test.topic", timeout_disabled=False)
        listener_b = create_listener(topic="test.topic", timeout_disabled=True)
        assert listener_a != listener_b
