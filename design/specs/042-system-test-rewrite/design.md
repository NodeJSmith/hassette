# Design: System Test Suite Rewrite

**Date:** 2026-04-26
**Status:** approved

## Problem

The system test suite was written as a one-off during telemetry work and never revisited. It has three problems:

1. **Flaky** — tests use caplog assertions that break on message rewording, hand-rolled polling loops instead of the shared `wait_for` utility, and accumulate HA container state across tests without resets.
2. **Too few** — 15 tests across 3 files, all concentrated on telemetry/DB internals. Core user-facing subsystems (bus event filtering, scheduler, app lifecycle, state proxy, web API, reconnection) have zero system-level coverage.
3. **Low signal** — many tests assert the same startup path from slightly different angles (session in DB, session status running, drop counters zero, health check succeeds, SELECT 1 works). The marginal value of each is near zero.

The practical cost is twofold: flaky failures erode trust in the suite (so it gets ignored rather than investigated), and real bugs have shipped that system tests should have caught — particularly in subsystems like the scheduler, app lifecycle, and reconnection that have zero system-level coverage.

System tests exist to prove things that unit and integration tests cannot: that real HA event delivery works end-to-end, that timing-sensitive scheduling actually fires, that apps loaded from disk get working resources, and that the framework recovers from connection drops. The current suite proves almost none of this.

## Goals

- Every major user-facing subsystem has at least one system test exercising it against a real HA instance
- The nox `system` session passes reliably in CI with no flaky failures
- Tests are organized by user-visible scenario, not by internal service
- All polling uses the shared `wait_for` utility — no hand-rolled deadline loops
- No caplog-based assertions — all tests verify observable behavior

## Non-Goals

- FileWatcher / hot reload tests — filesystem timing is inherently flaky in CI; better served by integration tests with mocked watchfiles
- Cron scheduling tests — too slow (must wait for minute boundary); unit tests with frozen time are sufficient
- WebUiWatcherService tests — internal service with no user-facing behavior worth system-testing
- SessionManager internals (orphan marking, stale listener cleanup) — DB operations that are fully unit-testable
- Numeric coverage targets — subsystem coverage is the goal, not a percentage

## User Scenarios

### Framework developer: Maintainer

- **Goal:** Verify that a change to a core subsystem doesn't break real HA integration
- **Context:** After modifying bus, scheduler, API, state proxy, or web API code

#### Run system tests before merge

1. **Run `uv run nox -s system`**
   - Sees: Docker container starts, tests run, pass/fail results
   - Decides: Whether the change is safe to merge
   - Then: CI also runs the system session as a required check

#### Debug a failing system test

1. **See a failure in CI or local run**
   - Sees: Test name, assertion error, and `--tb=short` traceback
   - Decides: Whether the failure is a real regression or a flaky test
   - Then: Re-runs locally with `-v -x` to reproduce; reads the test as documentation to understand what the test proves and why it might break

### Framework user: App author

- **Goal:** Trust that the framework's public API works correctly against a real HA instance
- **Context:** Evaluating hassette or debugging an app that works in tests but fails against real HA

#### Review system test suite as living documentation

1. **Read test files organized by subsystem**
   - Sees: Clear examples of bus registration, scheduler usage, app lifecycle, state access
   - Decides: How the API is intended to be used
   - Then: Uses patterns from tests as reference for their own apps

## Functional Requirements

1. Delete the three existing test files (`test_startup.py`, `test_shutdown.py`, `test_telemetry_lifecycle.py`) and replace them with new files organized by scenario
2. Retain the existing test infrastructure: `conftest.py`, `docker-compose.yml`, HA fixture config, `generate_ha_fixtures.py`
3. Extend `conftest.py` with shared helpers: a toggle-and-capture helper and a web-API-enabled config factory
4. Provide committed app fixture files for common patterns (trivial app, app with config, app with bus handler) under `tests/system/apps/`
5. Use inline app strings written to `tmp_path` only for test-specific edge cases
6. All polling assertions must use the existing `wait_for(predicate, timeout, desc)` utility — no hand-rolled deadline loops
7. No caplog-based assertions anywhere in the suite — verify observable behavior instead
8. Every test file must apply the `pytest.mark.system` marker
9. Tests must be independent of execution order — no test may depend on state left by a previous test
10. The reconnection test must use `docker pause`/`docker unpause` to simulate a real connection drop, not mock the WebSocket

## Edge Cases

1. **HA demo entity state accumulates across tests** — toggling a light in one test leaves it in the toggled state for the next. Tests must either be robust to either initial state or reset entities before asserting.
2. **Port conflicts for web API tests** — tests enabling the web API must use a non-default port to avoid conflicts with any local hassette instance.
3. **Reconnection timing** — after unpausing the HA container, the WebSocket may take several seconds to reconnect. Polling must have sufficient timeout.
4. **App import errors** — test apps written to disk could have syntax errors if string templating goes wrong. Tests should verify the app actually loaded, not just that hassette started.
5. **Scheduler timing jitter** — `run_in(1.0)` may fire at 1.0s or 1.2s depending on event loop load. Assertions must use `wait_for` with generous timeouts, not exact timing checks.
6. **Multiple events from a single toggle** — HA may emit multiple state_changed events for a single `light.toggle` (e.g., brightness + on/off). Tests asserting event counts must use `>=` not `==`.
7. **Container startup race** — the `ha_container` fixture already handles this with a 60s timeout, but tests should not assume HA is fully populated with demo entities immediately after the API returns 200.

## Acceptance Criteria

1. The `uv run nox -s system` session passes on a clean machine with Docker available
2. Each of the following subsystems has at least one passing test: startup, shutdown, bus events, scheduler, app lifecycle, HA API, state proxy, web API, reconnection
3. Running the suite 5 times consecutively produces 5 green runs (no flaky failures)
4. No test uses `caplog`, `capfd`, or asserts on log output
5. No test contains a hand-rolled `while loop.time() < deadline` polling pattern
6. The CI `system` job continues to collect coverage and report to Codecov
7. Test files are readable as living documentation of how each subsystem works

## Dependencies and Assumptions

- Docker must be available in the test environment (CI and local)
- The HA demo integration provides known entities (`light.kitchen_lights`, `binary_sensor.movement_backyard`, `weather.demo_weather_*`, etc.)
- The existing `ha_container` session-scoped fixture handles container lifecycle
- `wait_for` from `hassette.test_utils` is stable and suitable for system test polling
- The `docker pause`/`docker unpause` commands work in GitHub Actions runners

## Architecture

### Organization rationale

Tests are organized by **user-visible subsystem** (bus, scheduler, app lifecycle, etc.) rather than by internal service (BusService, SchedulerService, CommandExecutor). This means a developer modifying the scheduler knows exactly which file to check — `test_scheduler.py` — without understanding the internal service decomposition. It also makes the test suite readable as living documentation: each file demonstrates how one subsystem works from the outside.

The startup/shutdown files are kept separate rather than merged into subsystem files because they test framework-wide behavior that doesn't belong to any single subsystem.

**Trade-off:** This organization optimizes for discoverability and readability at the cost of some cross-cutting coverage. A test that exercises bus + scheduler + app lifecycle together (e.g., "app registers a bus handler that schedules a job") doesn't have an obvious home. The recommendation is to place such tests in the file of the primary subsystem being proven and cross-reference in a comment.

### File structure

```
tests/system/
├── conftest.py                    # Existing + new helpers
├── docker-compose.yml             # Existing (unchanged)
├── generate_ha_fixtures.py        # Existing (unchanged)
├── __init__.py                    # Existing (unchanged)
├── apps/                          # NEW — committed app fixtures
│   ├── __init__.py
│   ├── trivial_app.py             # Minimal App subclass
│   ├── config_app.py              # App[CustomConfig] with env-based settings
│   └── bus_handler_app.py         # App that registers a state_change handler
├── test_startup.py                # NEW — 3 tests (replaces old)
├── test_shutdown.py               # NEW — 2 tests (replaces old)
├── test_bus.py                    # NEW — 8 tests
├── test_scheduler.py              # NEW — 6 tests
├── test_app_lifecycle.py          # NEW — 7 tests
├── test_api.py                    # NEW — 6 tests
├── test_state_proxy.py            # NEW — 4 tests
├── test_web_api.py                # NEW — 5 tests
└── test_reconnection.py           # NEW — 2 tests
```

### Conftest changes

Add to `conftest.py`:

**`toggle_and_capture` helper** — encapsulates the "register handler → toggle entity → wait for event" pattern used across ~10 tests. Returns the captured events list. Accepts the entity_id, the bus instance, and an optional service domain/action.

**`make_web_system_config` factory** — like `make_system_config` but with `run_web_api=True` and a per-test dynamic port (use a fixture that finds an available port). Returns both the config and the base URL for HTTP requests.

**`system_app_dir` fixture** — returns the path to `tests/system/apps/` for tests that need committed app fixtures.

### Test plan by file

**`test_startup.py`** (3 tests):
- `test_startup_completes` — Hassette reaches running state with positive session_id
- `test_demo_entities_visible` — `api.get_states()` returns known demo entities
- `test_session_persisted_as_running` — sessions table has a row with status='running'

**`test_shutdown.py`** (2 tests):
- `test_clean_shutdown` — after `startup_context` exits, all children are STOPPED, `_shutdown_completed` is True, `event_streams_closed` is True, session finalized as 'success' in DB
- `test_failed_service_cascade_triggers_shutdown` — inject an always-failing service, fire FAILED event, verify shutdown_event is set after max retries

**`test_bus.py`** (8 tests):
- `test_state_change_handler_fires` — register handler for `light.kitchen_lights`, toggle, verify event received
- `test_attribute_change_handler_fires` — register `on_attribute_change` for brightness, toggle, verify fires
- `test_glob_pattern_matching` — register handler for `light.*`, toggle kitchen light, verify match
- `test_changed_to_predicate` — register with `changed_to="on"`, toggle light (start off→on), verify fires; toggle back (on→off), verify does NOT fire again
- `test_debounce` — register with `debounce=1.0`, toggle 3 times rapidly, verify handler fires exactly once after debounce window
- `test_throttle` — register with `throttle=2.0`, toggle 3 times over 1s, verify handler fires at most once
- `test_once_handler` — register with `once=True`, toggle twice, verify handler fires exactly once
- `test_multiple_handlers_same_entity` — register 2 handlers for same entity, toggle, verify both fire

**`test_scheduler.py`** (6 tests):
- `test_run_in_fires_after_delay` — schedule `run_in(callback, 1)`, verify fires within 3s
- `test_run_every_fires_multiple_times` — schedule `run_every(callback, seconds=1)`, wait 3.5s, verify ≥2 firings
- `test_run_once_at_time` — schedule `run_once(callback, at=<now+2s>)`, verify fires within 5s
- `test_job_cancellation` — schedule `run_in(callback, 1)`, cancel immediately, wait 3s, verify never fires
- `test_group_cancellation` — schedule 3 jobs in group "test", cancel group, wait, verify none fire
- `test_job_execution_persisted` — schedule a job, wait for execution, verify `job_executions` table has a row with correct session_id

**`test_app_lifecycle.py`** (7 tests):
- `test_trivial_app_initializes` — configure hassette to load `trivial_app.py` from fixture dir, verify app appears in `app_handler.apps` with RUNNING status
- `test_app_gets_working_api` — app calls `self.api.get_states()` in `on_initialize`, stores result, verify non-empty after startup
- `test_app_bus_handler_fires` — load `bus_handler_app.py` which registers a state_change handler in `on_initialize`, toggle light externally, verify the app's handler captured the event
- `test_app_scheduler_fires` — app schedules `self.scheduler.run_in(callback, 1)` in `on_initialize`, verify callback fires within 3s
- `test_app_state_access` — app reads `self.states.light` in `on_initialize`, stores result, verify it contains demo entities
- `test_app_shutdown_hook` — app sets a flag in `on_shutdown`, verify flag is set after `startup_context` exits
- `test_multiple_apps_isolation` — load 2 apps, one registers handler for `light.kitchen_lights`, the other does not, toggle light, verify only the registered app captures the event

**`test_api.py`** (6 tests):
- `test_get_state_single_entity` — `api.get_state("light.kitchen_lights")`, verify returns typed state with entity_id and attributes
- `test_set_state_roundtrip` — `api.set_state("input_boolean.test", "on")`, read back, verify matches (requires adding `input_boolean` to HA config or using a sensor)
- `test_fire_event_received_by_bus` — register bus handler for custom event type, `api.fire_event("custom_test", {"key": "value"})`, verify handler receives it
- `test_render_template` — `api.render_template("{{ states('light.kitchen_lights') }}")`, verify returns "on" or "off"
- `test_get_config` — `api.get_config()`, verify returns dict with 'components', 'unit_system', etc.
- `test_get_history` — toggle light, wait briefly, `api.get_history("light.kitchen_lights", start_time=<1min ago>)`, verify at least one entry

**`test_state_proxy.py`** (4 tests):
- `test_initial_state_loaded` — after startup, `state_proxy._states` is non-empty and contains demo entities
- `test_state_change_propagates_to_proxy` — toggle light via API, `wait_for` until `state_proxy` reflects new state
- `test_state_manager_typed_access` — `states.light["kitchen_lights"]`, verify returns typed object with `.state` and `.attributes`
- `test_state_manager_domain_iteration` — `list(states.light)`, verify returns multiple entities from demo integration

**`test_web_api.py`** (5 tests — uses `make_web_system_config`):
- `test_health_endpoint` — `GET /api/health`, verify 200 with connectivity status
- `test_apps_endpoint` — `GET /api/apps`, verify 200 with app list structure
- `test_config_endpoint` — `GET /api/config`, verify 200 with hassette config
- `test_telemetry_after_activity` — toggle light, wait for DB write, `GET /api/dashboard/kpis`, verify non-zero invocation count
- `test_websocket_receives_events` — connect to `/api/ws`, receive `connected` message, toggle light, verify event arrives over WebSocket

**`test_reconnection.py`** (2 tests):
- `test_websocket_reconnects_after_ha_restart` — start hassette, `docker pause` the HA container, wait for disconnect detection, `docker unpause`, `wait_for` until WebSocket reconnects and subscriptions are active, toggle light, verify event delivery resumes
- `test_state_proxy_refreshes_after_reconnect` — toggle light while HA is paused (will fail), unpause, wait for reconnect, verify state proxy reflects current state (may have been toggled by another test — just verify it's populated and fresh)

### App fixture files

**`tests/system/apps/trivial_app.py`**:
```python
from hassette import App

class TrivialApp(App):
    async def on_initialize(self):
        pass
```

**`tests/system/apps/config_app.py`**:
```python
from pydantic_settings import SettingsConfigDict
from hassette import App
from hassette.config.classes import AppConfig

class ConfigAppConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="config_app_")
    greeting: str = "hello"

class ConfigApp(App[ConfigAppConfig]):
    async def on_initialize(self):
        self._greeting = self.app_config.greeting
```

**`tests/system/apps/bus_handler_app.py`**:
```python
from hassette import App
from hassette.events import RawStateChangeEvent

class BusHandlerApp(App):
    async def on_initialize(self):
        self.captured_events: list[RawStateChangeEvent] = []
        self.bus.on_state_change("light.kitchen_lights", handler=self._on_light_change)

    async def _on_light_change(self, event: RawStateChangeEvent) -> None:
        self.captured_events.append(event)
```

### HA fixture changes

The `set_state` test needs an entity that can be set without side effects. Two options:
1. Add `input_boolean:` to `configuration.yaml` — HA creates an `input_boolean.test` entity that can be toggled via API
2. Use `set_state` on a non-existent entity (HA allows this for REST API)

Option 1 is cleaner. Add to `tests/fixtures/ha-config/configuration.yaml`:
```yaml
input_boolean:
  test:
    name: System Test Toggle
```

### Docker compose changes

The reconnection tests need the container name to be predictable for `docker pause`/`docker unpause` commands. The current compose file already sets `container_name: hassette-system-ha`, so no changes needed.

### Nox session changes

No changes needed — the existing `system` and `system_with_coverage` sessions run `pytest -m system` which will pick up all new test files automatically.

## Alternatives Considered

**Keep existing tests and add new ones alongside** — rejected because the existing tests would remain flaky, many are redundant with each other, and their internal-focused assertions would dilute the suite's signal. Starting fresh is cleaner than patching around bad tests.

**Use testcontainers-python instead of raw docker-compose** — considered for better container lifecycle management, but the existing docker-compose setup is working well and testcontainers would add a dependency for minimal benefit. The fixture already handles startup polling and cleanup.

**Mock the WebSocket for reconnection tests instead of pausing Docker** — rejected because the whole point of system tests is proving real behavior. A mocked WebSocket reconnection is already covered by integration tests.

## Test Strategy

This design *is* the test strategy — it defines a test suite. The tests themselves are verified by:
1. Running the nox `system` session locally before merging
2. CI running `system_with_coverage` on every push
3. Flakiness validation: 5 consecutive green runs before declaring the rewrite complete

## Documentation Updates

- Update `tests/TESTING.md` to document the system test organization, how to run them, and the fixture app pattern
- Update the "System tests" section if one exists, or add one describing the subsystem-by-scenario approach

## Impact

**Files deleted:**
- `tests/system/test_startup.py`
- `tests/system/test_shutdown.py`
- `tests/system/test_telemetry_lifecycle.py`

**Files modified:**
- `tests/system/conftest.py` — add helpers and fixtures
- `tests/fixtures/ha-config/configuration.yaml` — add `input_boolean` entity
- `tests/TESTING.md` — update system test documentation

**Files created:**
- `tests/system/apps/__init__.py`
- `tests/system/apps/trivial_app.py`
- `tests/system/apps/config_app.py`
- `tests/system/apps/bus_handler_app.py`
- `tests/system/test_startup.py` (new)
- `tests/system/test_shutdown.py` (new)
- `tests/system/test_bus.py`
- `tests/system/test_scheduler.py`
- `tests/system/test_app_lifecycle.py`
- `tests/system/test_api.py`
- `tests/system/test_state_proxy.py`
- `tests/system/test_web_api.py`
- `tests/system/test_reconnection.py`

**Blast radius:** Test-only. No production code changes. No API changes. No configuration changes outside the test fixtures.

## Open Questions

None — all design decisions resolved during discovery.
