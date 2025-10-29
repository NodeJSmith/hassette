import asyncio
import inspect

import pytest

from hassette.bus.listeners import HandlerAdapter, Listener
from hassette.task_bucket import TaskBucket


class MockEvent:
    """Mock event for testing."""

    def __init__(self, data="test"):
        self.data = data


class TestHandlerAdapter:
    """Test HandlerAdapter functionality."""

    async def test_sync_handler_with_event(self, bucket_fixture: TaskBucket):
        """Test sync handler that expects an event."""
        calls = []

        def handler(event):
            calls.append(event.data)

        signature = inspect.signature(handler)
        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = HandlerAdapter(async_handler, signature, bucket_fixture)

        assert adapter.expects_event, "Adapter should detect that handler expects event"

        event = MockEvent("test_data")
        await adapter.call(event)
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_async_handler_with_event(self, bucket_fixture: TaskBucket):
        """Test async handler that expects an event."""
        calls = []

        async def handler(event):
            calls.append(event.data)

        signature = inspect.signature(handler)
        adapter = HandlerAdapter(handler, signature, bucket_fixture)

        assert adapter.expects_event, "Adapter should detect that handler expects event"

        event = MockEvent("test_data")
        await adapter.call(event)
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_sync_handler_no_event(self, bucket_fixture: TaskBucket):
        """Test sync handler that doesn't expect an event."""
        calls = []

        def handler():
            calls.append("called")

        signature = inspect.signature(handler)
        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = HandlerAdapter(async_handler, signature, bucket_fixture)

        assert not adapter.expects_event, "Adapter should detect that handler does not expect event"

        event = MockEvent("test_data")
        await adapter.call(event)
        assert calls == ["called"], "Handler should be called without event data"

    async def test_async_handler_no_event(self, bucket_fixture: TaskBucket):
        """Test async handler that doesn't expect an event."""
        calls = []

        async def handler():
            calls.append("called")

        signature = inspect.signature(handler)
        adapter = HandlerAdapter(handler, signature, bucket_fixture)

        assert not adapter.expects_event, "Adapter should detect that handler does not expect event"

        event = MockEvent("test_data")
        await adapter.call(event)
        assert calls == ["called"], "Handler should be called without event data"


class TestDebounceLogic:
    """Test debounce functionality."""

    async def test_debounce_delays_execution(self, bucket_fixture: TaskBucket):
        """Test that debounce delays execution until quiet period."""
        calls = []

        def handler(event):
            calls.append(event.data)

        signature = inspect.signature(handler)
        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = HandlerAdapter(async_handler, signature, bucket_fixture, debounce=0.1)

        # Fire multiple events quickly
        event1 = MockEvent("first")
        event2 = MockEvent("second")
        event3 = MockEvent("third")

        await adapter.call(event1)
        await adapter.call(event2)
        await adapter.call(event3)

        await asyncio.sleep(0)

        # Nothing should be called immediately
        assert calls == [], "No calls should be made immediately due to debounce"

        # Wait for debounce period plus some buffer
        await asyncio.sleep(0.2)

        # Only the last event should be processed
        assert calls == ["third"], "Only the last event should be processed after debounce"

    async def test_debounce_with_no_event_handler(self, bucket_fixture: TaskBucket):
        """Test debounce with handler that doesn't expect event."""
        calls = []

        def handler():
            calls.append("called")

        signature = inspect.signature(handler)
        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = HandlerAdapter(async_handler, signature, bucket_fixture, debounce=0.1)

        # Fire multiple events quickly
        event = MockEvent("data")
        await adapter.call(event)
        await adapter.call(event)
        await adapter.call(event)

        # Wait for debounce period
        await asyncio.sleep(0.2)

        # Should be called once
        assert calls == ["called"], "Handler should be called only once after debounce"

    async def test_debounce_cancels_previous_calls(self, bucket_fixture: TaskBucket):
        """Test that new calls cancel previous debounced calls."""
        calls = []

        async def handler(event):
            calls.append(event.data)

        signature = inspect.signature(handler)
        adapter = HandlerAdapter(handler, signature, bucket_fixture, debounce=0.2)

        # First call
        await adapter.call(MockEvent("first"))
        await asyncio.sleep(0.1)  # Wait 100ms
        assert adapter._debounce_task is not None, "Debounce task should be created"
        assert not adapter._debounce_task.done(), "Debounce task should still be pending"

        # Second call should cancel first
        await adapter.call(MockEvent("second"))
        await asyncio.sleep(0.1)  # Wait another 100ms
        assert adapter._debounce_task is not None, "Debounce task should be created"
        assert not adapter._debounce_task.done(), "Debounce task should still be pending"

        # Third call should cancel second
        await adapter.call(MockEvent("third"))

        # Wait for final debounce period
        await asyncio.sleep(0.3)

        # Only the last call should execute
        assert calls == ["third"], "Only the last call should be processed after debounce"
        assert adapter._debounce_task.done(), "Debounce task should be completed"


class TestThrottleLogic:
    """Test throttle functionality."""

    async def test_throttle_limits_execution_frequency(self, bucket_fixture: TaskBucket):
        """Test that throttle limits how often handler is called."""
        calls = []

        def handler(event):
            calls.append(event.data)

        signature = inspect.signature(handler)
        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = HandlerAdapter(async_handler, signature, bucket_fixture, throttle=0.1)

        # First call should execute immediately
        await adapter.call(MockEvent("first"))
        assert calls == ["first"], "First call should be executed immediately"

        # Subsequent calls within throttle period should be ignored
        await adapter.call(MockEvent("second"))
        await adapter.call(MockEvent("third"))
        assert calls == ["first"], "Subsequent calls should be ignored"

        # Wait for throttle period to pass
        await asyncio.sleep(0.15)

        # Now a new call should work
        await adapter.call(MockEvent("fourth"))
        assert calls == ["first", "fourth"], "Fourth call should be executed after throttle period"

    async def test_throttle_with_no_event_handler(self, bucket_fixture: TaskBucket):
        """Test throttle with handler that doesn't expect event."""
        calls = []
        test_string = "called"

        def handler():
            nonlocal test_string
            calls.append(test_string)

        signature = inspect.signature(handler)
        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = HandlerAdapter(async_handler, signature, bucket_fixture, throttle=0.1)

        # First call executes
        await adapter.call(MockEvent("data"))
        assert calls == ["called"], "First call should be executed immediately"

        # Subsequent calls are throttled
        test_string = "called while throttled"
        await adapter.call(MockEvent("data"))
        await adapter.call(MockEvent("data"))
        assert calls == ["called"], "Subsequent calls should be ignored"

        # After throttle period
        test_string = "called after throttle"
        await asyncio.sleep(0.15)
        await adapter.call(MockEvent("data"))
        assert calls == ["called", "called after throttle"], "Second call should be executed after throttle period"

    async def test_throttle_tracks_time_correctly(self, bucket_fixture: TaskBucket):
        """Test that throttle timing works correctly."""
        calls = []

        async def handler(event):
            calls.append(event.data)

        signature = inspect.signature(handler)
        adapter = HandlerAdapter(handler, signature, bucket_fixture, throttle=0.05)

        # Series of calls with different timing
        await adapter.call(MockEvent("1"))
        assert calls == ["1"]

        await asyncio.sleep(0.03)  # 30ms - should be throttled
        await adapter.call(MockEvent("2"))
        assert calls == ["1"]

        await asyncio.sleep(0.03)  # Total 60ms - should work now
        await adapter.call(MockEvent("3"))
        assert calls == ["1", "3"]


class TestListenerIntegration:
    """Test Listener integration with HandlerAdapter."""

    async def test_listener_with_debounce(self, bucket_fixture: TaskBucket):
        """Test Listener using debounce."""
        calls = []

        def handler(event):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner="test",
            topic="test_topic",
            handler=handler,
            debounce=0.1,
        )

        # Multiple rapid calls
        await listener.invoke(MockEvent("1"))
        await listener.invoke(MockEvent("2"))
        await listener.invoke(MockEvent("3"))

        # Wait for debounce period
        await asyncio.sleep(0.2)

        # Only last event processed
        assert calls == ["3"], "Only the last event should be processed after debounce"

    async def test_listener_with_throttle(self, bucket_fixture: TaskBucket):
        """Test Listener using throttle."""
        calls = []

        def handler(event):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner="test",
            topic="test_topic",
            handler=handler,
            throttle=0.1,
        )

        # Multiple rapid calls
        await listener.invoke(MockEvent("1"))
        await listener.invoke(MockEvent("2"))
        await listener.invoke(MockEvent("3"))

        # Only first should execute immediately
        assert calls == ["1"], "First call should be executed immediately"

        # Wait for throttle period
        await asyncio.sleep(0.15)

        # Now another call should work
        await listener.invoke(MockEvent("4"))
        assert calls == ["1", "4"], "Second call should be executed after throttle period"

    async def test_listener_without_rate_limiting(self, bucket_fixture: TaskBucket):
        """Test Listener without debounce or throttle."""
        calls = []

        def handler(event):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner="test",
            topic="test_topic",
            handler=handler,
        )

        # All calls should execute immediately
        await listener.invoke(MockEvent("1"))
        await listener.invoke(MockEvent("2"))
        await listener.invoke(MockEvent("3"))

        assert calls == ["1", "2", "3"], "All calls should be executed immediately"

    async def test_cannot_specify_both_debounce_and_throttle(self, bucket_fixture: TaskBucket):
        """Test that specifying both debounce and throttle raises an error."""

        def handler(event):
            pass

        with pytest.raises(ValueError, match="Cannot specify both 'debounce' and 'throttle'"):
            Listener.create(
                task_bucket=bucket_fixture,
                owner="test",
                topic="test_topic",
                handler=handler,
                debounce=0.1,
                throttle=0.1,
            )
