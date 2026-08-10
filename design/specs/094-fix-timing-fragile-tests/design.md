# Design: Fix Timing-Fragile Integration Tests

**Date:** 2026-08-09
**Status:** draft
**Mode:** sketch

## Problem

Several integration tests fail intermittently in CI because they race real wall-clock sleeps/timeouts against async dispatch work. CPU contention under pytest-xdist shifts timing margins by tens of milliseconds, enough to flip a test from green to red. This erodes CI confidence and causes wasted re-runs.

## Goals

- Eliminate intermittent failures in the 5 identified subsystems
- Make fixes deterministic where possible (event-gated or controlled clock), practically deterministic elsewhere (generous safety-ceiling timeouts)
- Split the unrelated coverage/watchdog false-positive to its own issue
- No introduction of `--reruns` or similar retry-based workarounds (#1322)

## Non-Goals

- Full autojump clock (#661) — that is a separate, larger initiative
- Systematic real-clock timeout audit (#1503) — overlaps but is broader
- Changes to the `TimeControlMixin` or application-level time control

## Functional Requirements

- **FR#1** `RateLimiter` accepts an optional `clock` callable for `time.monotonic()`, defaulting to `time.monotonic`; throttle tests inject a controlled clock and advance it deterministically
- **FR#2** `DurationTimer` exposes a lifecycle completion signal — an `asyncio.Event` (`completed`) that is set when the timer finishes its cycle (either by firing or by cancellation), enabling tests to await "timer lifecycle done" instead of sleeping
- **FR#3** Duration test `DURATION` constant is increased from 0.05s to 0.2s and all partial-duration sleeps and margin timeouts are scaled proportionally
- **FR#4** Shutdown-wave test `resource_shutdown_timeout_seconds` is increased from 0.05s to 0.5s
- **FR#5** The coverage/loop-watchdog false-positive (`test_tier1_ignore_suppresses_warning_and_row`) is filed as a separate issue

## Acceptance Criteria

- **AC#1** (FR#1) `test_listener_with_throttle` passes deterministically — no `asyncio.sleep` in the throttle test path; the injected clock is advanced programmatically
- **AC#2** (FR#2) Duration cancellation tests (`test_duration_cancelled_on_state_exit`, `test_duration_subscription_cancel_stops_timer`, `test_changed_from_with_duration_cancels_on_revert`) await `timer.completed` instead of `asyncio.sleep(DURATION + margin)` then assert
- **AC#3** (FR#3) All duration tests pass under repeated runs (`pytest --count=20 -x tests/integration/bus/test_bus_duration.py`)
- **AC#4** (FR#4) `test_force_terminates_wave_on_timeout_and_returns_false` passes under repeated runs (`pytest --count=20 -x tests/unit/core/test_core_coverage.py::TestShutdownChildren::test_force_terminates_wave_on_timeout_and_returns_false`)
- **AC#5** (FR#5) A new issue exists on the tracker for the coverage/watchdog false-positive, labeled appropriately
- **AC#6** The full integration + unit test suite passes: `uv run nox -s dev` (verified at pre-commit gate, not by individual tasks)
- **AC#7** Lint + type check passes: `prek -a && prek pyright -a --stage pre-push` (verified at pre-commit gate, not by individual tasks)

## Approach

### 1. Injectable clock for RateLimiter (FR#1)

Add an optional `clock: Callable[[], float] = time.monotonic` parameter to `RateLimiter.__init__()` in `src/hassette/bus/rate_limiter.py`. Replace the `time.monotonic()` call in `throttled_call()` with `self._clock()`. The test injects a lambda that returns a mutable float (starting at `1.0` — not `0.0`, since `_throttle_last_time` defaults to `0.0` and the throttle guard would suppress the first call), advancing it past the throttle window without any `asyncio.sleep`.

The `BusService` constructs `RateLimiter` in `_build_rate_limiter()` — no change needed there since the default is `time.monotonic`.

### 2. DurationTimer lifecycle event (FR#2)

Add a `completed: asyncio.Event` attribute to `DurationTimer.__init__()` in `src/hassette/bus/duration_timer.py`. Set it at the end of `delayed_fire()` (after handler invocation or guard skip) and at the end of `cancel()`. Clear it in `start()` when a new cycle begins. This lets cancellation tests do `await timer.completed.wait()` instead of `asyncio.sleep(DURATION + margin)`.

To access the timer from tests: `DurationTimer` instances are stored on each `Listener`'s `DurationConfig` (`listener.duration_config.timer`). The test can get the listener via `harness.bus_service.router.get_topic_listeners(topic)` and access its timer.

### 3. Widen duration test margins (FR#3)

In `tests/integration/bus/conftest.py`, change `DURATION = 0.05` to `DURATION = 0.2`. All tests in the module use this constant, so partial-duration sleeps (`DURATION * 0.4` = 80ms instead of 20ms) gain proportionally wider real-time margins. The `asyncio.wait_for` safety ceilings (`DURATION + 0.5`) remain generous.

For cancellation tests that currently do `asyncio.sleep(DURATION + 0.1)` then assert, switch to awaiting the new `completed` event with a generous `wait_for` timeout.

### 4. Widen shutdown-wave timeout (FR#4)

In `tests/unit/core/test_core_coverage.py`, change `resource_shutdown_timeout_seconds = 0.05` to `0.5` in `test_force_terminates_wave_on_timeout_and_returns_false`. The hanging child sleeps 1000s, so any timeout under 10s triggers force-termination. The 0.5s value gives 10x+ margin over CI scheduling jitter.

### 5. Entity-time tests (deferred)

The research brief assessed subsystem 1 (scheduler entity-time `change_alarm()`) as "appears sound" — `await_dispatch_idle()` is already event-driven. The issue body lists 3 observed failures here, but the mechanism (`_dispatch_idle_event`) is correct. If these still flake after the other fixes land, the root cause is likely that EntityTime's re-scheduling task runs outside `_dispatch_pending` tracking, which would need a targeted follow-up.

### 6. StateProxy readiness (deferred)

The research brief noted this needs CI failure data to diagnose. `StateProxy.on_initialize()` calls `mark_ready()` synchronously, so the children-ready wait should resolve quickly. If this still flakes, the fix is increasing the `WAIT_FOR_READY` timeout — but we need a reproduction first.

### 7. Coverage/watchdog issue (FR#5)

File a new issue for `test_tier1_ignore_suppresses_warning_and_row`. Different root cause: coverage.py's sysmon/settrace tracing adds genuine event-loop overhead that triggers the watchdog threshold. The fix is either increasing `lag_threshold_seconds` in the test or suppressing watchdog warnings when `COVERAGE_PROCESS_START` is set.

## Changed Files

- modify: `src/hassette/bus/rate_limiter.py` — add optional `clock` parameter, use it in `throttled_call()`
- modify: `src/hassette/bus/duration_timer.py` — add `completed` asyncio.Event, set on fire/cancel, clear on start
- modify: `tests/integration/bus/conftest.py` — change `DURATION` from 0.05 to 0.2
- modify: `tests/integration/bus/test_bus_duration.py` — use `completed` event for cancellation assertions; adjust margins
- modify: `tests/integration/bus/CLAUDE.md` — update documented `DURATION` value from 0.05 to 0.2
- modify: `tests/integration/test_listeners.py` — rewrite throttle test to use injected clock
- modify: `tests/unit/bus/test_duration_timer.py` — regression test for a restart-while-active race in `DurationTimer.completed` found during review
- modify: `docs/pages/core-concepts/internals/service-details.md` — document `RateLimiter`'s injectable `clock` parameter
- create: `design/specs/094-fix-timing-fragile-tests/known-issues.md` — KI-001/KI-002, deferred out-of-scope test-hygiene findings from T01
- modify: `tests/unit/core/test_core_coverage.py` — increase shutdown timeout from 0.05 to 0.5
