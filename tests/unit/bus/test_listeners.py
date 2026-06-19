"""Unit tests for Listener immediate, duration, entity_id, error_handler, and cancel-listener factory."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.listeners import Listener, ListenerOptions, Subscription
from hassette.event_handling.predicates import StateTo
from hassette.test_utils.helpers import create_listener, make_task_bucket
from hassette.types.enums import BackpressurePolicy


def fn() -> None:
    pass


def fn_other() -> None:
    pass


class TestListenerConfigMatches:
    """Tests for Listener.config_matches() and diff_fields() — FR#8."""

    def test_identical_config_matches(self) -> None:
        """Two listeners with the same config return config_matches=True."""
        a = create_listener(handler=fn, topic="state_changed.light.kitchen")
        b = create_listener(handler=fn, topic="state_changed.light.kitchen")
        assert a.config_matches(b) is True

    def test_identical_config_diff_fields_empty(self) -> None:
        """Two identical listeners produce an empty diff_fields list."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn)
        assert a.diff_fields(b) == []

    def test_different_handler_not_matching(self) -> None:
        """Different handlers → config_matches=False, 'handler' in diff_fields."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn_other)
        assert a.config_matches(b) is False
        assert "handler" in a.diff_fields(b)

    def test_different_predicate_not_matching(self) -> None:
        """Different predicates → config_matches=False, 'predicate' in diff_fields."""
        pred_a = StateTo("on")
        pred_b = StateTo("off")
        a = create_listener(handler=fn, where=pred_a)
        b = create_listener(handler=fn, where=pred_b)
        assert a.config_matches(b) is False
        assert "predicate" in a.diff_fields(b)

    def test_different_once_not_matching(self) -> None:
        """Different once → 'once' in diff_fields."""
        a = create_listener(handler=fn, once=False)
        b = create_listener(handler=fn, once=True)
        assert a.config_matches(b) is False
        assert "once" in a.diff_fields(b)

    def test_different_mode_not_matching(self) -> None:
        """A mode-only change → config_matches=False, 'mode' in diff_fields (FR#14)."""
        a = create_listener(handler=fn, mode="single")
        b = create_listener(handler=fn, mode="queued")
        assert a.config_matches(b) is False
        assert "mode" in a.diff_fields(b)

    def test_different_debounce_not_matching(self) -> None:
        """Different debounce → 'debounce' in diff_fields."""
        a = create_listener(handler=fn, debounce=1.0)
        b = create_listener(handler=fn, debounce=2.0)
        assert a.config_matches(b) is False
        assert "debounce" in a.diff_fields(b)

    def test_different_throttle_not_matching(self) -> None:
        """Different throttle → 'throttle' in diff_fields."""
        a = create_listener(handler=fn, throttle=1.0)
        b = create_listener(handler=fn, throttle=2.0)
        assert a.config_matches(b) is False
        assert "throttle" in a.diff_fields(b)

    def test_different_timeout_not_matching(self) -> None:
        """Different timeout → 'timeout' in diff_fields."""
        a = create_listener(handler=fn, timeout=5.0)
        b = create_listener(handler=fn, timeout=10.0)
        assert a.config_matches(b) is False
        assert "timeout" in a.diff_fields(b)

    def test_different_timeout_disabled_not_matching(self) -> None:
        """Different timeout_disabled → 'timeout_disabled' in diff_fields."""
        a = create_listener(handler=fn, timeout_disabled=False)
        b = create_listener(handler=fn, timeout_disabled=True)
        assert a.config_matches(b) is False
        assert "timeout_disabled" in a.diff_fields(b)

    def test_different_priority_not_matching(self) -> None:
        """Different priority → config_matches=False, 'priority' in diff_fields."""
        a = create_listener(handler=fn, priority=0)
        b = create_listener(handler=fn, priority=5)
        assert a.config_matches(b) is False
        assert "priority" in a.diff_fields(b)

    def test_different_kwargs_not_matching(self) -> None:
        """Different kwargs → 'kwargs' in diff_fields."""
        a = create_listener(handler=fn, kwargs={"key": "a"})
        b = create_listener(handler=fn, kwargs={"key": "b"})
        assert a.config_matches(b) is False
        assert "kwargs" in a.diff_fields(b)

    def test_different_error_handler_not_matching(self) -> None:
        """Different error_handler (by identity) → 'error_handler' in diff_fields."""
        eh_a = AsyncMock()
        eh_b = AsyncMock()
        a = create_listener(handler=fn, error_handler=eh_a)
        b = create_listener(handler=fn, error_handler=eh_b)
        assert a.config_matches(b) is False
        assert "error_handler" in a.diff_fields(b)

    def test_same_error_handler_matches(self) -> None:
        """Same error_handler instance (by identity) → matches."""
        eh = AsyncMock()
        a = create_listener(handler=fn, error_handler=eh)
        b = create_listener(handler=fn, error_handler=eh)
        assert a.config_matches(b) is True

    def test_different_duration_config_not_matching(self) -> None:
        """Different duration_config scalars → 'duration_config' in diff_fields."""
        a = create_listener(handler=fn, entity_id="light.kitchen", duration=5.0)
        b = create_listener(handler=fn, entity_id="light.kitchen", duration=10.0)
        assert a.config_matches(b) is False
        assert "duration_config" in a.diff_fields(b)

    def test_both_duration_config_none_matches(self) -> None:
        """Both duration_config=None → matches (treated as equal)."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn)
        assert a.duration_config is None
        assert b.duration_config is None
        assert a.config_matches(b) is True

    def test_one_duration_config_none_not_matching(self) -> None:
        """One duration_config=None, other non-None → not matching."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn, entity_id="light.kitchen")
        assert a.config_matches(b) is False
        assert "duration_config" in a.diff_fields(b)

    def test_runtime_state_excluded_listener_id(self) -> None:
        """Different listener_id values do not affect config_matches."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn)
        # listener_id is assigned sequentially and will differ
        assert a.listener_id != b.listener_id
        assert a.config_matches(b) is True

    def test_runtime_state_excluded_db_id(self) -> None:
        """Different db_id values do not affect config_matches."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn)
        a.mark_registered(1)
        b.mark_registered(99)
        assert a.db_id != b.db_id
        assert a.config_matches(b) is True

    def test_runtime_state_excluded_cancelled(self) -> None:
        """Cancelled status does not affect config_matches."""
        a = create_listener(handler=fn)
        b = create_listener(handler=fn)
        b.cancel()
        assert b.is_cancelled is True
        assert a.config_matches(b) is True

    def test_diff_fields_lists_all_changed_fields(self) -> None:
        """diff_fields returns all changed field names when multiple differ."""
        a = create_listener(handler=fn, debounce=1.0)
        b = create_listener(handler=fn_other, debounce=2.0)
        changed = a.diff_fields(b)
        assert "handler" in changed
        assert "debounce" in changed

    def test_predicate_same_frozen_dataclass_matches(self) -> None:
        """Two StateTo('on') predicates (frozen dataclass, value equality) → matches."""
        a = create_listener(handler=fn, where=StateTo("on"))
        b = create_listener(handler=fn, where=StateTo("on"))
        assert a.config_matches(b) is True


class TestListenerImmediateField:
    def test_listener_create_with_immediate_true(self) -> None:
        """Listener.create(immediate=True) stores immediate=True."""
        listener = create_listener(topic="test.topic", immediate=True, entity_id="light.kitchen")
        assert listener.duration_config.immediate is True

    def test_listener_create_default_immediate_false(self) -> None:
        """Default immediate is False."""
        listener = create_listener(topic="test.topic")
        assert listener.duration_config is None or listener.duration_config.immediate is False


class TestListenerDurationField:
    def test_listener_create_with_duration(self) -> None:
        """Listener.create(duration=5.0) stores duration=5.0."""
        listener = create_listener(topic="test.topic", duration=5.0, entity_id="light.kitchen")
        assert listener.duration_config.duration == 5.0

    def test_listener_create_default_duration_none(self) -> None:
        """Default duration is None."""
        listener = create_listener(topic="test.topic")
        assert listener.duration_config is None or listener.duration_config.duration is None


class TestListenerEntityIdField:
    def test_listener_create_with_entity_id(self) -> None:
        """entity_id is stored on the Listener."""
        listener = create_listener(topic="test.topic", entity_id="light.kitchen")
        assert listener.duration_config.entity_id == "light.kitchen"

    def test_listener_create_default_entity_id_none(self) -> None:
        """Default entity_id is None."""
        listener = create_listener(topic="test.topic")
        assert listener.duration_config is None


class TestListenerDurationValidation:
    def test_validate_duration_must_be_positive_zero(self) -> None:
        """duration=0 raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            create_listener(topic="test.topic", duration=0, entity_id="light.test")

    def test_validate_duration_must_be_positive_negative(self) -> None:
        """duration=-1 raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            create_listener(topic="test.topic", duration=-1.0, entity_id="light.test")

    def test_validate_duration_conflicts_with_debounce(self) -> None:
        """duration + debounce raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            create_listener(topic="test.topic", duration=5.0, debounce=1.0, entity_id="light.test")

    def test_validate_duration_conflicts_with_throttle(self) -> None:
        """duration + throttle raises ValueError."""
        with pytest.raises(ValueError, match="duration"):
            create_listener(topic="test.topic", duration=5.0, throttle=1.0, entity_id="light.test")

    def test_validate_once_plus_duration_allowed(self) -> None:
        """once=True combined with duration is allowed (no ValueError)."""
        listener = create_listener(topic="test.topic", once=True, duration=5.0, entity_id="light.kitchen")
        assert listener.options.once is True
        assert listener.duration_config.duration == 5.0


class TestListenerErrorHandlerField:
    def test_listener_create_with_error_handler(self) -> None:
        """Listener.create() with error_handler= stores it on the resulting Listener."""
        mock_error_handler = AsyncMock()
        listener = create_listener(topic="test.topic", error_handler=mock_error_handler)
        assert listener.invoker.error_handler is mock_error_handler

    def test_listener_create_without_error_handler_defaults_none(self) -> None:
        """Listener.create() without error_handler= sets error_handler=None."""
        listener = create_listener(topic="test.topic")
        assert listener.invoker.error_handler is None

    def test_listener_error_handler_stored_as_raw_callable(self) -> None:
        """The error_handler stored is the raw callable, not a normalized wrapper."""
        mock_error_handler = AsyncMock()
        listener = create_listener(topic="test.topic", error_handler=mock_error_handler)
        assert listener.invoker.error_handler is mock_error_handler


class TestCreateCancelListener:
    """Tests for Listener.create_cancel_listener() (FR#10, AC#9)."""

    def test_source_tier_is_framework(self) -> None:
        """cancel_listener.identity.source_tier is 'framework'."""
        tb = make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.light.kitchen",
            handler=lambda: None,
        )
        assert listener.identity.source_tier == "framework"

    def test_owner_id_is_preserved(self) -> None:
        """cancel_listener.identity.owner_id matches the supplied owner_id."""
        tb = make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="my_owner",
            topic="hass.event.state_changed.light.office",
            handler=lambda: None,
        )
        assert listener.identity.owner_id == "my_owner"

    def test_no_duration_config(self) -> None:
        """cancel_listener.duration_config is None."""
        tb = make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.sensor.temp",
            handler=lambda: None,
        )
        assert listener.duration_config is None

    def test_no_rate_limiter(self) -> None:
        """cancel_listener has no rate limiter (debounce/throttle)."""
        tb = make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.light.kitchen",
            handler=lambda: None,
        )
        assert listener.invoker.rate_limiter is None

    def test_no_error_handler(self) -> None:
        """cancel_listener has no error handler."""
        tb = make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="test_owner",
            topic="hass.event.state_changed.light.kitchen",
            handler=lambda: None,
        )
        assert listener.invoker.error_handler is None

    def test_topic_is_set(self) -> None:
        """cancel_listener.topic matches the supplied topic."""
        tb = make_task_bucket()
        topic = "hass.event.state_changed.switch.fan"
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="owner",
            topic=topic,
            handler=lambda: None,
        )
        assert listener.topic == topic

    def test_predicate_default_none(self) -> None:
        """cancel_listener.predicate defaults to None when not supplied."""
        tb = make_task_bucket()
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="owner",
            topic="hass.event.state_changed.light.x",
            handler=lambda: None,
        )
        assert listener.predicate is None

    def test_predicate_can_be_set(self) -> None:
        """cancel_listener.predicate is stored when supplied."""
        tb = make_task_bucket()
        pred = MagicMock(return_value=True)
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="owner",
            topic="hass.event.state_changed.light.x",
            handler=lambda: None,
            predicate=pred,
        )
        assert listener.predicate is pred

    def test_works_without_bus_instance(self) -> None:
        """create_cancel_listener() requires no Bus instance — only task_bucket."""
        tb = make_task_bucket()
        # This must not raise — no Bus, no BusService, no Hassette instance
        listener = Listener.create_cancel_listener(
            task_bucket=tb,
            owner_id="standalone_owner",
            topic="hass.event.state_changed.light.z",
            handler=lambda: None,
        )
        assert listener.listener_id > 0

    def test_cancel_subscription_has_no_registration_task(self) -> None:
        """A Subscription for a cancel-listener has no registration_task field (AC#7).

        Under synchronous registration, Subscription has no registration_task.
        Cancel-listeners bypass DB registration entirely.
        """
        sub = Subscription(
            listener=MagicMock(),
            unsubscribe=MagicMock(),
        )
        assert not hasattr(sub, "registration_task"), "Subscription must not have registration_task field"


class TestBackpressurePolicy:
    """Tests for BackpressurePolicy plumbing — FR#1, FR#2, FR#9, FR#10, AC#6, AC#7."""

    def test_default_backpressure_is_block(self) -> None:
        """Omitting backpressure results in ListenerOptions.backpressure == BLOCK (FR#2)."""
        opts = ListenerOptions()
        assert opts.backpressure is BackpressurePolicy.BLOCK

    def test_explicit_block_policy(self) -> None:
        """backpressure=BackpressurePolicy.BLOCK is accepted and stored."""
        opts = ListenerOptions(backpressure=BackpressurePolicy.BLOCK)
        assert opts.backpressure is BackpressurePolicy.BLOCK

    def test_explicit_drop_newest_policy(self) -> None:
        """backpressure=BackpressurePolicy.DROP_NEWEST is accepted and stored."""
        opts = ListenerOptions(backpressure=BackpressurePolicy.DROP_NEWEST)
        assert opts.backpressure is BackpressurePolicy.DROP_NEWEST

    def test_string_coercion_block(self) -> None:
        """backpressure='block' string is coerced to BackpressurePolicy.BLOCK."""
        opts = ListenerOptions(backpressure="block")
        assert opts.backpressure is BackpressurePolicy.BLOCK

    def test_string_coercion_drop_newest(self) -> None:
        """backpressure='drop_newest' string is coerced to BackpressurePolicy.DROP_NEWEST."""
        opts = ListenerOptions(backpressure="drop_newest")
        assert opts.backpressure is BackpressurePolicy.DROP_NEWEST

    def test_invalid_backpressure_string_raises_value_error(self) -> None:
        """An invalid backpressure string raises ValueError naming the valid policies (FR#9, AC#6)."""
        with pytest.raises(ValueError, match="bogus") as exc_info:
            ListenerOptions(backpressure="bogus")
        error_msg = str(exc_info.value)
        assert "block" in error_msg
        assert "drop_newest" in error_msg

    def test_invalid_backpressure_string_lists_valid_values(self) -> None:
        """The ValueError message lists all valid policy values (AC#6)."""
        with pytest.raises(ValueError, match="invalid_policy") as exc_info:
            ListenerOptions(backpressure="invalid_policy")
        error_msg = str(exc_info.value)
        for policy in BackpressurePolicy:
            assert repr(policy.value) in error_msg

    def test_backpressure_drift_detected_by_diff_fields(self) -> None:
        """A changed backpressure value is reported in diff_fields (FR#10, AC#7)."""
        a = create_listener(handler=fn, backpressure=BackpressurePolicy.BLOCK)
        b = create_listener(handler=fn, backpressure=BackpressurePolicy.DROP_NEWEST)
        assert "backpressure" in a.diff_fields(b)

    def test_backpressure_drift_detected_by_config_matches(self) -> None:
        """A changed backpressure value causes config_matches to return False (FR#10, AC#7)."""
        a = create_listener(handler=fn, backpressure=BackpressurePolicy.BLOCK)
        b = create_listener(handler=fn, backpressure=BackpressurePolicy.DROP_NEWEST)
        assert a.config_matches(b) is False

    def test_same_backpressure_config_matches(self) -> None:
        """Same backpressure policy does not cause drift."""
        a = create_listener(handler=fn, backpressure=BackpressurePolicy.DROP_NEWEST)
        b = create_listener(handler=fn, backpressure=BackpressurePolicy.DROP_NEWEST)
        assert a.config_matches(b) is True
        assert "backpressure" not in a.diff_fields(b)
