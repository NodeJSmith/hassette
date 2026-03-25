# Design: Rate Limiter Ownership & Observability

**Issues:** #427, #428, #429
**Status:** Draft
**Complexity:** Simple refactor (3 source files + tests)

## Problem

After PR #430 redesigned rate limiting, the `RateLimiter` is created inside `HandlerAdapter.__init__()` but orchestrated entirely by `BusService._dispatch`. HandlerAdapter never invokes it -- it's just a data holder for someone else's concern. This creates:

1. **3-layer reach-through** -- `listener.adapter.rate_limiter` appears 8 times in `bus_service.py`, violating Law of Demeter
2. **Misplaced ownership** -- `HandlerAdapter` imports and constructs `RateLimiter` but never calls it
3. **Zero observability** -- when throttle drops an event or debounce resets, nothing is logged or counted

## Architecture

### Change 1: Move RateLimiter to Listener (#428 subsumes #427)

Move rate limiter construction from `HandlerAdapter.__init__()` to `Listener.create()`. Store `rate_limiter` directly on the `Listener` dataclass.

**Before:**
```
Listener.create() --> HandlerAdapter(debounce=, throttle=) --> RateLimiter()
BusService reads: listener.adapter.rate_limiter  (8 sites)
```

**After:**
```
Listener.create() --> RateLimiter()  (stored on Listener)
                  --> HandlerAdapter()  (no rate_limiter knowledge)
BusService reads: listener.rate_limiter  (8 sites, 1 layer deep)
```

**Files changed:**
- `src/hassette/bus/listeners.py` -- add `rate_limiter` field to Listener dataclass, remove debounce/throttle from HandlerAdapter, remove RateLimiter import from HandlerAdapter
- `src/hassette/core/bus_service.py` -- replace all `listener.adapter.rate_limiter` with `listener.rate_limiter`
- Tests: update `listener.adapter.rate_limiter` references

### Change 2: Add observability (#429)

Add DEBUG-level logging and counters to `RateLimiter` for throttle drops and debounce resets.

**Files changed:**
- `src/hassette/bus/rate_limiter.py` -- add logger, DEBUG logs, `throttled_count` and `debounce_reset_count` counters

### Interface contract

```python
@dataclass(slots=True)
class Listener:
    # ... existing fields ...
    rate_limiter: RateLimiter | None = None

    def cancel_rate_limiter(self) -> None:
        """Cancel any pending rate limiter tasks."""
        if self.rate_limiter:
            self.rate_limiter.cancel()
```

```python
class RateLimiter:
    throttled_count: int = 0
    debounce_reset_count: int = 0
```

## Alternatives Considered

1. **Property delegation only (#427 as-is)** -- Add `Listener.rate_limiter` property that delegates to `self.adapter.rate_limiter`. Rejected: still misplaced ownership, just hides the reach-through.
2. **Keep on HandlerAdapter, expose via Listener property** -- Less churn, but HandlerAdapter still imports and constructs something it never uses. Rejected: doesn't fix the root cause.

## Test Strategy

- Update existing test assertions from `listener.adapter.rate_limiter` to `listener.rate_limiter`
- Verify `HandlerAdapter` no longer has `rate_limiter` attribute
- Add test for throttle drop logging (capture log output)
- Add test for debounce reset logging
- Verify counters increment correctly
