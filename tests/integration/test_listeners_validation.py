"""Listener option validation, dependency errors, and registration metadata."""

import pytest

from hassette import D
from hassette.bus.listeners import ListenerOptions
from hassette.exceptions import DependencyResolutionError
from hassette.models import states
from hassette.task_bucket import TaskBucket
from hassette.test_utils import (
    make_full_state_change_event,
    make_light_state_dict,
    make_state_dict,
)
from hassette.test_utils.helpers import create_listener

from .listener_helpers import MockEvent


class TestDependencyValidationErrors:
    """Test that listeners properly handle dependency resolution errors."""

    async def test_required_state_with_none_raises_error(self, bucket: TaskBucket):
        """Test that using StateNew with None value raises DependencyResolutionError."""
        old_state = make_state_dict(entity_id="test.entity", state="off")
        state_change_event = make_full_state_change_event("test.entity", old_state, None)

        calls = []

        def handler(new_state: D.StateNew[states.BaseState]):
            calls.append(new_state)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")

        with pytest.raises(DependencyResolutionError):
            await listener.invoker.invoke(state_change_event)

        assert len(calls) == 0

    async def test_maybe_state_with_none_succeeds(self, bucket: TaskBucket):
        """Test that using MaybeStateNew with None value succeeds."""
        old_state = make_state_dict(entity_id="test.entity", state="off")
        state_change_event = make_full_state_change_event("test.entity", old_state, None)

        calls = []

        def handler(new_state: D.MaybeStateNew[states.BaseState]):
            calls.append(new_state)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
        await listener.invoker.invoke(state_change_event)

        assert len(calls) == 1
        assert calls[0] is None

    async def test_mixed_maybe_and_required_all_succeed(self, bucket: TaskBucket):
        """Test handler with both Maybe and required deps when all resolve."""
        old_state = make_state_dict(entity_id="test.entity", state="off")
        new_state = make_state_dict(entity_id="test.entity", state="on")
        state_change_event = make_full_state_change_event("test.entity", old_state, new_state)

        results = []

        def handler(
            new_state: D.StateNew[states.BaseState],
            old_state: D.MaybeStateOld[states.BaseState],
            entity_id: D.EntityId,
        ):
            results.append((new_state, old_state, entity_id))

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
        await listener.invoker.invoke(state_change_event)

        assert len(results) == 1
        new, old, eid = results[0]
        assert new is not None
        assert old is not None
        assert eid == "test.entity"

    async def test_multiple_required_deps_first_fails(self, bucket: TaskBucket):
        """Test that if first required dep fails, handler is not called."""
        old_dict = make_light_state_dict("light.test", "on", brightness=100)
        event = make_full_state_change_event("light.test", old_dict, None)

        calls = []

        def handler(new_state: D.StateNew[states.BaseState], entity_id: D.EntityId):
            calls.append((new_state, entity_id))

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")

        with pytest.raises(DependencyResolutionError):
            await listener.invoker.invoke(event)

        assert len(calls) == 0


class TestListenerAppKeyAndInstanceIndex:
    """Test app_key and instance_index fields on Listener."""

    async def test_listener_has_app_key_and_instance_index(self, bucket: TaskBucket) -> None:
        """Create a Listener via Listener.create() with explicit app_key and instance_index."""

        def handler(event: MockEvent) -> None:
            pass

        listener = create_listener(
            handler,
            task_bucket=bucket,
            owner_id="MyApp.MyApp.0",
            topic="test_topic",
            app_key="my_app",
            instance_index=1,
        )

        assert listener.identity.app_key == "my_app"
        assert listener.identity.instance_index == 1
        assert listener.identity.owner_id == "MyApp.MyApp.0"

    async def test_listener_defaults_empty_app_key(self, bucket: TaskBucket) -> None:
        """Create a Listener without app_key, verify it defaults to empty string."""

        def handler(event: MockEvent) -> None:
            pass

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="test_topic")

        assert listener.identity.app_key == ""
        assert listener.identity.instance_index == 0


class TestOnceWithRateLimitingProhibited:
    """once=True combined with debounce or throttle is semantically contradictory and must raise."""

    async def test_once_with_debounce_raises_value_error(self, bucket: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"once.*debounce.*throttle"):
            create_listener(
                handler,
                task_bucket=bucket,
                owner_id="test",
                topic="test_topic",
                once=True,
                debounce=1.0,
            )

    async def test_once_with_throttle_raises_value_error(self, bucket: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"once.*debounce.*throttle"):
            create_listener(
                handler,
                task_bucket=bucket,
                owner_id="test",
                topic="test_topic",
                once=True,
                throttle=1.0,
            )

    async def test_once_without_rate_limiting_is_allowed(self, bucket: TaskBucket):
        async def handler(event):
            pass

        listener = create_listener(
            handler,
            task_bucket=bucket,
            owner_id="test",
            topic="test_topic",
            once=True,
        )
        assert listener.options.once is True

    async def test_rate_limiting_without_once_is_allowed(self, bucket: TaskBucket):
        async def handler(event):
            pass

        listener = create_listener(
            handler,
            task_bucket=bucket,
            owner_id="test",
            topic="test_topic",
            debounce=1.0,
        )
        assert listener.invoker.rate_limiter is not None


class TestRateLimitValueValidation:
    """debounce and throttle must be positive floats -- zero and negative are rejected."""

    async def test_debounce_zero_raises(self, bucket: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"debounce.*positive"):
            create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", debounce=0.0)

    async def test_throttle_zero_raises(self, bucket: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"throttle.*positive"):
            create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", throttle=0.0)

    async def test_debounce_negative_raises(self, bucket: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"debounce.*positive"):
            create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", debounce=-1.0)

    async def test_throttle_negative_raises(self, bucket: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"throttle.*positive"):
            create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", throttle=-1.0)


class TestMarkRegistered:
    """Test Listener.mark_registered() — one-time db_id assignment."""

    async def test_mark_registered_sets_db_id(self, bucket: TaskBucket) -> None:
        """mark_registered() sets db_id on first call."""
        listener = create_listener(lambda _e: None, task_bucket=bucket, owner_id="test", topic="t")
        assert listener.db_id is None

        listener.mark_registered(42)
        assert listener.db_id == 42

    async def test_mark_registered_warns_on_double_call(self, bucket: TaskBucket) -> None:
        """mark_registered() keeps the original db_id when called a second time."""
        listener = create_listener(lambda _e: None, task_bucket=bucket, owner_id="test", topic="t")
        listener.mark_registered(42)
        listener.mark_registered(99)

        assert listener.db_id == 42


class TestMarkFired:
    """Test Listener.mark_fired() — once-guard flag."""

    async def test_mark_fired_sets_fired(self, bucket: TaskBucket) -> None:
        """mark_fired() sets the internal _fired flag."""
        listener = create_listener(lambda _e: None, task_bucket=bucket, owner_id="test", topic="t", once=True)
        assert listener.invoker.fired is False

        listener.invoker.mark_fired()
        assert listener.invoker.fired is True


class TestValidateOptions:
    """Test ListenerOptions validation via __post_init__."""

    def test_rejects_negative_debounce(self) -> None:
        with pytest.raises(ValueError, match=r"debounce.*positive"):
            ListenerOptions(once=False, debounce=-1.0, throttle=None)

    def test_rejects_both_debounce_and_throttle(self) -> None:
        with pytest.raises(ValueError, match=r"Cannot specify both"):
            ListenerOptions(once=False, debounce=1.0, throttle=1.0)

    def test_rejects_once_with_debounce(self) -> None:
        with pytest.raises(ValueError, match=r"once.*debounce.*throttle"):
            ListenerOptions(once=True, debounce=1.0, throttle=None)

    def test_accepts_valid_options(self) -> None:
        ListenerOptions(once=False, debounce=1.0, throttle=None)
        ListenerOptions(once=True, debounce=None, throttle=None)
