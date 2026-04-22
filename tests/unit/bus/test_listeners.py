"""Unit tests for Listener immediate, duration, entity_id, and error_handler fields."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.listeners import Listener


def _make_listener(
    *,
    immediate: bool = False,
    duration: float | None = None,
    entity_id: str | None = None,
    once: bool = False,
    debounce: float | None = None,
    throttle: float | None = None,
    error_handler=None,
) -> Listener:
    """Create a Listener via create() with the given parameters."""
    task_bucket = MagicMock()
    task_bucket.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    return Listener.create(
        task_bucket=task_bucket,
        owner_id="test_owner",
        topic="test.topic",
        handler=lambda: None,
        immediate=immediate,
        duration=duration,
        entity_id=entity_id,
        once=once,
        debounce=debounce,
        throttle=throttle,
        error_handler=error_handler,
    )


class TestListenerImmediateField:
    def test_listener_create_with_immediate_true(self) -> None:
        """Listener.create(immediate=True) stores immediate=True."""
        listener = _make_listener(immediate=True, entity_id="light.kitchen")
        assert listener.immediate is True

    def test_listener_create_default_immediate_false(self) -> None:
        """Default immediate is False."""
        listener = _make_listener()
        assert listener.immediate is False


class TestListenerDurationField:
    def test_listener_create_with_duration(self) -> None:
        """Listener.create(duration=5.0) stores duration=5.0."""
        listener = _make_listener(duration=5.0, entity_id="light.kitchen")
        assert listener.duration == 5.0

    def test_listener_create_default_duration_none(self) -> None:
        """Default duration is None."""
        listener = _make_listener()
        assert listener.duration is None


class TestListenerEntityIdField:
    def test_listener_create_with_entity_id(self) -> None:
        """entity_id is stored on the Listener."""
        listener = _make_listener(entity_id="light.kitchen")
        assert listener.entity_id == "light.kitchen"

    def test_listener_create_default_entity_id_none(self) -> None:
        """Default entity_id is None."""
        listener = _make_listener()
        assert listener.entity_id is None


class TestListenerDurationValidation:
    def test_validate_duration_must_be_positive_zero(self) -> None:
        """duration=0 raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            _make_listener(duration=0)

    def test_validate_duration_must_be_positive_negative(self) -> None:
        """duration=-1 raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            _make_listener(duration=-1.0)

    def test_validate_duration_conflicts_with_debounce(self) -> None:
        """duration + debounce raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            _make_listener(duration=5.0, debounce=1.0)

    def test_validate_duration_conflicts_with_throttle(self) -> None:
        """duration + throttle raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            _make_listener(duration=5.0, throttle=1.0)

    def test_validate_once_plus_duration_allowed(self) -> None:
        """once=True combined with duration is allowed (no ValueError)."""
        listener = _make_listener(once=True, duration=5.0, entity_id="light.kitchen")
        assert listener.once is True
        assert listener.duration == 5.0


class TestListenerErrorHandlerField:
    def test_listener_create_with_error_handler(self) -> None:
        """Listener.create() with error_handler= stores it on the resulting Listener."""
        mock_error_handler = AsyncMock()
        listener = _make_listener(error_handler=mock_error_handler)
        assert listener.error_handler is mock_error_handler

    def test_listener_create_without_error_handler_defaults_none(self) -> None:
        """Listener.create() without error_handler= sets error_handler=None."""
        listener = _make_listener()
        assert listener.error_handler is None

    def test_listener_error_handler_stored_as_raw_callable(self) -> None:
        """The error_handler stored is the raw callable, not a normalized wrapper."""
        mock_error_handler = AsyncMock()
        listener = _make_listener(error_handler=mock_error_handler)
        assert listener.error_handler is mock_error_handler
