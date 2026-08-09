# Context: Fix Timing-Fragile Integration Tests

## Problem & Motivation
Several integration tests fail intermittently in CI because they race real wall-clock sleeps/timeouts against async dispatch work. CPU contention under pytest-xdist shifts timing margins enough to flip tests. This erodes CI confidence and wastes re-runs.

## Key Decisions
1. Inject a controlled `clock` callable into `RateLimiter` for the throttle test — makes it fully deterministic.
2. Add a `completed` asyncio.Event to `DurationTimer` so cancellation tests can await the timer lifecycle ending instead of sleeping.
3. Increase `DURATION` from 0.05s to 0.2s for all duration tests — wider real-time margins for partial-duration sleeps.
4. Increase shutdown-wave timeout from 0.05s to 0.5s — generous safety ceiling.
5. Defer entity-time and StateProxy readiness fixes — research assessed these as either "appears sound" or "needs CI data."
6. Split the coverage/watchdog false-positive to its own issue — genuinely different mechanism.

## Constraints
- Do NOT reintroduce `--reruns` or any retry-based workaround (#1322).
- Do NOT modify `TimeControlMixin` or application-level time control — that's #661.
- `RateLimiter.clock` parameter must default to `time.monotonic` so no production code changes behavior.
- `DurationTimer.completed` must be cleared on `start()` so restarted timers don't leak stale signals.
- Do NOT touch `tests/integration/test_scheduler_entity_time.py` or `tests/integration/test_app_test_harness.py` in this PR.
