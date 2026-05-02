---
topic: "internal test infrastructure for async event-driven frameworks"
date: 2026-05-02
status: Draft
---

# Prior Art: Internal Test Infrastructure for Async Event-Driven Frameworks

## The Problem

Testing an async event-driven framework has unique challenges that standard unit testing patterns don't address: time-dependent behavior (schedulers, debounce, timeouts), non-deterministic task ordering, lifecycle dependencies between services, and the need to inject synthetic events that trigger handler chains of arbitrary depth. Framework authors need deterministic tests that run in milliseconds, not real-time seconds — but the framework's core value proposition IS its real-time behavior.

## How We Do It Today

Hassette uses a three-tier testing model:

1. **AppTestHarness** (end-user tier) — async context manager providing app, bus, scheduler, api_recorder, states with automatic lifecycle management
2. **HassetteHarness** (internal tier) — fluent builder (`.with_bus()`, `.with_scheduler()`) with dependency graph auto-resolution and module-scoped reuse via `reset()`
3. **create_hassette_stub()** (web tier) — MagicMock stub for HTTP/API tests without real event delivery

**Time control**: `TimeControlMixin` patches `date_utils.now()` with a `_TestClock` object. `advance_time()` mutates the frozen clock. `trigger_due_jobs()` manually fires scheduled jobs. Process-global `threading.Lock` prevents concurrent clock corruption.

**Event simulation**: Factory functions (`create_state_change_event`, `create_call_service_event`) build realistic HA events that match real schema.

**Drain mechanism**: `_drain_task_bucket(timeout=2.0)` iterates until quiescence — waiting for both bus dispatch idle AND task bucket pending to settle. Exception recorder catches failures during drain.

## Patterns Found

### Pattern 1: Virtual Clock with Autojump

**Used by**: Trio (MockClock + autojump_clock), Temporal (time-skipping test server), AnyIO (via Trio backend)

**How it works**: A virtual clock replaces the real clock at the event loop level. When all tasks are blocked (nothing runnable), the clock automatically advances to the next scheduled wakeup time. Tests that involve hour-long delays complete in microseconds because time jumps happen instantly during idle periods.

Trio's `MockClock(autojump_threshold=0)` integrates directly with `wait_all_tasks_blocked` — time only advances when the scheduler confirms nothing can proceed. Temporal provides a dedicated test server binary with time-skipping built into the workflow execution model.

The key insight: time control belongs in the event loop scheduler, not layered on top as a separate mechanism. Trio explicitly refactored from an "autojump task" to direct loop integration after discovering ordering issues.

**Strengths**: Tests run in microseconds regardless of real delays. Deterministic — no timing-dependent flakiness. Handles arbitrary nesting of timers/sleeps. Catches bugs where code depends on wall-clock ordering.

**Weaknesses**: Requires framework integration with the event loop (can't bolt onto vanilla asyncio easily). Autojump semantics can mask real-time ordering bugs. Some patterns (polling loops with `asyncio.sleep(0)`) don't block long enough to trigger autojump.

**Example**: https://trio.readthedocs.io/en/stable/reference-testing.html

### Pattern 2: Framework Instance Fixture (Full Harness)

**Used by**: Home Assistant (`hass` fixture), FastAPI (TestClient), Starlette (TestClient)

**How it works**: A fixture creates a real framework instance wired to test doubles (mock integrations, in-memory storage, stub external services). Tests interact through the framework's public API, catching integration bugs that mocked tests miss. HA's `async_test_home_assistant()` creates a fully functional Home Assistant instance with stubbed I/O.

HA's conftest is ~2000 lines providing fixtures for: event loop, hass instance, mock config entries, recorder (telemetry DB), mock integrations, and cross-cutting concerns. Tests fire events via `hass.bus.async_fire()` and assert state changes via `hass.states.get()`.

**Strengths**: High confidence — tests exercise real code paths. Catches integration issues early. Tests resemble real usage. Framework-level fixtures are reusable across thousands of tests.

**Weaknesses**: Expensive per-test (creation overhead). Requires careful cleanup/reset between tests. Massive fixture infrastructure to maintain. Slow tests encourage over-mocking.

**Example**: https://developers.home-assistant.io/docs/development_testing/

### Pattern 3: Event Replay and Deterministic Execution

**Used by**: Temporal (workflow replay testing), FoundationDB (simulation testing), DBOS

**How it works**: Record event history from a real or simulated execution, then replay to verify the system makes the same decisions. Temporal's replay-based testing detects non-determinism: if a workflow produces different commands on replay than the recorded history shows, the test fails.

FoundationDB takes this further with full deterministic simulation — replace the entire runtime (network, disk, clock) with a seeded simulator that can reproduce any execution path. TigerBeetle and Madsim follow similar approaches.

**Strengths**: Catches non-determinism bugs (the hardest category in async systems). Enables regression testing against recorded production events. Full simulation finds bugs that targeted tests miss.

**Weaknesses**: Requires a replay-compatible architecture (deterministic decision-making given the same inputs). Full simulation is extremely high investment. Replay tests can be brittle if the system's behavior legitimately changes.

**Example**: https://docs.temporal.io/develop/python/testing-suite

### Pattern 4: Async Gate/Barrier Pattern

**Used by**: General async testing best practice, hassette's own test patterns

**How it works**: Use `asyncio.Event` as a gate to control execution ordering in tests. Block a service until a test signals readiness, then release and assert the expected behavior. This replaces real timing with explicit synchronization points.

```python
gate = asyncio.Event()
mock_service.wait_for_ready = AsyncMock(side_effect=lambda _: gate.wait())
task = asyncio.create_task(executor.register_listener(...))
await asyncio.sleep(0)  # let task reach the gate
assert not task.done()  # confirms blocking
gate.set()  # release
await task  # verify completion
```

**Strengths**: Deterministic ordering without real delays. Tests express intent ("verify it blocks here"). No timing-dependent flakiness. Works with vanilla asyncio.

**Weaknesses**: Requires understanding internal control flow to place gates correctly. Tests become coupled to implementation details. Can't test true concurrency behavior (serializes everything).

**Example**: [no source found — common pattern in async test suites]

### Pattern 5: Synthetic Event Injection

**Used by**: Home Assistant (bus.async_fire), Kafka test producers, hassette (simulate_state_change)

**How it works**: Inject events directly into the event bus without external I/O. Events are constructed via factory functions that produce schema-valid payloads matching real system events. Tests compose `set_state()` (seed initial state) + `inject_event()` (trigger handler) + `drain()` (wait for completion) + `assert()`.

HA provides `async_fire_time_changed` to simulate time progression through the event bus, triggering time-based automations without real delays.

**Strengths**: Fast (no I/O). Deterministic (exact event content). Tests handler logic in isolation from event sources. Factory functions document event schemas implicitly.

**Weaknesses**: Synthetic events may drift from real event format. No coverage of event parsing/deserialization. Tests may pass with events that the real system would never produce.

**Example**: https://developers.home-assistant.io/docs/development_testing/

### Pattern 6: Backend-Agnostic Test Runner

**Used by**: AnyIO (parametrizes across asyncio/trio), pytest-anyio

**How it works**: Tests are parametrized to run against multiple async backends (asyncio, trio, uvloop). The test runner swaps the event loop implementation, catching backend-specific bugs. AnyIO's `@pytest.fixture(params=['asyncio', 'trio'])` runs each test twice.

**Strengths**: Catches backend-specific behavior differences. Ensures framework portability. Single test covers multiple runtimes.

**Weaknesses**: Doubles test execution time. Backend differences may be intentional. Requires backend-agnostic test code (no raw asyncio/trio primitives in tests).

**Example**: https://anyio.readthedocs.io/en/stable/testing.html

## Anti-Patterns

- **Real-time sleeps in tests**: Using `await asyncio.sleep(0.5)` to "wait for handlers to finish" creates flaky tests and slow suites. Use explicit drain/quiescence mechanisms instead.

- **Testing implementation details via mock assertions**: Asserting that an internal method was called N times couples tests to implementation. Test observable behavior (state changes, API responses, emitted events).

- **Module-scoped fixtures without reset**: Reusing a framework instance across tests without proper reset leads to test pollution. HA's approach of a fresh instance per test is expensive but safe; hassette's `reset()` pattern is the middle ground.

- **Time control as a separate task**: Trio explicitly learned that running the autojump clock as a concurrent task creates ordering issues with shutdown and chaos schedulers. Time control must integrate with the event loop scheduler directly.

## Emerging Trends

- **Full Deterministic Simulation**: FoundationDB, TigerBeetle, and Madsim prove that seeded simulation testing finds bugs that no amount of unit/integration testing catches. The investment is enormous but the confidence is unmatched. Python frameworks are beginning to explore this via custom event loop implementations.

- **Test Infrastructure as a First-Class Product**: pytest-homeassistant-custom-component extracts HA's internal test fixtures into a reusable package updated daily. This validates that well-designed test infrastructure becomes an ecosystem enabler — external developers test their plugins with the same tools the framework uses.

- **Time-Skipping Test Environments**: Temporal's approach (a dedicated test server with time-skipping) shows the trend toward purpose-built test runtimes rather than mocking individual time functions. The runtime handles all timing semantics consistently.

## Relevance to Us

Hassette's testing infrastructure is already more sophisticated than most comparable projects. The three-tier model (AppTestHarness, HassetteHarness, create_hassette_stub) maps well to industry patterns. Comparing:

**What we do well:**
- Three tiers for different test granularity (matches HA's graduated approach)
- Drain mechanism with quiescence detection (solves the "wait for handlers" problem)
- Synthetic event factories matching real HA schema
- Module-scoped reuse with reset (efficient without pollution)
- Exception recorder during drain (no silent handler failures)
- Time freezing with explicit advance (basic but functional)

**Gaps compared to best practice:**

1. **No autojump clock** — our `TimeControlMixin` requires explicit `advance_time()` + `trigger_due_jobs()` calls. Trio/Temporal's autojump makes scheduler tests far simpler: just `await result` and time advances automatically to when the job fires. This is the single biggest opportunity.

2. **Time control is per-function patch, not event-loop level** — we patch `date_utils.now()` which means only code using that function is time-controlled. `asyncio.sleep()`, `asyncio.wait_for(timeout=...)`, and any third-party code using `time.time()` still use real time. Trio's approach controls time at the scheduler level, affecting all timing.

3. ~~No test infrastructure published for end users~~ — **already addressed**. `test_utils/__all__` exports 13 Tier 1 APIs (AppTestHarness, RecordingApi, event factories, etc.) explicitly designed and documented for end-user consumption. A dedicated design spec (025-end-user-test-utils) was implemented.

4. **No replay/determinism testing** — no mechanism to record a sequence of events and replay them to verify consistent behavior. Lower priority for hassette (handlers are typically pure reactions, not stateful workflows), but would catch non-determinism in ordering-sensitive code.

## Recommendation

The testing infrastructure is strong. The most impactful improvement:

1. **Autojump clock integration** — replace or augment `TimeControlMixin` with a mechanism that auto-advances time when the event loop is idle. This would eliminate `advance_time()` + `trigger_due_jobs()` boilerplate and make scheduler tests express intent rather than mechanics. Investigation: can we hook asyncio's event loop clock (`loop.time()`) with a custom implementation that auto-advances?

2. ~~Expose test_utils as a stable package~~ — **already done**. Tier 1 APIs are exported, documented, and explicitly designed for end-user consumption. Future work: ensure independently installable (e.g., `hassette[test]` extra) if not already.

3. **Add event recording/replay** (lower priority) — record the event sequence during integration tests for regression detection. If a handler produces different results from the same event sequence, the test fails.

## Sources

### Reference implementations
- https://docs.temporal.io/develop/python/testing-suite — Temporal time-skipping test environment
- https://trio.readthedocs.io/en/stable/reference-testing.html — Trio MockClock with autojump
- https://developers.home-assistant.io/docs/development_testing/ — HA test infrastructure
- https://github.com/home-assistant/core/blob/dev/tests/conftest.py — HA conftest (2000+ lines)
- https://github.com/MatthewFlamm/pytest-homeassistant-custom-component — HA test plugin as package
- https://anyio.readthedocs.io/en/stable/testing.html — AnyIO testing docs

### Design discussions
- https://github.com/python-trio/trio/issues/1587 — Trio autojump refactor rationale
- https://python.temporal.io/temporalio.testing.WorkflowEnvironment.html — Temporal test environment API
