---
proposal: "Fix timing-fragile integration tests that fail intermittently across 5 subsystems"
date: 2026-08-09
status: Draft
flexibility: Exploring
motivation: "CI unreliability — flaky test failures cause re-runs, lost confidence in green builds"
constraints: "Must not regress existing passing tests. Must work with Python 3.11-3.13 and pytest-xdist."
non-goals: "Full autojump clock (issue #661) — that is a separate, larger initiative"
depth: deep
---

# Research Brief: Timing-Fragile Test Fixes

**Initiated by**: Fix intermittently failing integration tests that race real wall-clock timeouts/sleeps against actual dispatch/scheduling work.

## Context

### What prompted this

Several integration tests fail intermittently in CI. They share a common pattern: a test asserts something about timing (a handler fired, a timer elapsed, a shutdown completed) using real wall-clock `asyncio.sleep()` or `asyncio.wait_for()` with margins measured in fractions of a second. On CI machines under load (or with pytest-xdist worker scheduling jitter), these margins are occasionally insufficient.

### Current state

The codebase already has sophisticated time-control infrastructure:

**TimeControlMixin** (`src/hassette/test_utils/time_control.py`) patches `hassette.utils.date_utils.now` with a `_TestClock` object. `advance_time()` mutates the frozen clock and `trigger_due_jobs()` manually dispatches scheduled jobs. This controls *application-level* time (what the framework thinks "now" is for scheduling decisions) but does NOT control the asyncio event loop clock — `asyncio.sleep()`, `call_later()`, and `asyncio.wait_for()` all use the real monotonic clock.

**await_dispatch_idle()** (`src/hassette/core/bus_service.py:639`) is an event-driven wait that blocks until all dispatched handler tasks have completed, with a stability check (5ms `asyncio.sleep`) to handle in-transit events. This is the correct mechanism for waiting on handler completion. Its docstring explicitly states: "Duration timer callbacks are NOT tracked here."

**DurationTimer** (`src/hassette/bus/duration_timer.py`) uses `asyncio.sleep(duration)` internally to implement the hold timer. This is real wall-clock time that cannot be controlled by `TimeControlMixin`.

**RateLimiter** (`src/hassette/bus/rate_limiter.py`) uses `asyncio.sleep(debounce)` for debounce and `time.monotonic()` for throttle window tracking. Both are real wall-clock.

**Issue #661** (autojump clock) proposes replacing the two-step `advance_time() + trigger_due_jobs()` with a virtual clock that auto-advances when all tasks are idle, inspired by Trio's `MockClock(autojump_threshold=0)`. This is a larger initiative (size:large, priority:low) and is distinct from the immediate timing-fragile test fixes.

**Issue #1503** (real-clock timeout audit) tracks a systematic audit of tests that override production timeout configs to small values while having their own deliberate real-time holds — the same race pattern that broke `test_app_bootstrap_waits_for_first_websocket_connection_and_state_sync`. This overlaps with some of the tests in scope here.

### Key constraints

- Python 3.11-3.13 compatibility required (3.12+ uses `sys.monitoring` for coverage instead of `settrace`)
- pytest-xdist parallelism — tests run across multiple workers on CI
- The framework's production code uses `asyncio.sleep()`, `call_later()`, and `time.monotonic()` in hot paths (DurationTimer, RateLimiter, LoopWatchdog) — any clock control solution must interact correctly with these
- The existing `TimeControlMixin` controls application-level time only; asyncio loop time is separate

## Findings by Subsystem

### 1. Scheduler Entity-Time (`change_alarm()`)

**Root cause**: The `change_alarm()` helper (`tests/integration/test_scheduler_entity_time.py:54`) sends a state-change event and then calls `await harness.bus_service.await_dispatch_idle()`. This works correctly — `await_dispatch_idle()` is event-driven (waits on `_dispatch_idle_event`, not a wall-clock poll) and has a 2-second default timeout. The stability sleep is only 5ms.

**Assessment**: This subsystem appears sound. `await_dispatch_idle()` uses `asyncio.Event.wait()` under the hood, gated by the `_dispatch_pending` counter. It fires immediately when all dispatched tasks complete. The 5ms stability sleep is a single yield, not a timing-sensitive margin. If this test is flaking, the root cause is likely upstream — either the event dispatch path has a race where `_dispatch_pending` is not yet incremented when the event is sent, or the state-change listener for the EntityTime trigger spawns work that completes outside the dispatch tracking window.

**Available signals**: `_dispatch_idle_event` (asyncio.Event), `_dispatch_pending` counter, and `ScheduleStatus` transitions on the Job object. The scheduler's `kick()` mechanism (`_wakeup_event`) could also be observed.

**Recommended fix**: Verify whether this test actually flakes. If it does, the issue is likely that the EntityTime trigger's state-change listener spawns a re-scheduling task that runs outside the `_dispatch_pending` tracking. The fix would be to also await the job's schedule status transition (e.g., `await wait_for(lambda: job.schedule_status == ScheduleStatus.SCHEDULED, ...)`), which is what several of the tests already do (lines 144-146).

### 2. Listener Throttle (`test_listener_with_throttle`)

**Root cause** (`tests/integration/test_listeners.py:374`): The test creates a listener with `throttle=0.1` (100ms window), calls the handler immediately, then does `await asyncio.sleep(0.15)` to advance past the throttle window before calling again. The 50ms margin (150ms - 100ms) is vulnerable to CI scheduling jitter.

**Mechanism**: The `RateLimiter.throttled_call()` (`src/hassette/bus/rate_limiter.py:134`) uses `time.monotonic()` to track the last call time. The throttle check is `now - self._throttle_last_time < self.throttle`. This is purely wall-clock — there is no observable signal when the throttle window expires.

**Why this is fragile**: `time.monotonic()` reads occur at two points: (1) when the first call runs (setting `_throttle_last_time`), and (2) when the fourth call runs after the sleep. If the first call's `time.monotonic()` read happens slightly later than expected (e.g., due to context switching between `await rl.call(make_invoke(events[0]))` and the sleep), the effective window shrinks. The 50ms margin is enough for most runs but not all.

**Recommended fix**: Two options:
- **Option A (widen margin)**: Change `asyncio.sleep(0.15)` to `asyncio.sleep(0.25)` or even `asyncio.sleep(0.5)`. Simple, keeps the test's intent clear, and 150% margin is usually sufficient. Disadvantage: the test takes longer.
- **Option B (mock time.monotonic)**: Inject a controllable clock into `RateLimiter`. The rate limiter already takes a `task_bucket` in its constructor; adding an optional `clock: Callable[[], float] = time.monotonic` parameter would let the test control time without real sleeps. More robust but requires a production code change.
- **Option C (event-gate the window)**: Not feasible — the throttle window expiry has no observable signal by design.

### 3. Harness Readiness / StateProxy (`test_simulate_state_change_none_new_value`)

**Root cause** (`tests/integration/test_app_test_harness.py:350`): This test uses `AppTestHarness`, which during `_setup()` calls `start_children_and_wait()` with a `WAIT_FOR_READY` timeout of 5 seconds. If any child resource (including StateProxy) does not call `mark_ready()` within 5 seconds, the harness raises `TimeoutError`.

**StateProxy readiness path**: `StateProxy.on_initialize()` (`src/hassette/core/state_proxy.py:218`) calls `mark_ready()` immediately and then spawns `_bootstrap_initial_sync()` in the background. So StateProxy itself should become ready quickly. The `_maybe_wait_for_state_capability()` then waits for `wait_initial_state_capability()`, which requires the bootstrap to complete.

**Where it gets stuck**: The `HassetteHarness._start_state_proxy()` method creates a `Mock()` for the websocket service and calls `_configure_ready_websocket_mock()`, which sets `get_connected_generation()` to return `1`. With a non-None generation, `_maybe_wait_for_state_capability()` will wait for `wait_initial_state_capability()`. The bootstrap sync inside StateProxy tries to load states from the API and process them. If the mock API's `get_states_raw` returns `[]` (which it does), the bootstrap should complete quickly.

**Assessment**: If this test flakes, the most likely cause is the 5-second `WAIT_FOR_READY` timeout being too tight when CI is under load, or a race in the StateProxy bootstrap path where the initial state capability event is set before the wait begins (lost wakeup). The `wait_initial_state_capability()` uses an `asyncio.Event`, so a lost wakeup would mean the event was set before anyone was listening. Given that `mark_ready()` happens synchronously before the bootstrap task is spawned, and the harness waits for children ready before waiting for state capability, this ordering should be safe.

**Recommended fix**: Increase the `WAIT_FOR_READY` timeout if needed, or add diagnostic logging to identify exactly which child is stuck. The `start_children_and_wait()` timeout error already includes child statuses in the message, so the first step is to capture the actual failure message from CI.

### 4. Duration-Hold Timer

**Root cause** (`tests/integration/bus/test_bus_duration.py`): The entire duration test suite uses `DURATION = 0.05` (50ms) as the timer value, with margins of 0.1-0.5 seconds for `asyncio.wait_for()` timeouts. The `DurationTimer.start()` method (`src/hassette/bus/duration_timer.py:96`) spawns a task that does `await asyncio.sleep(sleep_duration)` — this is real wall-clock time.

**Why even 10x margin fails**: The comment at the top of the file states "Duration tests use `asyncio.sleep(duration + margin)` to advance the clock — duration timers are not tracked by dispatch_pending, so await_dispatch_idle() cannot be used to drain them." The problem is not the margin on the `wait_for` timeout — that is generous (DURATION + 0.5 = 550ms for a 50ms timer). The problem is in tests that assert something did NOT happen: `test_duration_cancelled_on_state_exit` does `await asyncio.sleep(DURATION + 0.1)` and then asserts `received == []`. If the timer fires slightly late (due to CI load) and the assertion runs before the handler completes, the test passes for the wrong reason. Conversely, if the sleep wakes early, it might assert too soon.

But the more fundamental issue is in multi-step tests like `test_duration_resets_on_re_entry` (line 82): it sleeps `DURATION * 0.4` (20ms), sends events, then waits `DURATION + 0.5` for the fire. The 20ms partial-duration sleep is extremely fragile — CI scheduling jitter can easily push this past the 50ms duration window.

**Observable signals**: The `DurationTimer` has an `is_active` property and the `DurationHoldManager` tracks `_duration_timers_active` count. The handler sets an `asyncio.Event` (`fired`), which is already used in most tests. The problem is specifically the tests that need to assert "the timer has NOT fired yet" or "the timer was cancelled" — there is no "timer cancelled" event.

**Recommended fix**: Three complementary changes:
1. **Increase DURATION**: Change from 0.05 (50ms) to 0.2 or 0.3 seconds. This provides more real-time margin for partial-duration sleeps. Cost: tests take slightly longer.
2. **Add a timer-lifecycle event**: Have `DurationTimer` set an `asyncio.Event` (or invoke a callback) on cancellation and on fire. The tests that assert "did not fire" can then use `await wait_for(lambda: not timer.is_active, ...)` followed by `assert received == []`.
3. **Use `asyncio.Event` instead of `asyncio.sleep` for positive cases**: For tests that assert "handler fires", the `fired` event pattern already works. The margin on `asyncio.wait_for(fired.wait(), timeout=DURATION + 0.5)` is 500ms, which is generous.

### 5. Shutdown-Wave (`test_force_terminates_wave_on_timeout_and_returns_false`)

**Root cause** (`tests/unit/core/test_core_coverage.py:301`): The test sets `resource_shutdown_timeout_seconds = 0.05` (50ms), makes one child's `shutdown()` hang forever (`await asyncio.sleep(1000)`), then asserts `_shutdown_children()` returns `False` (meaning the wave timed out and was force-terminated).

**Why this is fragile**: The `_shutdown_children()` method (`src/hassette/core/core.py:728`) uses `async with asyncio.timeout(timeout)` around `asyncio.gather()`. With a 50ms timeout, the `asyncio.timeout` context manager must fire before the test's overall timeout, and the `_force_terminal()` call must complete before the assertion. On a loaded CI machine, 50ms might be consumed by context switching before `asyncio.gather` even starts.

**Recommended fix**: Increase the timeout from 0.05 to 0.5 seconds. The test's logic is "does a hanging child trigger force-termination?" — the specific timeout value does not matter as long as it is shorter than the test's own timeout. The hanging child sleeps for 1000 seconds, so any timeout under ~10 seconds will trigger the force-termination path. Cost: the test takes 0.5s instead of 0.05s.

### 6. Coverage/Loop Watchdog (`test_tier1_ignore_suppresses_warning_and_row`)

**Root cause** (`tests/integration/telemetry/test_blocking_io_executor_offload.py:408`): The test configures a watchdog with `lag_threshold_seconds=0.05` and `watchdog_interval_seconds=0.1`, then does `time.sleep(0.3)` to stall the loop, followed by `await asyncio.sleep(0.4)` to let the watchdog recover and process the episode.

**Mechanism**: The `LoopWatchdog` runs a daemon thread that checks `time.monotonic() - self._last_tick` against `lag_threshold_seconds`. The daemon thread polls every `watchdog_interval_seconds / 3` (33ms). The in-loop tick callback updates `_last_tick` via `call_later`. When coverage's sysmon tracer (Python 3.12+) or settrace tracer (3.11) is active, it adds overhead to every bytecode instruction, which can cause the in-loop tick callback to be delayed — potentially enough to exceed the `lag_threshold_seconds` even without an intentional `time.sleep()`.

**Is this the same issue?** No — this is a genuinely different mechanism. The other tests in scope have fragile margins on intentional timing assertions. This test has a different problem: coverage instrumentation causes real event-loop stalls that trigger the watchdog even when no user code is blocking. The fix is fundamentally different: either suppress the watchdog during coverage runs, or increase the lag threshold when coverage is detected.

**Assessment**: The codebase already has a pattern for handling coverage interference — see `skip_c_blocked_under_coverage_py311` in `tests/unit/test_sync_executor_service_saturation.py:62`, which skips tests that deadlock under coverage's settrace tracer on Python 3.11. The watchdog test could use a similar approach, but since it needs to verify that the watchdog works correctly, skipping defeats the purpose.

**Recommended approach**: Split off as a separate issue. The fix is to increase `lag_threshold_seconds` in the test from 0.05 to a value that exceeds coverage-induced overhead (0.2-0.3 seconds), and proportionally increase the `time.sleep()` stall to remain well above the threshold. This keeps the test meaningful while avoiding false triggers.

## Controlled Clock Assessment

### Should the project adopt a virtual/controlled clock?

**Short answer**: Not for this fix batch. A controlled asyncio clock is the right long-term solution (issue #661), but it is a large investment that addresses a broader set of problems.

### Available libraries

| Library | Approach | Maintained | Python 3.11+ | asyncio.sleep patching | loop.time patching |
|---------|----------|------------|--------------|----------------------|-------------------|
| `time-machine` | C extension, patches `time.time`/`time.monotonic` | Yes (active) | Yes | No (removed `monotonic` patching due to asyncio freezes) | No |
| `aiofastforward` | Patches `loop.call_later`, `loop.call_at`, `loop.time`, `asyncio.sleep` | Unclear (last PyPI 0.0.19) | Likely (claims 3.5+) | Yes | Yes |
| `asynciotimemachine` | Monkey-patches `AbstractEventLoop.time` | Last release 2021 | No (supports 3.6-3.9) | No | Yes (partially) |
| `timeless-loop` | Custom event loop implementation | Last release 2024 | Possibly | Yes (via custom loop) | Yes (custom loop) |

**`time-machine`** explicitly removed `time.monotonic()` mocking because it caused asyncio event loops to freeze (their issue #387). This makes it unsuitable for controlling `asyncio.sleep()` and `call_later()`, which use the loop's monotonic clock.

**`aiofastforward`** is the closest match — it patches exactly the primitives that `DurationTimer` and `RateLimiter` use. However, its maintenance status is unclear and it would need validation against Python 3.13's event loop internals.

### What issue #661 proposes

The autojump clock (issue #661) envisions a deeper integration: a custom event loop clock that auto-advances when all tasks are idle, similar to Trio's `MockClock`. The prior art research (`design/research/2026-05-02-test-infrastructure-design/research.md`) documents Pattern 1 (Virtual Clock with Autojump) as the ideal solution, but notes it "requires framework integration with the event loop (can't bolt onto vanilla asyncio easily)."

### Integration cost

Adopting `aiofastforward` or building a custom clock would require:
1. Validating it works with Python 3.11-3.13 event loop internals
2. Ensuring it interacts correctly with the LoopWatchdog (which uses `time.monotonic()` from a daemon thread — outside the event loop's clock)
3. Updating all duration/throttle/debounce tests to use the controlled clock
4. Ensuring `_dispatch_idle_event` semantics are preserved (the stability sleep uses `asyncio.sleep(0.005)`)

**Recommendation**: Defer controlled clock adoption to issue #661. The immediate fixes are simpler and lower-risk.

## Approach Options

### Option A: Per-test targeted fixes (event-gating + wider margins)

**How it works**: Fix each test individually using the most appropriate technique:
- Replace `asyncio.sleep(margin)` with event-based waits where observable signals exist
- Widen real-time margins where no signal exists
- Add observable signals (callbacks/events) to `DurationTimer` for cancel/fire lifecycle

**Pros**:
- Smallest change per test — easy to review
- No new dependencies
- No production code changes (except optional DurationTimer lifecycle events)
- Each fix can be verified independently

**Cons**:
- Does not prevent future timing-fragile tests from being written
- Some tests still use real wall-clock time (just with wider margins)
- Does not address the root cause (real-time dependence in tests)

**Effort estimate**: Small-Medium. Most fixes are one-line margin changes or adding an `asyncio.Event` wait.

**Dependencies**: None

### Option B: Injectable clock for RateLimiter and DurationTimer

**How it works**: Add an optional `clock` parameter to `RateLimiter` (for `time.monotonic()`) and `DurationTimer` (for `asyncio.sleep`). In tests, inject a controllable clock that can be advanced instantly. Production code uses the default real clock.

**Pros**:
- Makes duration/throttle/debounce tests fully deterministic
- Small production code change (one extra constructor parameter with a default)
- Follows the existing pattern (TimeControlMixin already injects a clock into `date_utils.now`)
- Sets up infrastructure for issue #661's autojump clock

**Cons**:
- Requires modifying `RateLimiter`, `DurationTimer`, and their constructors through `BusService`
- The clock injection only covers these two components — `asyncio.sleep` in other paths remains real
- DurationTimer's `asyncio.sleep` is not trivially replaceable with a clock callback — the task needs to actually yield and resume

**Effort estimate**: Medium. The `time.monotonic()` injection in RateLimiter is straightforward. The `asyncio.sleep` replacement in DurationTimer is harder — it requires either a custom awaitable or a `call_later`-based approach.

**Dependencies**: None (production code change)

### Option C: Hybrid (Option A now, Option B for DurationTimer)

**How it works**: Apply targeted fixes (Option A) for subsystems 1, 3, 5, and 6. For subsystem 2 (throttle) and 4 (duration), inject a controllable clock into RateLimiter's throttle check (small, clean change) and increase DURATION + margins for DurationTimer tests (avoiding the larger asyncio.sleep replacement).

**Pros**:
- Gets the immediate CI reliability fix shipped quickly
- Makes the throttle test fully deterministic (the cleanest win)
- Defers the harder DurationTimer clock injection to issue #661
- Each change is independently reviewable and revertable

**Cons**:
- Duration tests still use real time (just with wider margins)
- Two-phase approach means duration tests may still flake under extreme CI load

**Effort estimate**: Small-Medium

**Dependencies**: None

## Recommended Strategy

**Option C (Hybrid)** is the recommended approach. It provides immediate CI relief with minimal risk, makes the cleanest available win (throttle clock injection), and defers the harder problems to their proper scope (issue #661 for autojump clock, issue #1503 for the broader timeout audit).

### Specific recommendations per subsystem:

| Subsystem | Fix | Deterministic? | Effort |
|-----------|-----|---------------|--------|
| 1. Entity-Time | Verify if actually flaky; add `wait_for(job.schedule_status == SCHEDULED)` if needed | Yes (event-gated) | Small |
| 2. Throttle | Inject `clock` parameter into `RateLimiter.__init__` for `time.monotonic()` | Yes (controlled clock) | Small |
| 3. StateProxy | Capture CI failure message; increase timeout if needed | Partially (wider margin) | Small |
| 4. Duration | Increase `DURATION` from 0.05 to 0.2; widen margins proportionally | No (wider margin) | Small |
| 5. Shutdown-wave | Increase timeout from 0.05 to 0.5 seconds | No (wider margin) | Trivial |
| 6. Watchdog/coverage | Split to separate issue; increase lag threshold | No (wider margin) | Small |

## Prerequisites and Ordering

1. **First**: Verify which tests actually flake — run the affected tests 50-100 times under load (`pytest --count=50 -x`) to confirm failure rates. Some of these may be theoretical rather than observed.
2. **Second**: Apply trivial margin fixes (subsystems 4, 5) — these are one-line changes with immediate CI benefit.
3. **Third**: Inject clock into RateLimiter (subsystem 2) — small production code change, makes throttle test deterministic.
4. **Fourth**: Investigate StateProxy readiness (subsystem 3) — needs CI failure data to diagnose.
5. **Separate issue**: Coverage/watchdog (subsystem 6) — different mechanism, different fix.

Subsystems 2-5 can be parallelized after step 1.

## Open Questions

- [ ] Which of these tests actually flake in CI? The investigation request names 5 subsystems but does not specify which have observed failures versus which are theoretically fragile. Running a flake-detection pass would narrow the scope.
- [ ] Is the `test_simulate_state_change_none_new_value` failure actually a StateProxy readiness issue, or something else? The test itself looks straightforward — need the actual CI failure message.
- [ ] Should the RateLimiter clock injection also cover the debounce path (`asyncio.sleep`)? The debounce tests use `wait_for` on an observable signal and appear less fragile than the throttle test.
- [ ] Does issue #1503's audit overlap with any of these specific tests? If so, the fixes should be coordinated to avoid duplicate work.
- [ ] Is `DURATION = 0.2` sufficient for CI, or should it be higher? Depends on the CI environment's scheduling characteristics.

## Sources

- [aiofastforward — asyncio clock patching library](https://github.com/michalc/aiofastforward)
- [time-machine — Python time mocking library (Adam Johnson)](https://pypi.org/project/time-machine/)
- [asynciotimemachine — asyncio event loop time patching](https://pypi.org/project/asynciotimemachine/)
- [timeless-loop — custom asyncio event loop with time control](https://pypi.org/project/timeless-loop/0.1.2/)
