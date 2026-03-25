import asyncio
import inspect
from dataclasses import dataclass

import pytest

from hassette import D
from hassette.bus.listeners import HandlerAdapter, Listener
from hassette.events import Event
from hassette.exceptions import DependencyResolutionError
from hassette.models import states
from hassette.task_bucket import TaskBucket
from hassette.test_utils import make_full_state_change_event, make_light_state_dict, make_state_dict


@dataclass(frozen=True, slots=True)
class MockEvent(Event[str]):
    """Mock event for testing."""

    @property
    def data(self) -> str:
        """Return payload for backward compatibility with tests."""
        return self.payload


def mock_event(data: str = "test") -> MockEvent:
    """Create a MockEvent with a topic and payload."""
    return MockEvent(topic="test_topic", payload=data)


def create_adapter(handler, _bucket_fixture=None):
    """Helper to create HandlerAdapter with proper signature."""
    signature = inspect.signature(handler)
    handler_name = handler.__name__ if hasattr(handler, "__name__") else "test_handler"
    return HandlerAdapter(handler_name, handler, signature)


class TestHandlerAdapter:
    """Test HandlerAdapter functionality."""

    async def test_sync_handler_with_event(self, bucket_fixture: TaskBucket):
        """Test sync handler that expects an event."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_async_handler_with_event(self, bucket_fixture: TaskBucket):
        """Test async handler that expects an event."""
        calls = []

        async def handler(event: MockEvent):
            calls.append(event.data)

        adapter = create_adapter(handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_sync_handler_no_event(self, bucket_fixture: TaskBucket):
        """Test sync handler that doesn't expect an event."""
        calls = []

        def handler():
            calls.append("called")

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["called"], "Handler should be called without event data"

    async def test_async_handler_no_event(self, bucket_fixture: TaskBucket):
        """Test async handler that doesn't expect an event."""
        calls = []

        async def handler():
            calls.append("called")

        adapter = create_adapter(handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["called"], "Handler should be called without event data"


class TestDebounceLogic:
    """Test debounce functionality via RateLimiter directly.

    Rate limiting is orchestrated by BusService._dispatch, not HandlerAdapter.
    These tests exercise the RateLimiter in isolation.
    """

    async def test_debounce_delays_execution(self, bucket_fixture: TaskBucket):
        """Test that debounce delays execution until quiet period."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket_fixture, debounce=0.1)

        await limiter.call(make_handler("first"))
        await limiter.call(make_handler("second"))
        await limiter.call(make_handler("third"))

        await asyncio.sleep(0)
        assert calls == [], "No calls should be made immediately due to debounce"

        await asyncio.sleep(0.2)
        assert calls == ["third"], "Only the last event should be processed after debounce"

    async def test_debounce_with_no_args(self, bucket_fixture: TaskBucket):
        """Test debounce with a no-arg handler."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        async def handler():
            calls.append("called")

        limiter = RateLimiter(bucket_fixture, debounce=0.1)

        await limiter.call(handler)
        await limiter.call(handler)
        await limiter.call(handler)

        await asyncio.sleep(0.2)
        assert calls == ["called"], "Handler should be called only once after debounce"

    async def test_debounce_cancels_previous_calls(self, bucket_fixture: TaskBucket):
        """Test that new debounce calls cancel previous pending calls."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket_fixture, debounce=0.2)

        await limiter.call(make_handler("first"))
        await asyncio.sleep(0.1)
        assert limiter._debounce_task is not None, "Debounce task should be created"
        assert not limiter._debounce_task.done(), "Debounce task should still be pending"

        await limiter.call(make_handler("second"))
        await asyncio.sleep(0.1)
        assert not limiter._debounce_task.done(), "Debounce task should still be pending"

        await limiter.call(make_handler("third"))

        await asyncio.sleep(0.3)
        assert calls == ["third"], "Only the last call should be processed after debounce"
        # After completion, done_callback clears the reference to release captured payloads
        assert limiter._debounce_task is None, "Debounce task reference should be cleared after completion"

    async def test_debounce_handler_cancelled_error_propagates(self, bucket_fixture: TaskBucket):
        """CancelledError during handler execution must propagate (not be suppressed).

        Debounce reset (cancel during sleep) should be silent, but handler cancellation
        (e.g., shutdown) should propagate so telemetry can record it as 'cancelled'.
        """
        from hassette.bus.rate_limiter import RateLimiter

        async def handler_that_gets_cancelled():
            raise asyncio.CancelledError()

        limiter = RateLimiter(bucket_fixture, debounce=0.01)
        await limiter.call(handler_that_gets_cancelled)

        # Capture task reference before done_callback clears it
        task = limiter._debounce_task
        assert task is not None

        # Wait for debounce to fire and handler to run
        await asyncio.sleep(0.05)

        # The task should show as cancelled (CancelledError propagated out of delayed_call)
        assert task.done()
        assert task.cancelled(), "Handler CancelledError should propagate, not be suppressed"

    async def test_debounce_reset_cancellation_is_silent(self, bucket_fixture: TaskBucket):
        """CancelledError from debounce reset (new event superseding old) should be silent."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket_fixture, debounce=0.1)

        # First call starts debounce
        await limiter.call(make_handler("first"))
        first_task = limiter._debounce_task
        assert first_task is not None

        # Second call cancels first (debounce reset)
        await limiter.call(make_handler("second"))
        await asyncio.sleep(0)  # Let cancellation propagate

        # First task should be cancelled silently (no crash)
        assert first_task.cancelled() or first_task.done()

        # Wait for second debounce to fire
        await asyncio.sleep(0.15)
        assert calls == ["second"]


class TestRateLimiterCancel:
    """Test RateLimiter.cancel() for cleanup on listener removal."""

    async def test_cancel_pending_debounce(self, bucket_fixture: TaskBucket):
        """Cancelling a pending debounce prevents the handler from firing."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        async def handler():
            calls.append("fired")

        limiter = RateLimiter(bucket_fixture, debounce=0.5)
        await limiter.call(handler)
        assert limiter._debounce_task is not None

        limiter.cancel()
        assert limiter._debounce_task is None

        await asyncio.sleep(0.6)
        assert calls == [], "Handler should not fire after cancel"

    async def test_cancel_when_no_task(self, bucket_fixture: TaskBucket):
        """Cancelling with no pending task should not raise."""
        from hassette.bus.rate_limiter import RateLimiter

        limiter = RateLimiter(bucket_fixture, debounce=0.1)
        limiter.cancel()  # Should not raise

    async def test_cancel_after_task_completed(self, bucket_fixture: TaskBucket):
        """Cancelling after the task has already completed should not raise."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        async def handler():
            calls.append("fired")

        limiter = RateLimiter(bucket_fixture, debounce=0.01)
        await limiter.call(handler)
        await asyncio.sleep(0.05)
        assert calls == ["fired"]

        limiter.cancel()  # Should not raise; task already done


class TestThrottleLogic:
    """Test throttle functionality via RateLimiter directly.

    Rate limiting is orchestrated by BusService._dispatch, not HandlerAdapter.
    These tests exercise the RateLimiter in isolation.
    """

    async def test_throttle_limits_execution_frequency(self, bucket_fixture: TaskBucket):
        """Test that throttle limits how often handler is called."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket_fixture, throttle=0.1)

        await limiter.call(make_handler("first"))
        assert calls == ["first"], "First call should be executed immediately"

        await limiter.call(make_handler("second"))
        await limiter.call(make_handler("third"))
        assert calls == ["first"], "Subsequent calls should be ignored"

        await asyncio.sleep(0.15)

        await limiter.call(make_handler("fourth"))
        assert calls == ["first", "fourth"], "Fourth call should execute after throttle period"

    async def test_throttle_with_no_args(self, bucket_fixture: TaskBucket):
        """Test throttle with a no-arg handler."""
        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []
        label = "called"

        async def handler():
            calls.append(label)

        limiter = RateLimiter(bucket_fixture, throttle=0.1)

        await limiter.call(handler)
        assert calls == ["called"]

        label = "called while throttled"
        await limiter.call(handler)
        await limiter.call(handler)
        assert calls == ["called"]

        label = "called after throttle"
        await asyncio.sleep(0.15)
        await limiter.call(handler)
        assert calls == ["called", "called after throttle"]

    async def test_throttle_tracks_time_correctly(self, bucket_fixture: TaskBucket):
        """Test that throttle timing works correctly using mocked time."""
        from unittest.mock import patch

        from hassette.bus.rate_limiter import RateLimiter

        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        with patch("hassette.bus.rate_limiter.time.monotonic") as mock_time:
            mock_time.return_value = 1000.0
            limiter = RateLimiter(bucket_fixture, throttle=0.05)

            await limiter.call(make_handler("1"))
            assert calls == ["1"]

            mock_time.return_value = 1000.03
            await limiter.call(make_handler("2"))
            assert calls == ["1"]

            mock_time.return_value = 1000.06
            await limiter.call(make_handler("3"))
            assert calls == ["1", "3"]

    async def test_throttle_does_not_block_during_handler(self, bucket_fixture: TaskBucket):
        """A second throttled call within the window must not block on the first handler."""
        from hassette.bus.rate_limiter import RateLimiter

        handler_started = asyncio.Event()
        handler_release = asyncio.Event()

        async def slow_handler():
            handler_started.set()
            await handler_release.wait()

        limiter = RateLimiter(bucket_fixture, throttle=5.0)

        task1 = asyncio.create_task(limiter.call(slow_handler))
        await handler_started.wait()

        task2 = asyncio.create_task(limiter.call(slow_handler))
        done, _ = await asyncio.wait({task2}, timeout=0.05)
        assert task2 in done, "Throttled call within window must return immediately, not block"

        handler_release.set()
        await task1


class TestListenerIntegration:
    """Test Listener integration with HandlerAdapter."""

    async def test_listener_with_debounce(self, bucket_fixture: TaskBucket):
        """Test Listener with debounce via rate limiter (as BusService._dispatch would)."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="test",
            topic="test_topic",
            handler=handler,
            debounce=0.1,
        )

        assert listener.rate_limiter is not None
        rl = listener.rate_limiter

        # Simulate dispatch: rate_limiter.call(invoke_fn) — like _dispatch does
        async def invoke_fn():
            await listener.invoke(mock_event("1"))

        async def invoke_fn2():
            await listener.invoke(mock_event("2"))

        async def invoke_fn3():
            await listener.invoke(mock_event("3"))

        await rl.call(invoke_fn)
        await rl.call(invoke_fn2)
        await rl.call(invoke_fn3)

        await asyncio.sleep(0.2)
        assert calls == ["3"], "Only the last event should be processed after debounce"

    async def test_listener_with_throttle(self, bucket_fixture: TaskBucket):
        """Test Listener with throttle via rate limiter (as BusService._dispatch would)."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="test",
            topic="test_topic",
            handler=handler,
            throttle=0.1,
        )

        assert listener.rate_limiter is not None
        rl = listener.rate_limiter

        events = [mock_event("1"), mock_event("2"), mock_event("3"), mock_event("4")]

        def make_invoke(ev):
            async def invoke_fn():
                await listener.invoke(ev)

            return invoke_fn

        await rl.call(make_invoke(events[0]))
        await rl.call(make_invoke(events[1]))
        await rl.call(make_invoke(events[2]))
        assert calls == ["1"], "First call should be executed immediately"

        await asyncio.sleep(0.15)
        await rl.call(make_invoke(events[3]))
        assert calls == ["1", "4"], "Second call should execute after throttle period"

    async def test_listener_without_rate_limiting(self, bucket_fixture: TaskBucket):
        """Test Listener without debounce or throttle."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="test",
            topic="test_topic",
            handler=handler,
        )

        # All calls should execute immediately
        await listener.invoke(mock_event("1"))
        await listener.invoke(mock_event("2"))
        await listener.invoke(mock_event("3"))

        assert calls == ["1", "2", "3"], "All calls should be executed immediately"

    async def test_cannot_specify_both_debounce_and_throttle(self, bucket_fixture: TaskBucket):
        """Test that specifying both debounce and throttle raises an error."""

        def handler(event):
            pass

        with pytest.raises(ValueError, match="Cannot specify both 'debounce' and 'throttle'"):
            Listener.create(
                task_bucket=bucket_fixture,
                owner_id="test",
                topic="test_topic",
                handler=handler,
                debounce=0.1,
                throttle=0.1,
            )


class TestListenerDispatchAndCancel:
    """Test Listener.dispatch() and Listener.cancel() — the public rate limiting API."""

    async def test_dispatch_without_rate_limiter_calls_invoke_fn_directly(self, bucket_fixture: TaskBucket):
        """dispatch() with no rate limiter calls the invoke function immediately."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler)

        async def invoke_fn():
            await listener.invoke(mock_event("direct"))

        await listener.dispatch(invoke_fn)
        assert calls == ["direct"]

    async def test_dispatch_with_debounce_coalesces(self, bucket_fixture: TaskBucket):
        """dispatch() with debounce coalesces rapid calls — only last fires."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler, debounce=0.1
        )

        for i in range(3):

            async def invoke_fn(val=str(i + 1)):
                await listener.invoke(mock_event(val))

            await listener.dispatch(invoke_fn)

        await asyncio.sleep(0.2)
        assert calls == ["3"], "Only the last event should fire after debounce"

    async def test_dispatch_with_throttle_drops_extras(self, bucket_fixture: TaskBucket):
        """dispatch() with throttle allows first call, drops subsequent within window."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler, throttle=5.0
        )

        for i in range(3):

            async def invoke_fn(val=str(i + 1)):
                await listener.invoke(mock_event(val))

            await listener.dispatch(invoke_fn)

        assert calls == ["1"], "Only the first call should execute"

    async def test_cancel_with_rate_limiter_delegates(self, bucket_fixture: TaskBucket):
        """cancel() delegates to the rate limiter's cancel."""
        listener = Listener.create(
            task_bucket=bucket_fixture, owner_id="test", topic="t", handler=lambda _e: None, debounce=0.5
        )
        assert listener.rate_limiter is not None
        assert not listener.rate_limiter._cancelled

        listener.cancel()
        assert listener.rate_limiter._cancelled

    async def test_cancel_without_rate_limiter_is_noop(self, bucket_fixture: TaskBucket):
        """cancel() on a listener without rate limiter does not raise."""
        listener = Listener.create(task_bucket=bucket_fixture, owner_id="test", topic="t", handler=lambda _e: None)
        assert listener.rate_limiter is None
        listener.cancel()  # should not raise

    async def test_cancel_is_idempotent(self, bucket_fixture: TaskBucket):
        """Calling cancel() twice does not raise."""
        listener = Listener.create(
            task_bucket=bucket_fixture, owner_id="test", topic="t", handler=lambda _e: None, throttle=1.0
        )
        listener.cancel()
        listener.cancel()  # second call should not raise


class TestDependencyValidationErrors:
    """Test that listeners properly handle dependency resolution errors."""

    async def test_required_state_with_none_raises_error(self, bucket_fixture: TaskBucket):
        """Test that using StateNew with None value raises DependencyResolutionError."""

        # Create mock states
        old_state = make_state_dict(entity_id="test.entity", state="off")
        state_change_event = make_full_state_change_event("test.entity", old_state, None)

        calls = []

        def handler(new_state: D.StateNew[states.BaseState]):
            calls.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        # Should raise DependencyResolutionError when new_state is None
        with pytest.raises(DependencyResolutionError):
            await adapter.call(state_change_event)

        assert len(calls) == 0  # Handler should not be called

    async def test_maybe_state_with_none_succeeds(self, bucket_fixture: TaskBucket):
        """Test that using MaybeStateNew with None value succeeds."""

        # Create mock states
        old_state = make_state_dict(entity_id="test.entity", state="off")
        state_change_event = make_full_state_change_event("test.entity", old_state, None)

        calls = []

        def handler(new_state: D.MaybeStateNew[states.BaseState]):
            calls.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        # Should succeed
        await adapter.call(state_change_event)

        assert len(calls) == 1
        assert calls[0] is None

    async def test_mixed_maybe_and_required_all_succeed(self, bucket_fixture: TaskBucket):
        """Test handler with both Maybe and required deps when all resolve."""

        # Create mock states
        old_state = make_state_dict(entity_id="test.entity", state="off")
        new_state = make_state_dict(entity_id="test.entity", state="on")
        state_change_event = make_full_state_change_event("test.entity", old_state, new_state)

        results = []

        def handler(
            new_state: D.StateNew[states.BaseState],  # Required, present
            old_state: D.MaybeStateOld[states.BaseState],  # Optional, present
            entity_id: D.EntityId,  # Required, present
        ):
            results.append((new_state, old_state, entity_id))

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(state_change_event)

        assert len(results) == 1
        new, old, eid = results[0]
        assert new is not None
        assert old is not None
        assert eid == "test.entity"

    async def test_multiple_required_deps_first_fails(self, bucket_fixture: TaskBucket):
        """Test that if first required dep fails, handler is not called."""

        old_dict = make_light_state_dict("light.test", "on", brightness=100)

        # make and send update event
        event = make_full_state_change_event("light.test", old_dict, None)

        calls = []

        # StateNew will fail, EntityId will succeed
        def handler(new_state: D.StateNew[states.BaseState], entity_id: D.EntityId):
            calls.append((new_state, entity_id))

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        with pytest.raises(DependencyResolutionError):
            await adapter.call(event)

        assert len(calls) == 0


class TestListenerAppKeyAndInstanceIndex:
    """Test app_key and instance_index fields on Listener."""

    async def test_listener_has_app_key_and_instance_index(self, bucket_fixture: TaskBucket) -> None:
        """Create a Listener via Listener.create() with explicit app_key and instance_index."""

        def handler(event: MockEvent) -> None:
            pass

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="MyApp.MyApp.0",
            topic="test_topic",
            handler=handler,
            app_key="my_app",
            instance_index=1,
        )

        assert listener.app_key == "my_app"
        assert listener.instance_index == 1
        assert listener.owner_id == "MyApp.MyApp.0"

    async def test_listener_defaults_empty_app_key(self, bucket_fixture: TaskBucket) -> None:
        """Create a Listener without app_key, verify it defaults to empty string."""

        def handler(event: MockEvent) -> None:
            pass

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="test",
            topic="test_topic",
            handler=handler,
        )

        assert listener.app_key == ""
        assert listener.instance_index == 0


class TestOnceWithRateLimitingProhibited:
    """once=True combined with debounce or throttle is semantically contradictory and must raise."""

    async def test_once_with_debounce_raises_value_error(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"once.*debounce.*throttle"):
            Listener.create(
                task_bucket=bucket_fixture,
                owner_id="test",
                topic="test_topic",
                handler=handler,
                once=True,
                debounce=1.0,
            )

    async def test_once_with_throttle_raises_value_error(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"once.*debounce.*throttle"):
            Listener.create(
                task_bucket=bucket_fixture,
                owner_id="test",
                topic="test_topic",
                handler=handler,
                once=True,
                throttle=1.0,
            )

    async def test_once_without_rate_limiting_is_allowed(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="test",
            topic="test_topic",
            handler=handler,
            once=True,
        )
        assert listener.once is True

    async def test_rate_limiting_without_once_is_allowed(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner_id="test",
            topic="test_topic",
            handler=handler,
            debounce=1.0,
        )
        assert listener.rate_limiter is not None


class TestRateLimitValueValidation:
    """debounce and throttle must be positive floats -- zero and negative are rejected."""

    async def test_debounce_zero_raises(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"debounce.*positive"):
            Listener.create(task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler, debounce=0.0)

    async def test_throttle_zero_raises(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"throttle.*positive"):
            Listener.create(task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler, throttle=0.0)

    async def test_debounce_negative_raises(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"debounce.*positive"):
            Listener.create(task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler, debounce=-1.0)

    async def test_throttle_negative_raises(self, bucket_fixture: TaskBucket):
        async def handler(event):
            pass

        with pytest.raises(ValueError, match=r"throttle.*positive"):
            Listener.create(task_bucket=bucket_fixture, owner_id="test", topic="t", handler=handler, throttle=-1.0)
