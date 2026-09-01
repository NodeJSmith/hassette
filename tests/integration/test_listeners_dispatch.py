"""Listener invocation, dispatch, and cancellation behavior."""

import pytest

from hassette.task_bucket import TaskBucket
from hassette.test_utils import make_controlled_clock, wait_for
from hassette.test_utils.helpers import create_listener

from .listener_helpers import MockEvent, mock_event


class TestListenerInvoke:
    """Test Listener.invoke() — dependency injection and handler invocation."""

    async def test_sync_handler_with_event(self, bucket: TaskBucket):
        """Test sync handler that expects an event."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
        await listener.invoker.invoke(mock_event("test_data"))
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_async_handler_with_event(self, bucket: TaskBucket):
        """Test async handler that expects an event."""
        calls = []

        async def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
        await listener.invoker.invoke(mock_event("test_data"))
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_sync_handler_no_event(self, bucket: TaskBucket):
        """Test sync handler that doesn't expect an event."""
        calls = []

        def handler():
            calls.append("called")

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
        await listener.invoker.invoke(mock_event("test_data"))
        assert calls == ["called"], "Handler should be called without event data"

    async def test_async_handler_no_event(self, bucket: TaskBucket):
        """Test async handler that doesn't expect an event."""
        calls = []

        async def handler():
            calls.append("called")

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")
        await listener.invoker.invoke(mock_event("test_data"))
        assert calls == ["called"], "Handler should be called without event data"


class TestListenerIntegration:
    """Test Listener integration with rate limiting."""

    async def test_listener_with_debounce(self, bucket: TaskBucket):
        """Test Listener with debounce via rate limiter (as BusService._dispatch would)."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(
            handler,
            task_bucket=bucket,
            owner_id="test",
            topic="test_topic",
            debounce=0.1,
        )

        assert listener.invoker.rate_limiter is not None
        rl = listener.invoker.rate_limiter

        # Simulate dispatch: rate_limiter.call(invoke_fn) — like _dispatch does
        async def invoke_fn():
            await listener.invoker.invoke(mock_event("1"))

        async def invoke_fn2():
            await listener.invoker.invoke(mock_event("2"))

        async def invoke_fn3():
            await listener.invoker.invoke(mock_event("3"))

        await rl.call(invoke_fn)
        await rl.call(invoke_fn2)
        await rl.call(invoke_fn3)

        await wait_for(lambda: calls == ["3"], desc="debounce fired")

    async def test_listener_with_throttle(self, bucket: TaskBucket):
        """Test Listener with throttle via rate limiter (as BusService._dispatch would)."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        clock = make_controlled_clock()

        listener = create_listener(
            handler,
            task_bucket=bucket,
            owner_id="test",
            topic="test_topic",
            throttle=0.1,
            clock=clock,
        )

        assert listener.invoker.rate_limiter is not None
        rl = listener.invoker.rate_limiter

        events = [mock_event("1"), mock_event("2"), mock_event("3"), mock_event("4")]

        def make_invoke(ev):
            async def invoke_fn():
                await listener.invoker.invoke(ev)

            return invoke_fn

        await rl.call(make_invoke(events[0]))
        await rl.call(make_invoke(events[1]))
        await rl.call(make_invoke(events[2]))
        assert calls == ["1"], "First call should be executed immediately"

        # advance the controlled clock past the throttle window before the next call
        clock.advance_to(1.2)
        await rl.call(make_invoke(events[3]))
        assert calls == ["1", "4"], "Second call should execute after throttle period"

    async def test_listener_without_rate_limiting(self, bucket: TaskBucket):
        """Test Listener without debounce or throttle."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="test_topic")

        # All calls should execute immediately
        await listener.invoker.invoke(mock_event("1"))
        await listener.invoker.invoke(mock_event("2"))
        await listener.invoker.invoke(mock_event("3"))

        assert calls == ["1", "2", "3"], "All calls should be executed immediately"

    async def test_cannot_specify_both_debounce_and_throttle(self, bucket: TaskBucket):
        """Test that specifying both debounce and throttle raises an error."""

        def handler(event):
            pass

        with pytest.raises(ValueError, match="Cannot specify both 'debounce' and 'throttle'"):
            create_listener(
                handler,
                task_bucket=bucket,
                owner_id="test",
                topic="test_topic",
                debounce=0.1,
                throttle=0.1,
            )


class TestListenerDispatchAndCancel:
    """Test Listener.dispatch() and Listener.cancel() — the public rate limiting API."""

    async def test_dispatch_without_rate_limiter_calls_invoke_fn_directly(self, bucket: TaskBucket):
        """dispatch() with no rate limiter calls the invoke function immediately."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t")

        async def invoke_fn():
            await listener.invoker.invoke(mock_event("direct"))

        await listener.invoker.dispatch(invoke_fn)
        assert calls == ["direct"]

    async def test_dispatch_with_debounce_coalesces(self, bucket: TaskBucket):
        """dispatch() with debounce coalesces rapid calls — only last fires."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", debounce=0.1)

        for i in range(3):

            async def invoke_fn(val=str(i + 1)):
                await listener.invoker.invoke(mock_event(val))

            await listener.invoker.dispatch(invoke_fn)

        await wait_for(lambda: calls == ["3"], desc="debounce fired")

    async def test_dispatch_with_throttle_drops_extras(self, bucket: TaskBucket):
        """dispatch() with throttle allows first call, drops subsequent within window."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", throttle=5.0)

        for i in range(3):

            async def invoke_fn(val=str(i + 1)):
                await listener.invoker.invoke(mock_event(val))

            await listener.invoker.dispatch(invoke_fn)

        assert calls == ["1"], "Only the first call should execute"

    async def test_dispatch_once_fires_only_once(self, bucket: TaskBucket):
        """dispatch() on a once=True listener fires the handler exactly once, even without BusService."""
        calls: list[str] = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = create_listener(handler, task_bucket=bucket, owner_id="test", topic="t", once=True)

        for i in range(3):

            async def invoke_fn(val=str(i + 1)):
                await listener.invoker.invoke(mock_event(val))

            await listener.invoker.dispatch(invoke_fn)

        assert calls == ["1"], "Once-listener should fire exactly once via dispatch()"

    async def test_cancel_with_rate_limiter_delegates(self, bucket: TaskBucket):
        """cancel() delegates to the rate limiter's cancel."""
        listener = create_listener(
            lambda _e: None,
            task_bucket=bucket,
            owner_id="test",
            topic="t",
            debounce=0.5,
        )
        assert listener.invoker.rate_limiter is not None
        assert not listener.invoker.rate_limiter._cancelled

        listener.cancel()
        assert listener.invoker.rate_limiter._cancelled

    async def test_cancel_without_rate_limiter_is_noop(self, bucket: TaskBucket):
        """cancel() on a listener without rate limiter does not raise."""
        listener = create_listener(lambda _e: None, task_bucket=bucket, owner_id="test", topic="t")
        assert listener.invoker.rate_limiter is None
        listener.cancel()  # should not raise

    async def test_cancel_is_idempotent(self, bucket: TaskBucket):
        """Calling cancel() twice does not raise."""
        listener = create_listener(
            lambda _e: None,
            task_bucket=bucket,
            owner_id="test",
            topic="t",
            throttle=1.0,
        )
        listener.cancel()
        listener.cancel()  # second call should not raise
