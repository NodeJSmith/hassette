"""Debounce, throttle, and rate-limiter cancellation behavior."""

import asyncio

from hassette.bus.rate_limiter import RateLimiter
from hassette.task_bucket import TaskBucket
from hassette.test_utils import make_controlled_clock, wait_for
from hassette.test_utils.helpers import settle


class TestDebounceLogic:
    """Test debounce functionality via RateLimiter directly."""

    async def test_debounce_delays_execution(self, bucket: TaskBucket):
        """Test that debounce delays execution until quiet period."""
        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket, debounce=0.1)

        await limiter.call(make_handler("first"))
        await limiter.call(make_handler("second"))
        await limiter.call(make_handler("third"))

        await asyncio.sleep(0)
        assert calls == [], "No calls should be made immediately due to debounce"

        await wait_for(lambda: calls == ["third"], desc="debounce fired")

    async def test_debounce_with_no_args(self, bucket: TaskBucket):
        """Test debounce with a no-arg handler."""
        calls: list[str] = []

        async def handler():
            calls.append("called")

        limiter = RateLimiter(bucket, debounce=0.1)

        await limiter.call(handler)
        await limiter.call(handler)
        await limiter.call(handler)

        await wait_for(lambda: calls == ["called"], desc="debounce fired")

    async def test_debounce_cancels_previous_calls(self, bucket: TaskBucket):
        """Test that new debounce calls cancel previous pending calls."""
        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket, debounce=0.2)

        await limiter.call(make_handler("first"))
        # timing: mid-debounce assertion — must be within the 0.2s window
        await asyncio.sleep(0.1)
        assert limiter._debounce_task is not None, "Debounce task should be created"
        assert not limiter._debounce_task.done(), "Debounce task should still be pending"

        await limiter.call(make_handler("second"))
        # timing: mid-debounce assertion — must be within the 0.2s window
        await asyncio.sleep(0.1)
        assert not limiter._debounce_task.done(), "Debounce task should still be pending"

        await limiter.call(make_handler("third"))

        await wait_for(lambda: calls == ["third"], desc="debounce fired")
        # done_callback is scheduled via call_soon, so it may not have run yet
        await wait_for(lambda: limiter._debounce_task is None, desc="debounce task reference cleared")

    async def test_debounce_handler_cancelled_error_propagates(self, bucket: TaskBucket):
        """CancelledError during handler execution must propagate (not be suppressed).

        Debounce reset (cancel during sleep) should be silent, but handler cancellation
        (e.g., shutdown) should propagate so telemetry can record it as 'cancelled'.
        """

        async def handler_that_gets_cancelled():
            raise asyncio.CancelledError()

        limiter = RateLimiter(bucket, debounce=0.01)
        await limiter.call(handler_that_gets_cancelled)

        # Capture task reference before done_callback clears it
        task = limiter._debounce_task
        assert task is not None

        await wait_for(lambda: task.done(), desc="debounce task completed")

        # The task should show as cancelled (CancelledError propagated out of delayed_call)
        assert task.done()
        assert task.cancelled(), "Handler CancelledError should propagate, not be suppressed"

    async def test_debounce_reset_cancellation_is_silent(self, bucket: TaskBucket):
        """CancelledError from debounce reset (new event superseding old) should be silent."""
        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        limiter = RateLimiter(bucket, debounce=0.1)

        # First call starts debounce
        await limiter.call(make_handler("first"))
        first_task = limiter._debounce_task
        assert first_task is not None

        # Second call cancels first (debounce reset)
        await limiter.call(make_handler("second"))
        await asyncio.sleep(0)  # Let cancellation propagate

        # First task should be cancelled silently (no crash)
        assert first_task.cancelled() or first_task.done()

        await wait_for(lambda: calls == ["second"], desc="debounce fired")


class TestRateLimiterCancel:
    """Test RateLimiter.cancel() for cleanup on listener removal."""

    async def test_cancel_pending_debounce(self, bucket: TaskBucket):
        """Cancelling a pending debounce prevents the handler from firing."""
        calls: list[str] = []

        async def handler():
            calls.append("fired")

        limiter = RateLimiter(bucket, debounce=0.5)
        await limiter.call(handler)
        assert limiter._debounce_task is not None

        limiter.cancel()
        assert limiter._debounce_task is None

        await settle(0.6)
        assert calls == [], "Handler should not fire after cancel"

    async def test_cancel_when_no_task(self, bucket: TaskBucket):
        """Cancelling with no pending task should not raise."""
        limiter = RateLimiter(bucket, debounce=0.1)
        limiter.cancel()  # Should not raise

    async def test_cancel_after_task_completed(self, bucket: TaskBucket):
        """Cancelling after the task has already completed should not raise."""
        calls: list[str] = []

        async def handler():
            calls.append("fired")

        limiter = RateLimiter(bucket, debounce=0.01)
        await limiter.call(handler)
        await wait_for(lambda: calls == ["fired"], desc="debounce fired")

        limiter.cancel()  # Should not raise; task already done


class TestThrottleLogic:
    """Test throttle functionality via RateLimiter directly."""

    async def test_throttle_limits_execution_frequency(self, bucket: TaskBucket):
        """Test that throttle limits how often handler is called."""
        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        clock = make_controlled_clock()
        limiter = RateLimiter(bucket, throttle=0.1, clock=clock)

        await limiter.call(make_handler("first"))
        assert calls == ["first"], "First call should be executed immediately"

        await limiter.call(make_handler("second"))
        await limiter.call(make_handler("third"))
        assert calls == ["first"], "Subsequent calls should be ignored"

        # advance the controlled clock past the throttle window before the next call
        clock.advance_to(1.2)

        await limiter.call(make_handler("fourth"))
        assert calls == ["first", "fourth"], "Fourth call should execute after throttle period"

    async def test_throttle_allows_first_call_with_zero_origin_clock(self, bucket: TaskBucket):
        """A clock that legitimately returns 0.0 on its first call must not drop that call.

        Regression test: `_throttle_last_time` used to default to `0.0`, so `now - 0.0 <
        throttle` was true on the very first call whenever `now` was also `0.0`, silently
        dropping it. `_throttle_last_time` now starts as `None` and the elapsed-window
        check is bypassed until a timestamp has actually been recorded.
        """
        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        clock = make_controlled_clock(start=0.0)
        limiter = RateLimiter(bucket, throttle=0.1, clock=clock)

        await limiter.call(make_handler("first"))
        assert calls == ["first"], "First call must execute even when the clock starts at 0.0"

    async def test_throttle_with_no_args(self, bucket: TaskBucket):
        """Test throttle with a no-arg handler."""
        calls: list[str] = []
        label = "called"

        async def handler():
            calls.append(label)

        clock = make_controlled_clock()
        limiter = RateLimiter(bucket, throttle=0.1, clock=clock)

        await limiter.call(handler)
        assert calls == ["called"]

        label = "called while throttled"
        await limiter.call(handler)
        await limiter.call(handler)
        assert calls == ["called"]

        label = "called after throttle"
        # advance the controlled clock past the throttle window before the next call
        clock.advance_to(1.2)
        await limiter.call(handler)
        assert calls == ["called", "called after throttle"]

    async def test_throttle_tracks_time_correctly(self, bucket: TaskBucket):
        """Test that throttle timing works correctly using an injected clock."""
        calls: list[str] = []

        def make_handler(label: str):
            async def handler():
                calls.append(label)

            return handler

        clock = make_controlled_clock(start=1000.0)

        limiter = RateLimiter(bucket, throttle=0.05, clock=clock)

        await limiter.call(make_handler("1"))
        assert calls == ["1"]

        clock.advance_to(1000.03)
        await limiter.call(make_handler("2"))
        assert calls == ["1"]

        clock.advance_to(1000.06)
        await limiter.call(make_handler("3"))
        assert calls == ["1", "3"]

    async def test_throttle_does_not_block_during_handler(self, bucket: TaskBucket):
        """A second throttled call within the window must not block on the first handler."""
        handler_started = asyncio.Event()
        handler_release = asyncio.Event()

        async def slow_handler():
            handler_started.set()
            await handler_release.wait()

        limiter = RateLimiter(bucket, throttle=5.0)

        task1 = asyncio.create_task(limiter.call(slow_handler))
        await handler_started.wait()

        task2 = asyncio.create_task(limiter.call(slow_handler))
        done, _ = await asyncio.wait({task2}, timeout=0.05)
        assert task2 in done, "Throttled call within window must return immediately, not block"

        handler_release.set()
        await task1
