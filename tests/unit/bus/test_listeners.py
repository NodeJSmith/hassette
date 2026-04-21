"""Unit tests for Listener immediate, duration, and entity_id fields (WP01)."""

from unittest.mock import MagicMock

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
