---
task_id: "T01"
title: "Inject controlled clock into RateLimiter and rewrite throttle test"
status: "done"
depends_on: []
implements: ["FR#1", "AC#1"]
---

## Target Files

- modify: `src/hassette/bus/rate_limiter.py`
- modify: `tests/integration/test_listeners.py`

## Prompt

Add an optional `clock` parameter to `RateLimiter.__init__()` in `src/hassette/bus/rate_limiter.py`:

```python
def __init__(
    self,
    task_bucket: "TaskBucket",
    debounce: float | None = None,
    throttle: float | None = None,
    handler_name: str = "unknown",
    clock: "Callable[[], float] | None" = None,
):
```

Store as `self._clock = clock or time.monotonic`. Replace the `time.monotonic()` call in `throttled_call()` (line 143) with `self._clock()`. There is only one call site to replace.

Add `Callable` to the `TYPE_CHECKING` imports if not already there.

In `tests/integration/test_listeners.py`, rewrite `TestListenerIntegration::test_listener_with_throttle` (line 374):

1. Create a mutable clock: `clock_time = [1.0]` and `clock = lambda: clock_time[0]`. Start at `1.0`, NOT `0.0` — `_throttle_last_time` defaults to `0.0`, and the throttle guard (`now - _throttle_last_time < throttle`) would suppress the first call if `now` is also `0.0`.
2. Create the listener with `throttle=0.1` and pass `clock=clock` to the `RateLimiter` constructor. Since `create_listener()` constructs the `RateLimiter` internally, you'll need to either:
   - Construct the `RateLimiter` directly with `clock=clock` and assign it to `listener.invoker.rate_limiter`, OR
   - Access `listener.invoker.rate_limiter._clock` and replace it after construction (less clean but simpler)

   The cleanest approach: after `create_listener(...)`, replace the rate limiter: `listener.invoker.rate_limiter = RateLimiter(task_bucket=bucket, throttle=0.1, handler_name="test", clock=clock)`.
3. Fire events 1-3 at `clock_time = [1.0]` — event 1 executes, events 2-3 are throttled.
4. Advance: `clock_time[0] = 1.2` (past the 0.1s window).
5. Fire event 4 — it executes.
6. Assert `calls == ["1", "4"]`.
7. Remove the `await asyncio.sleep(0.15)` entirely — no wall-clock sleep needed.

## Verify

- [ ] FR#1: `RateLimiter.__init__` accepts `clock` parameter, defaults to `time.monotonic`
- [ ] AC#1: `test_listener_with_throttle` contains no `asyncio.sleep` and passes: `uv run pytest tests/integration/test_listeners.py::TestListenerIntegration::test_listener_with_throttle -v`
