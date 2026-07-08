"""Unit tests for DurationHoldManager and compute_elapsed.

Tests cover:
- DurationHoldManager is constructable with mock callbacks (sync)
- immediate_fire_task calls state_reader, builds invoke_fn, dispatches (async)
- immediate_fire_task returns early when state_reader returns None (async)
- start_duration_timer increments duration_timers_active and starts timer
- hold_matches delegates to hold_predicate or falls back to listener.matches
- create_cancel_listener inserts route and returns Subscription (async)
- compute_elapsed edge cases (attribute listener → 0.0, missing last_changed → 0.0)
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import hassette.utils.date_utils as _date_utils
from hassette.bus.duration_hold import DurationHoldManager
from hassette.bus.listeners import DurationConfig, Listener, Subscription
from hassette.bus.router import Router
from hassette.core.bus_service import compute_elapsed, make_synthetic_state_event
from hassette.test_utils.helpers import create_listener, make_state_dict


def make_executor() -> MagicMock:
    """Create a mock executor with an async execute method."""
    executor = MagicMock()
    executor.execute = AsyncMock()
    return executor


def make_config_resolver(value: float | None = 30.0) -> Callable[[], float | None]:
    """Create a config_resolver callable returning a fixed value."""
    return MagicMock(return_value=value)


def make_state_reader(
    state: dict[str, Any] | None = None,
) -> Callable[[str], dict[str, Any] | None]:
    """Create a state_reader callable returning a fixed state dict."""
    return MagicMock(return_value=state)


def make_remove_listener() -> Callable[[Listener], None]:
    """Create a mock remove_listener callable."""
    return MagicMock()


def make_task_bucket_with_spawn() -> MagicMock:
    """Create a task_bucket mock where spawn() actually runs tasks via asyncio."""
    tb = MagicMock()
    tb.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    def spawn_side_effect(coro: Any, *, name: str = "") -> asyncio.Task:  # noqa: ARG001
        return asyncio.create_task(coro)

    tb.spawn = MagicMock(side_effect=spawn_side_effect)
    return tb


def make_manager(
    state: dict[str, Any] | None = None,
    remove_listener: Callable[[Listener], None] | None = None,
    task_bucket: Any = None,
    executor: Any = None,
    router: Router | None = None,
) -> DurationHoldManager:
    """Build a DurationHoldManager with default mocks."""
    if remove_listener is None:
        remove_listener = make_remove_listener()
    if task_bucket is None:
        task_bucket = make_task_bucket_with_spawn()
    if executor is None:
        executor = make_executor()
    if router is None:
        router = Router()
    return DurationHoldManager(
        executor=executor,
        config_resolver=make_config_resolver(),
        state_reader=make_state_reader(state),
        remove_listener=remove_listener,
        router=router,
        task_bucket=task_bucket,
        logger=logging.getLogger("test"),
        make_synthetic_event=make_synthetic_state_event,
        compute_elapsed=compute_elapsed,
    )


class TestConstruction:
    def test_constructable_with_mock_callbacks(self) -> None:
        """DurationHoldManager is constructable with mock callbacks (no BusService import)."""
        manager = make_manager()
        assert manager is not None
        assert manager.duration_timers_active == 0

    def test_duration_timers_active_starts_at_zero(self) -> None:
        """duration_timers_active property returns 0 before any timers are started."""
        manager = make_manager()
        assert manager.duration_timers_active == 0


class TestImmediateFireTask:
    async def test_returns_early_when_state_reader_returns_none(self) -> None:
        """immediate_fire_task returns early (no dispatch) when state_reader returns None."""
        executor = make_executor()
        manager = make_manager(executor=executor)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            immediate=True,
        )

        await manager.immediate_fire_task(listener)

        executor.execute.assert_not_called()

    async def test_calls_state_reader_and_dispatches(self) -> None:
        """immediate_fire_task calls state_reader and dispatches when state exists and predicate matches."""
        executor = make_executor()
        state = make_state_dict("light.kitchen", "on")
        manager = make_manager(state=state, executor=executor)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            immediate=True,
        )

        await manager.immediate_fire_task(listener)

        executor.execute.assert_called_once()

    async def test_logs_error_and_returns_when_no_entity_id(self) -> None:
        """immediate_fire_task logs error and returns early when listener has no entity_id."""
        executor = make_executor()
        manager = make_manager(state=make_state_dict("light.kitchen", "on"), executor=executor)
        # Listener without entity_id (no duration_config)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
        )
        # Manually clear duration_config to simulate invariant violation
        object.__setattr__(listener, "duration_config", None)

        await manager.immediate_fire_task(listener)

        executor.execute.assert_not_called()

    async def test_removes_listener_on_once_after_non_duration_fire(self) -> None:
        """immediate_fire_task calls remove_listener when once=True after non-duration dispatch."""
        executor = make_executor()
        state = make_state_dict("light.kitchen", "on")
        remove_listener = make_remove_listener()
        manager = make_manager(state=state, executor=executor, remove_listener=remove_listener)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            immediate=True,
            once=True,
        )

        await manager.immediate_fire_task(listener)

        remove_listener.assert_called_once_with(listener)

    async def test_does_not_dispatch_when_predicate_does_not_match(self) -> None:
        """immediate_fire_task does not dispatch when listener predicate returns False."""
        executor = make_executor()
        state = make_state_dict("light.kitchen", "off")

        # Predicate that never matches
        never_match = MagicMock(return_value=False)

        manager = make_manager(state=state, executor=executor)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            immediate=True,
            where=never_match,
        )

        await manager.immediate_fire_task(listener)

        executor.execute.assert_not_called()


class TestDecrementTimersActive:
    def test_decrement_from_positive(self) -> None:
        """decrement_timers_active decreases counter by 1."""
        manager = make_manager()
        manager._duration_timers_active = 2
        manager.decrement_timers_active()
        assert manager.duration_timers_active == 1

    def test_decrement_floors_at_zero(self) -> None:
        """decrement_timers_active does not go below zero."""
        manager = make_manager()
        assert manager.duration_timers_active == 0
        manager.decrement_timers_active()
        assert manager.duration_timers_active == 0


class TestStartDurationTimer:
    def test_increments_duration_timers_active(self) -> None:
        """start_duration_timer increments duration_timers_active before timer fires."""
        manager = make_manager()
        remove_listener_mock = make_remove_listener()
        manager.remove_listener = remove_listener_mock

        task_bucket = make_task_bucket_with_spawn()
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=60.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        # Attach a mock timer so start() can be called
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        invoke_fn = AsyncMock()
        manager.start_duration_timer(listener, "light.kitchen", listener.duration_config, invoke_fn)

        assert manager.duration_timers_active == 1
        mock_timer.start.assert_called_once()

    def test_start_remaining_increments_duration_timers_active(self) -> None:
        """start_remaining_duration_timer increments duration_timers_active."""
        manager = make_manager()
        task_bucket = make_task_bucket_with_spawn()
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=60.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        invoke_fn = AsyncMock()
        manager.start_remaining_duration_timer(listener, "light.kitchen", listener.duration_config, invoke_fn, 30.0)

        assert manager.duration_timers_active == 1
        mock_timer.start.assert_called_once_with(mock_timer.start.call_args[0][0], override_duration=30.0)

    async def test_duration_fire_decrements_timers_active(self) -> None:
        """on_duration_fire closure decrements duration_timers_active in finally block."""
        state = make_state_dict("light.kitchen", "on")
        manager = make_manager(state=state)

        task_bucket = make_task_bucket_with_spawn()
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=60.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        invoke_fn = AsyncMock()
        manager.start_duration_timer(listener, "light.kitchen", listener.duration_config, invoke_fn)
        assert manager.duration_timers_active == 1

        on_fire = mock_timer.start.call_args[0][0]
        await on_fire()

        assert manager.duration_timers_active == 0

    async def test_duration_fire_decrements_on_early_return(self) -> None:
        """on_duration_fire decrements counter even when state_reader returns None (early return)."""
        manager = make_manager(state=None)

        task_bucket = make_task_bucket_with_spawn()
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=60.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        invoke_fn = AsyncMock()
        manager.start_duration_timer(listener, "light.kitchen", listener.duration_config, invoke_fn)
        assert manager.duration_timers_active == 1

        on_fire = mock_timer.start.call_args[0][0]
        await on_fire()

        assert manager.duration_timers_active == 0
        invoke_fn.assert_not_called()

    async def test_remaining_fire_decrements_timers_active(self) -> None:
        """on_duration_fire in start_remaining_duration_timer decrements counter."""
        state = make_state_dict("light.kitchen", "on")
        manager = make_manager(state=state)

        task_bucket = make_task_bucket_with_spawn()
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=60.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        invoke_fn = AsyncMock()
        manager.start_remaining_duration_timer(listener, "light.kitchen", listener.duration_config, invoke_fn, 30.0)
        assert manager.duration_timers_active == 1

        on_fire = mock_timer.start.call_args[0][0]
        await on_fire()

        assert manager.duration_timers_active == 0


class TestHoldMatches:
    def test_falls_back_to_listener_matches_when_no_hold_predicate(self) -> None:
        """hold_matches falls back to listener.matches() when no hold_predicate is set.

        Listener uses __slots__ so patch.object cannot replace methods — we verify
        behavior indirectly: a predicate on the listener controls the match result.
        """
        manager = make_manager()
        # Predicate that always returns False — listener.matches() delegates to it
        always_false = MagicMock(return_value=False)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            where=always_false,
        )
        # No hold_predicate — falls back to listener.matches()
        assert listener.duration_config is not None
        assert listener.duration_config.hold_predicate is None

        event = MagicMock()
        result = manager.hold_matches(listener, event)

        # listener.matches() called always_false, which returned False
        assert result is False
        always_false.assert_called_once_with(event)

    def test_uses_hold_predicate_when_set(self) -> None:
        """hold_matches calls hold_predicate directly when it is set."""
        manager = make_manager()
        hold_pred = MagicMock(return_value=False)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            hold_predicate=hold_pred,
        )
        event = MagicMock()

        result = manager.hold_matches(listener, event)

        assert result is False
        hold_pred.assert_called_once_with(event)

    def test_hold_matches_returns_true_when_hold_predicate_returns_true(self) -> None:
        """hold_matches returns True when hold_predicate returns True."""
        manager = make_manager()
        hold_pred = MagicMock(return_value=True)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            hold_predicate=hold_pred,
        )
        event = MagicMock()

        result = manager.hold_matches(listener, event)

        assert result is True

    def test_raising_hold_predicate_returns_false(self) -> None:
        """hold_matches catches a raising hold_predicate and returns False."""
        manager = make_manager()

        def bad_pred(_ev: object) -> bool:
            raise ValueError("hold boom")

        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            hold_predicate=bad_pred,
        )
        event = MagicMock()

        result = manager.hold_matches(listener, event)
        assert result is False

    def test_raising_listener_predicate_in_hold_matches_returns_false(self) -> None:
        """hold_matches catches a raising listener.matches() fallback and returns False."""
        manager = make_manager()

        def bad_pred(_ev: object) -> bool:
            raise RuntimeError("matches boom")

        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            where=bad_pred,
        )
        assert listener.duration_config is not None
        assert listener.duration_config.hold_predicate is None

        event = MagicMock()
        result = manager.hold_matches(listener, event)
        assert result is False

    def test_falls_back_when_no_duration_config(self) -> None:
        """hold_matches falls back to listener.matches when duration_config is None.

        Listener uses __slots__ — verify via a listener with a predicate that controls
        the match result.
        """
        manager = make_manager()
        always_true = MagicMock(return_value=True)
        listener = create_listener(topic="test.topic", where=always_true)
        # No duration_config (no entity_id passed)
        assert listener.duration_config is None

        event = MagicMock()
        result = manager.hold_matches(listener, event)

        assert result is True
        always_true.assert_called_once_with(event)


class TestCreateCancelListener:
    async def test_inserts_route_and_returns_subscription(self) -> None:
        """create_cancel_listener inserts a route and returns a Subscription."""
        router = Router()
        task_bucket = make_task_bucket_with_spawn()
        manager = make_manager(router=router, task_bucket=task_bucket)

        # Build a listener with a duration timer attached
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None

        cancel_sub_mock = MagicMock()
        cancel_sub_mock.cancel = MagicMock()
        # We need a real DurationTimer or a mock — use a mock
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        sub = manager.create_cancel_listener(listener)

        assert isinstance(sub, Subscription)
        assert not hasattr(sub, "registration_task"), "cancel-listener Subscription must not have registration_task"
        # Route inserted into router for the entity's state_changed topic
        entity_topic = "hass.event.state_changed.light.kitchen"
        listeners_in_route = router.get_topic_listeners(entity_topic)
        assert len(listeners_in_route) == 1

    async def test_subscription_cancel_removes_route(self) -> None:
        """Calling sub.cancel() removes the cancel listener from the router."""
        router = Router()
        task_bucket = make_task_bucket_with_spawn()
        manager = make_manager(router=router, task_bucket=task_bucket)

        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        mock_timer = MagicMock()
        listener.duration_config._timer = mock_timer

        sub = manager.create_cancel_listener(listener)

        # Verify route is present
        entity_topic = "hass.event.state_changed.light.kitchen"
        assert len(router.get_topic_listeners(entity_topic)) == 1

        # Cancel should remove the route
        sub.cancel()
        assert len(router.get_topic_listeners(entity_topic)) == 0

    def test_cancel_listener_subscription_has_no_registration_task(self) -> None:
        """create_cancel_listener returns a Subscription without registration_task.

        Cancel-listeners bypass DB registration entirely; no registration_task field.
        """
        task_bucket = make_task_bucket_with_spawn()
        manager = make_manager(task_bucket=task_bucket)
        listener = create_listener(
            topic="hass.event.state_changed.light.kitchen",
            entity_id="light.kitchen",
            duration=5.0,
            task_bucket=task_bucket,
        )
        assert listener.duration_config is not None
        listener.duration_config._timer = MagicMock()

        sub = manager.create_cancel_listener(listener)

        assert not hasattr(sub, "registration_task"), "cancel-listener Subscription must not have registration_task"


class TestComputeElapsed:
    def test_attribute_listener_returns_zero(self) -> None:
        """compute_elapsed returns 0.0 for attribute listeners."""
        state = make_state_dict("light.kitchen", "on")
        dc = DurationConfig(entity_id="light.kitchen", duration=60.0, is_attribute_listener=True)
        result = compute_elapsed(state, dc)
        assert result == 0.0

    def test_missing_last_changed_returns_zero(self) -> None:
        """compute_elapsed returns 0.0 when last_changed is missing from state dict."""
        state: dict[str, Any] = {
            "entity_id": "light.kitchen",
            "state": "on",
            # no last_changed key
        }
        dc = DurationConfig(entity_id="light.kitchen", duration=60.0)
        result = compute_elapsed(state, dc)
        assert result == 0.0

    def test_non_string_last_changed_returns_zero(self) -> None:
        """compute_elapsed returns 0.0 when last_changed is not a string."""
        state: dict[str, Any] = {
            "entity_id": "light.kitchen",
            "state": "on",
            "last_changed": 12345,  # not a string
        }
        dc = DurationConfig(entity_id="light.kitchen", duration=60.0)
        result = compute_elapsed(state, dc)
        assert result == 0.0

    def test_none_duration_returns_zero(self) -> None:
        """compute_elapsed returns 0.0 when duration_config.duration is None."""
        state = make_state_dict("light.kitchen", "on")
        dc = DurationConfig(entity_id="light.kitchen", duration=None)
        result = compute_elapsed(state, dc)
        assert result == 0.0

    def test_elapsed_clamped_to_duration(self) -> None:
        """compute_elapsed clamps result to [0.0, duration]."""
        # Use a last_changed far in the past (1 hour ago) with duration=60s
        old_time = _date_utils.now().subtract(hours=1)
        state: dict[str, Any] = {
            "entity_id": "light.kitchen",
            "state": "on",
            "last_changed": old_time.format_iso(),
        }
        dc = DurationConfig(entity_id="light.kitchen", duration=60.0)
        result = compute_elapsed(state, dc)
        # Should be clamped to the duration value (60.0)
        assert result == 60.0

    def test_elapsed_non_zero_for_recent_change(self) -> None:
        """compute_elapsed returns a positive value for a recent state change."""
        # last_changed 5 seconds ago
        recent_time = _date_utils.now().subtract(seconds=5)
        state: dict[str, Any] = {
            "entity_id": "light.kitchen",
            "state": "on",
            "last_changed": recent_time.format_iso(),
        }
        dc = DurationConfig(entity_id="light.kitchen", duration=60.0)
        result = compute_elapsed(state, dc)
        # Should be approximately 5 seconds (within 1s tolerance for test timing)
        assert 4.0 <= result <= 10.0
