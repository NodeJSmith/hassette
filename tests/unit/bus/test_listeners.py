"""Unit tests for Listener immediate, duration, entity_id, error_handler, and cancel-listener factory."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.listeners import Listener, Subscription


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
        assert listener.duration_config.immediate is True

    def test_listener_create_default_immediate_false(self) -> None:
        """Default immediate is False."""
        listener = _make_listener()
        assert listener.duration_config is None or listener.duration_config.immediate is False


class TestListenerDurationField:
    def test_listener_create_with_duration(self) -> None:
        """Listener.create(duration=5.0) stores duration=5.0."""
        listener = _make_listener(duration=5.0, entity_id="light.kitchen")
        assert listener.duration_config.duration == 5.0

    def test_listener_create_default_duration_none(self) -> None:
        """Default duration is None."""
        listener = _make_listener()
        assert listener.duration_config is None or listener.duration_config.duration is None


class TestListenerEntityIdField:
    def test_listener_create_with_entity_id(self) -> None:
        """entity_id is stored on the Listener."""
        listener = _make_listener(entity_id="light.kitchen")
        assert listener.duration_config.entity_id == "light.kitchen"

    def test_listener_create_default_entity_id_none(self) -> None:
        """Default entity_id is None."""
        listener = _make_listener()
        assert listener.duration_config is None


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
        assert listener.options.once is True
        assert listener.duration_config.duration == 5.0


class TestListenerErrorHandlerField:
    def test_listener_create_with_error_handler(self) -> None:
        """Listener.create() with error_handler= stores it on the resulting Listener."""
        mock_error_handler = AsyncMock()
        listener = _make_listener(error_handler=mock_error_handler)
        assert listener.invoker.error_handler is mock_error_handler

    def test_listener_create_without_error_handler_defaults_none(self) -> None:
        """Listener.create() without error_handler= sets error_handler=None."""
        listener = _make_listener()
        assert listener.invoker.error_handler is None

    def test_listener_error_handler_stored_as_raw_callable(self) -> None:
        """The error_handler stored is the raw callable, not a normalized wrapper."""
        mock_error_handler = AsyncMock()
        listener = _make_listener(error_handler=mock_error_handler)
        assert listener.invoker.error_handler is mock_error_handler


def _make_task_bucket() -> MagicMock:
    tb = MagicMock()
    tb.make_async_adapter = MagicMock(side_effect=lambda fn: fn)
    return tb


class TestCreateCancelListener:
    """Tests for Listener.create_cancel_listener() (FR#10, AC#9)."""

    def test_source_tier_is_framework(self) -> None:
        """cancel_listener.identity.source_tier is 'framework'."""
        tb = _make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.light.kitchen",
            handler=lambda: None,
            entity_id="light.kitchen",
        )
        assert listener.identity.source_tier == "framework"

    def test_owner_id_is_preserved(self) -> None:
        """cancel_listener.identity.owner_id matches the supplied owner_id."""
        tb = _make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="my_owner",
            topic="hass.event.state_changed.light.office",
            handler=lambda: None,
            entity_id="light.office",
        )
        assert listener.identity.owner_id == "my_owner"

    def test_no_duration_config(self) -> None:
        """cancel_listener.duration_config is None."""
        tb = _make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.sensor.temp",
            handler=lambda: None,
            entity_id="sensor.temp",
        )
        assert listener.duration_config is None

    def test_no_rate_limiter(self) -> None:
        """cancel_listener has no rate limiter (debounce/throttle)."""
        tb = _make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.light.kitchen",
            handler=lambda: None,
            entity_id="light.kitchen",
        )
        assert listener.invoker._rate_limiter is None

    def test_no_error_handler(self) -> None:
        """cancel_listener has no error handler."""
        tb = _make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.light.kitchen",
            handler=lambda: None,
            entity_id="light.kitchen",
        )
        assert listener.invoker.error_handler is None

    def test_topic_is_set(self) -> None:
        """cancel_listener.topic matches the supplied topic."""
        tb = _make_task_bucket()
        topic = "hass.event.state_changed.switch.fan"
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="owner",
            topic=topic,
            handler=lambda: None,
            entity_id="switch.fan",
        )
        assert listener.topic == topic

    def test_predicate_default_none(self) -> None:
        """cancel_listener.predicate defaults to None when not supplied."""
        tb = _make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="owner",
            topic="hass.event.state_changed.light.x",
            handler=lambda: None,
            entity_id="light.x",
        )
        assert listener.predicate is None

    def test_predicate_can_be_set(self) -> None:
        """cancel_listener.predicate is stored when supplied."""
        tb = _make_task_bucket()
        pred = MagicMock(return_value=True)
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="owner",
            topic="hass.event.state_changed.light.x",
            handler=lambda: None,
            entity_id="light.x",
            predicate=pred,
        )
        assert listener.predicate is pred

    def test_works_without_bus_instance(self) -> None:
        """create_cancel_listener() requires no Bus instance — only task_bucket."""
        tb = _make_task_bucket()
        # This must not raise — no Bus, no BusService, no Hassette instance
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="standalone_owner",
            topic="hass.event.state_changed.light.z",
            handler=lambda: None,
            entity_id="light.z",
        )
        assert listener.listener_id > 0

    def test_cancel_subscription_has_resolved_future(self) -> None:
        """A Subscription for a cancel-listener receives an already-resolved Future (AC#9)."""
        loop = asyncio.new_event_loop()
        try:
            resolved: asyncio.Future[None] = loop.create_future()
            resolved.set_result(None)
            sub = Subscription(
                listener=MagicMock(),
                unsubscribe=MagicMock(),
                registration_task=resolved,
            )
            assert sub.registration_task is not None
            assert sub.registration_task.done()
            assert sub.registration_task.result() is None
        finally:
            loop.close()
