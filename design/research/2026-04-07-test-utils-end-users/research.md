---
proposal: "Identify gaps in hassette's testing utilities for end-user app development"
date: 2026-04-07
status: Draft
flexibility: Exploring
motivation: "The hassette framework ships test_utils but they're explicitly marked as internal. End users (e.g. hassette-examples) have zero tests, possibly because hassette doesn't provide usable, documented testing tools for app authors."
constraints: "Research only. No code changes."
non-goals: "Redesigning hassette's internal test infrastructure"
depth: normal
---

# Research Brief: Testing Utilities for End Users

**Initiated by**: Investigation of what testing patterns end users need to test their hassette apps, and where the framework falls short.

## Context

### What prompted this

Hassette is a framework. Its value proposition includes type safety and structured patterns for Home Assistant automations. But framework users currently have no supported path for testing their apps. The `hassette-examples` repo -- the canonical consumer -- has **zero test files**. The `test_utils` module's docstring explicitly says "not meant to be used by external users."

### Current state of hassette's test infrastructure

Hassette ships a `test_utils` package at `src/hassette/test_utils/` with 7 modules:

| Module | Purpose | End-user relevance |
|--------|---------|-------------------|
| `harness.py` | `HassetteHarness` -- fluent builder that wires real Bus, Scheduler, StateProxy, API mock | **High** -- this is the core integration test tool |
| `helpers.py` | Event factories (`create_state_change_event`, `make_state_dict`, etc.) | **High** -- essential for simulating HA events |
| `fixtures.py` | Pytest fixtures (`hassette_with_bus`, `hassette_with_scheduler`, etc.) | **Medium** -- useful patterns but tightly coupled to internal config |
| `web_mocks.py` | `create_hassette_stub()`, `create_test_fastapi_app()` | **Low** -- for testing hassette's own web UI, not user apps |
| `web_helpers.py` | Manifest/snapshot/job factories for web tests | **Low** -- internal web UI testing only |
| `reset.py` | `reset_state_proxy()`, `reset_bus()`, `reset_scheduler()` | **Medium** -- needed for module-scoped fixture reuse |
| `test_server.py` | `SimpleTestServer` -- mock HTTP server for HA REST API | **Medium** -- useful for testing `api.call_service()` etc. |

The `__init__.py` exports everything (48 symbols), making no distinction between internal and end-user APIs.

### What end users actually need to test

Analyzing the 5 example apps reveals these testing surfaces:

| App | Testing surfaces | Framework features used |
|-----|-----------------|------------------------|
| **MotionLights** | State change handlers, API service calls (turn_on/off), entity access, debounce | `bus.on_state_change`, `api.get_entity`, `api.turn_off`, `states.binary_sensor.get` |
| **ClimateController** | Glob pattern matching, conditions (Increased/Decreased/Present), attribute change handlers, scheduler periodic tasks, dependency injection (D.StateNew/StateOld/EntityId), accessor annotations | `bus.on_state_change` with globs, `C.Increased()`, `bus.on_attribute_change`, `scheduler.run_every`, `D.*`, `A.get_attr_new` |
| **PresenceTracker** | Dynamic subscription/cancellation, custom sensor creation, D.MaybeStateOld vs D.StateOld, once= listeners | `bus.on_state_change`, `Subscription.cancel()`, `api.set_state`, `scheduler.run_every` |
| **SecurityMonitor** | AppSync (synchronous app), `on_call_service`, throttle, domain-level state iteration | `bus.on_call_service`, `states.lock` iteration, `AppSync` |
| **CoverScheduler** | Cron scheduling, daily scheduling, run_in, run_hourly, cache persistence, on_shutdown lifecycle, once= listeners, if_exists="skip" | `scheduler.run_cron/daily/hourly/run_in`, `self.cache`, glob listeners, `on_shutdown` |

### Key constraints

- The `test_utils` package is already shipped in the built wheel (it's under `src/hassette/`), so end users *can* import it today -- they just have no guidance.
- No `[project.optional-dependencies]` for test extras -- users don't know what test deps to install.
- No documentation page for testing.

## Feasibility Analysis

### What would need to change

| Area | Scope | Effort | Risk |
|------|-------|--------|------|
| New `AppTestHarness` or simplified API | New module/class | Medium | Must not break internal test_utils |
| Event/state factory cleanup | Refactor existing helpers | Low | Backwards-compatible additions |
| Pytest plugin / fixtures for end users | New fixtures module | Medium | API surface commitment |
| Documentation | New docs section | Medium | None |
| Optional test dependency group | pyproject.toml change | Low | None |

### What already supports this

1. **`HassetteHarness`** already works as an integration test tool. The fluent builder API (`with_bus()`, `with_scheduler()`, etc.) is well-designed. An end user *could* use it today if they knew how.

2. **Event factories** (`create_state_change_event`, `make_state_dict`, `make_light_state_dict`, `make_sensor_state_dict`, `make_switch_state_dict`) are exactly what end users need. These are well-structured and general-purpose.

3. **`SimpleTestServer`** provides a clean expect/assert model for mocking the HA REST API.

4. **Reset utilities** (`reset_bus`, `reset_scheduler`, `reset_state_proxy`) solve real problems for test isolation.

### What works against this

1. **`HassetteHarness` requires internal knowledge to use.** The constructor needs a `HassetteConfig` instance, which requires TOML files, env files, and test data paths. The `tests/conftest.py` shows 50+ lines of config boilerplate. An end user can't just write `HassetteHarness()` and go.

2. **No way to get an App instance wired into the harness.** The harness creates a mock `Hassette` with Bus/Scheduler/StateProxy, but there's no `with_app(MyApp)` method. End users need their *actual app* wired up with real Bus/Scheduler/StateProxy to test handler registration and event flow. The internal `with_app_handler()` loads apps from TOML config files and the filesystem -- it doesn't accept app classes directly.

3. **Fixtures assume hassette's own test data directory.** The fixtures in `fixtures.py` depend on `test_config`, `test_config_with_apps`, `test_events_path` -- all session-scoped fixtures defined in hassette's own `tests/conftest.py`. End users can't use these fixtures without reproducing hassette's entire test data structure.

4. **No helpers for the most common test pattern: "emit event, assert handler did X."** The harness provides raw Bus/Scheduler access, but there's no higher-level helper like:
   ```python
   await harness.emit_state_change("light.kitchen", old="off", new="on")
   await harness.wait_for_handler(my_app.on_light_change)
   ```

5. **No time control for scheduler tests.** The scheduler uses real time. Testing `run_in(60)`, `run_daily()`, or `run_cron()` requires either waiting or mocking time. Hassette provides no time-travel utility.

6. **No mock for `self.cache`.** The `cache` property creates a real `diskcache.Cache` on disk. Tests need either a temp directory or an in-memory mock.

7. **No helpers for testing dependency injection.** Apps like `ClimateController` use `D.StateNew[states.SensorState]`, `D.StateOld[states.SensorState]`, `D.EntityId`, `A.get_attr_new("current_temperature")`. Testing that these are resolved correctly requires constructing events with the right shape -- the factories help, but there's no "here's a complete event that will satisfy `D.StateNew[SensorState]`" helper.

## Gap Analysis

### Gap 1: No App-Level Test Harness (CRITICAL)

**The problem**: End users write `App` subclasses. They need to instantiate their app with real (or test-double) Bus, Scheduler, StateManager, and Api, then call `on_initialize()` and verify handler registrations work. There is no supported way to do this.

**What users would have to build themselves**: A function that creates a `HassetteConfig`, builds a `HassetteHarness`, somehow instantiates their App class and wires it into the harness's mock Hassette. This requires understanding Resource parent/child relationships, AppManifest creation, and the internal initialization lifecycle.

**What hassette should provide**: An `AppTestHarness` or `app_harness(MyApp, config={...})` that:
- Creates a minimal config without requiring TOML/env files
- Instantiates the user's App class
- Wires Bus, Scheduler, StateProxy, and a mock Api
- Runs `on_initialize()`
- Exposes `app.bus`, `app.scheduler`, `app.api`, `app.states` for assertions

### Gap 2: No Event Emission + Handler Assertion Pattern (HIGH)

**The problem**: The most common test is "when entity X changes to Y, my handler should call service Z." This requires:
1. Constructing a state change event
2. Sending it through the bus
3. Waiting for the handler to be invoked
4. Asserting the handler's side effects (API calls, state changes)

**What users would have to build**: Chain `create_state_change_event()` -> `hassette.send_event()` -> manual `asyncio.sleep()` or polling -> assert on API mock.

**What hassette should provide**: Higher-level helpers like:
```python
await harness.simulate_state_change("sensor.temperature", old="20", new="30")
# or
await harness.simulate_state_change("sensor.temperature", old="20", new="30",
                                     old_attrs={"unit": "C"}, new_attrs={"unit": "C"})
```

### Gap 3: No Time Control for Scheduler Tests (HIGH)

**The problem**: `CoverScheduler` uses `run_cron()`, `run_daily()`, `run_hourly()`, `run_in()`. Testing these with real time means either:
- Waiting actual seconds (slow, flaky)
- Mocking the scheduler entirely (loses integration value)

**What hassette should provide**: A `FakeScheduler` or time-advance helper:
```python
await harness.advance_time(seconds=60)  # triggers any run_in(60) jobs
await harness.advance_to(hour=7, minute=30)  # triggers run_daily at 7:30
```

### Gap 4: No Minimal Config Helper (MEDIUM)

**The problem**: `HassetteConfig` requires TOML files and env files. Creating a test config requires understanding `SettingsConfigDict`, `model_config`, TOML structure, and which defaults to override.

**What hassette should provide**: A `make_test_config()` factory or a `TestConfig` base class:
```python
from hassette.test_utils import make_test_config

config = make_test_config(
    app_config={"motion_entity": "binary_sensor.test", "light_entity": "light.test"}
)
```

### Gap 5: No State Seeding Helper (MEDIUM)

**The problem**: Apps read state via `self.states.light.get("light.kitchen")`. To test this, users need to seed the state proxy with initial state data. The current approach requires understanding `StateProxy` internals and state dict format.

**What hassette should provide**:
```python
harness.set_state("light.kitchen", "on", brightness=255)
harness.set_state("sensor.temperature", "25.5", unit_of_measurement="C")
```

### Gap 6: No Mock API with Assertion Helpers (MEDIUM)

**The problem**: Apps call `self.api.turn_on()`, `self.api.call_service()`, `self.api.set_state()`. Testing these requires either the `SimpleTestServer` (which needs TCP port setup and HTTP-level expectations) or an `AsyncMock` (which loses type safety).

**What hassette should provide**: A recording mock that captures API calls for assertion:
```python
assert harness.api.calls == [
    Call("turn_on", entity_id="light.kitchen", brightness=255),
]
# or
harness.api.assert_called_with("turn_on", entity_id="light.kitchen")
```

### Gap 7: No Pytest Plugin / Fixture Package (MEDIUM)

**The problem**: Hassette's fixtures assume internal test structure. End users need plug-and-play fixtures.

**What hassette should provide**: A pytest plugin (registered via `entry_points`) or documented `conftest.py` patterns:
```python
# user's conftest.py
pytest_plugins = ["hassette.test_utils.plugin"]

# or
from hassette.test_utils import app_harness

@pytest.fixture
async def my_app():
    async with app_harness(MotionLights, config={"motion_entity": "binary_sensor.test"}) as harness:
        yield harness
```

### Gap 8: No Documentation (MEDIUM)

**The problem**: No docs page exists for testing. The only guidance is `tests/TESTING.md`, which is an internal reference.

### Gap 9: No Test Dependency Group (LOW)

**The problem**: Users don't know what test dependencies to install. Hassette's test deps (`pytest-asyncio`, `httpx`, etc.) are in `[dependency-groups.test]` which is a dev-only group.

**What hassette should provide**: An optional dependency:
```toml
[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=1.0"]
```

## Patterns End Users Cannot Test Today

Based on the example apps, these app behaviors have no feasible test path:

| Behavior | Example | Why untestable |
|----------|---------|---------------|
| Handler fires on state change | MotionLights `on_motion_detected` | No way to wire app + emit event + assert API call |
| Debounce suppresses rapid events | MotionLights `on_motion_cleared` (60s debounce) | No time control |
| Glob patterns match correctly | ClimateController `sensor.*temperature*` | No way to verify which entities trigger the handler |
| Conditions filter events | ClimateController `C.Increased()` | Would need to emit events and verify filtering |
| Attribute change handlers fire | ClimateController `on_hvac_temp_change` | No attribute change event helpers |
| Dynamic subscription/cancellation | PresenceTracker `_subscribe_to_zone` / `cancel()` | Can't verify subscription lifecycle |
| Scheduler jobs fire | CoverScheduler `run_cron`, `run_daily` | No time control |
| Cache persistence | CoverScheduler `on_shutdown` saves to cache | No cache mock/helper |
| AppSync handlers | SecurityMonitor sync handlers | No AppSync test support |
| `on_call_service` handlers | SecurityMonitor lock monitoring | No call_service event emission helper (exists in helpers.py but no integration path) |
| DI parameter resolution | ClimateController `D.StateNew[SensorState]` | No helper to verify DI works with user types |

## Open Questions

- [ ] Should hassette commit to a public test_utils API (semver stability), or keep it as "supported but not guaranteed stable"?
- [ ] Should the harness support loading actual app TOML configs for integration-level tests, or should config always be passed programmatically?
- [ ] Is time control feasible? The scheduler is custom (built on `croniter` + `asyncio`, not apscheduler), so injecting a test clock may be straightforward.
- [ ] Should `test_utils` be a separate package (`hassette-test-utils`) or stay as a subpackage?
- [ ] What test deps should be in the optional group? Just `pytest` + `pytest-asyncio`, or also `httpx` for API testing?

## Recommendation

The single most impactful change is **an `AppTestHarness` (or similar) that lets users write `async with app_test(MotionLights, config={...}) as harness:`** and get a fully wired app with testable Bus, Scheduler, API, and StateManager. Everything else is secondary.

The hassette-examples repo having zero tests is a strong signal. When your own demo apps aren't tested, end users won't test theirs either. Adding tests to hassette-examples -- using hassette's own test_utils -- is both the best validation of the API and the best documentation.

### Suggested next steps

1. **Write a design doc via /mine.design** for the end-user test API, focusing on `AppTestHarness` and event simulation helpers
2. **Add tests to hassette-examples** as a design validation exercise -- attempt to test each example app and let the friction reveal the exact API gaps
3. **Create a `docs/pages/core-concepts/testing.md`** guide once the API is settled
4. **Add `[project.optional-dependencies] test = [...]`** to pyproject.toml

### Priority ordering

1. `AppTestHarness` / `app_test()` context manager (Gap 1) -- **unlocks everything else**
2. State seeding + event simulation helpers (Gaps 2, 5) -- **most common test pattern**
3. Mock API with recording/assertion (Gap 6) -- **second most common pattern**
4. Time control for scheduler (Gap 3) -- **enables scheduler testing**
5. Minimal config helper (Gap 4) -- **reduces boilerplate**
6. Documentation (Gap 8) -- **useless without the above**
7. Pytest plugin (Gap 7) -- **polish**
8. Test dependency group (Gap 9) -- **trivial**
