# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Other RateLimiter throttle tests still use real-time sleep/patch instead of clock injection

Status: open
Run: 64
Source: T01
Reason not fixed now: out-of-scope
Observed in: T01
Affected files:
- tests/integration/test_listeners.py

Issue:
T01 added an injectable `clock` parameter to `RateLimiter` and rewrote `test_listener_with_throttle`
to use it instead of `asyncio.sleep`. Two sibling tests in the same file —
`test_throttle_limits_execution_frequency` and `test_throttle_with_no_args` — still use real
`asyncio.sleep(0.15)` to cross the throttle window (the same class of CI timing flakiness this
issue is about). A third, `test_throttle_tracks_time_correctly`, uses
`unittest.mock.patch("hassette.bus.rate_limiter.time.monotonic")` — a different deterministic
technique than clock injection. The file now has three different mechanisms for controlling
throttle timing in tests of the same class.

Why deferred:
T01's task spec named only `test_listener_with_throttle` for rewrite. Migrating the other two
tests to clock injection is straightforward but expands scope beyond the approved task — it
wasn't part of #1571's stated fix list, and the two `asyncio.sleep`-based tests aren't flagged in
the parent issue's list of flaky tests.

Recommended follow-up:
Migrate `test_throttle_limits_execution_frequency` and `test_throttle_with_no_args` to use the
new `clock` injection point on `RateLimiter`, and consider standardizing on injection over
`patch(time.monotonic)` for `test_throttle_tracks_time_correctly` too, so the file converges on
one technique.

Acceptance criteria:
- All throttle-timing tests in `tests/integration/test_listeners.py` use `RateLimiter`'s injected
  `clock` parameter instead of `asyncio.sleep` or `unittest.mock.patch`.

## KI-002: Throttle-clock test bypasses the create_listener() factory

Status: open
Run: 64
Source: T01
Reason not fixed now: out-of-scope
Observed in: T01
Affected files:
- tests/integration/test_listeners.py
- src/hassette/test_utils/helpers.py (would need a new `clock` passthrough parameter)

Issue:
Every other listener test in `test_listeners.py` builds a `Listener` purely through
`create_listener(...)` kwargs. `test_listener_with_throttle` (T01) instead calls
`create_listener(..., throttle=0.1)`, discards the `RateLimiter` it constructs, and replaces
`listener.invoker.rate_limiter` with a hand-built `RateLimiter` carrying the injected clock —
because `create_listener()` has no `clock` passthrough parameter.

Why deferred:
Threading a `clock` parameter through the shared `create_listener()` factory (and possibly
`ListenerOptions`) is a reasonable improvement, but it's a change to shared test infrastructure
used across many test files — outside T01's stated scope (the `RateLimiter` constructor plus one
test) and outside this task's target files.

Recommended follow-up:
Add an optional `clock` parameter to `create_listener()` in `src/hassette/test_utils/helpers.py`
that passes through to the constructed `RateLimiter`, then update `test_listener_with_throttle`
to use it instead of manually reconstructing the rate limiter.

Acceptance criteria:
- `create_listener()` accepts an optional `clock` parameter and passes it to the `RateLimiter` it
  constructs.
- `test_listener_with_throttle` no longer manually reconstructs `RateLimiter`.
