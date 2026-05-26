# Design: Decompose bus_service.py

**Date:** 2026-05-25
**Status:** approved
**Scope-mode:** hold

## Problem

The bus service module has grown past the project's file-size ceiling (946 lines vs 800 max). It mixes five distinct concerns — duration hold lifecycle, dispatch pipeline, event filtering, registration persistence, and idle tracking — in a single class.

The cost is twofold: PRs touching any single bus concern (e.g., duration hold) require reviewers to understand all five concerns because the code is interleaved, increasing review time and mis-scoping risk. Additionally, unit-testing individual behaviors (like duration hold logic) requires constructing a full BusService with mocked stream, executor, and hassette — there is no way to test a concern in isolation without bringing the entire service along.

## Goals

- Reduce `bus_service.py` to under 500 lines by extracting three focused modules
- Each extracted module owns exactly one concern and is independently testable
- Zero behavior change — existing functionality preserved
- Clean import graph with no circular dependencies

## User Scenarios

### Developer: Framework maintainer
- **Goal:** modify duration hold behavior without reading dispatch logic
- **Context:** when implementing a new timer feature or fixing a duration-related bug

#### Modify duration hold logic

1. **Open duration_hold module**
   - Sees: all duration-related code in one place (timers, immediate fire, cancel listeners)
   - Decides: what to change based on self-contained context
   - Then: edits one file, runs its focused tests

#### Modify event filtering rules

1. **Open event_filter module**
   - Sees: all skip/log decision logic, exclusion config parsing
   - Decides: what filter to add or modify
   - Then: edits one file, no risk of touching dispatch or registration logic

## Functional Requirements

- **FR#1** Duration hold lifecycle (immediate fire, full timer start, remaining timer start, cancel listener creation, hold predicate matching) operates from a dedicated module
- **FR#2** Tracked invocation function building (timeout resolution, error handler resolution, InvokeHandler construction) operates from a dedicated module
- **FR#3** Event skip and log decisions (exclusion filter setup, domain/entity exclusion, system_log filtering) operate from a dedicated module
- **FR#4** BusService retains its public API surface unchanged (add_listener, remove_listener, remove_listeners_by_owner, get_listeners_by_owner, dispatch, await_dispatch_idle, await_registrations_complete, drain_framework_registrations, serve, router, is_dispatch_idle, dispatch_pending_count, duration_timers_active)
- **FR#5** The duration hold module receives dependencies via injected parameters (not a reference to BusService) — callbacks for cross-module operations (`state_reader`, `remove_listener`), direct values for sibling-module dependencies (`executor`, `config_resolver`)
- **FR#6** Module-level helper functions (`read_current_state`, `compute_elapsed`) move to the duration hold module where they are consumed

## Edge Cases

- **Listener with no duration_config:** dispatch path must still work (non-duration path in `_dispatch` stays in BusService or is handled by the invocation module)
- **Duration listener with immediate=True but entity not in cache:** error handling stays intact after extraction
- **Event with no payload:** filter must still return False (don't skip)
- **Circular import risk:** `bus/invocation.py` imports `core/commands.py` which imports `bus/listeners.py` — verified non-circular (commands.py is a leaf)

## Acceptance Criteria

- **AC#1** `bus_service.py` is under 500 lines (maps to FR#1, FR#2, FR#3)
- **AC#2** All existing test suites pass (existing tests may need fixture/import updates to reflect new module locations, but tested behaviors remain identical) (maps to FR#4)
- **AC#3** `pyright` reports no new type errors
- **AC#4** The import graph has no runtime circular dependencies (verified by running the test suite — circular imports produce ImportError at import time)
- **AC#5** No external consumers of `BusService` need import changes (the class stays in `core/bus_service.py`, public methods unchanged) (maps to FR#4)
- **AC#6** Duration hold module is constructable with mock callbacks for unit testing (maps to FR#5)

## Key Constraints

- The non-duration dispatch path (`_dispatch` → `listener.invoker.dispatch(invoke_fn)` with `once` removal) must remain in BusService because it's the `dispatch()` fanout's natural continuation — extracting it would fragment a 4-line code path across two modules for no testability benefit
- Do not introduce a Protocol/ABC for BusService — callback injection is the coupling strategy; a protocol would be over-engineering for an internal extraction with one consumer
- Do not rename any public method or attribute on BusService — this is a structural refactor, not an API redesign

## Dependencies and Assumptions

- No external dependencies. All extracted code uses stdlib (`asyncio`, `collections`, `uuid`) and existing hassette types.
- Assumes the `DurationTimer` class (already in `bus/duration_timer.py`) remains unchanged — the new `duration_hold.py` orchestrates timers but doesn't modify `DurationTimer` internals.
- Assumes `core/commands.py` remains a leaf dataclass module (no imports back into the new modules).

## Architecture

### New module: `src/hassette/bus/duration_hold.py` (~220 lines)

Extracts the duration hold lifecycle from BusService. Contains:

- `DurationHoldManager` class — constructed with dependencies:
  - `executor: CommandExecutor` — for invoking handlers via `build_tracked_invoke_fn`
  - `config_resolver: Callable[[], float | None]` — lazy reader for `event_handler_timeout_seconds` (must remain a callable, not a captured value, to support hot-reload)
  - `state_reader: Callable[[str], HassStateDict | None]` — reads entity state from StateProxy, returns None if entity not found. StateProxy is guaranteed ready before apps run (`AppHandler.depends_on` includes `StateProxy`); the `ResourceNotReadyError` handling in the existing `read_current_state` is defense-in-depth that BusService absorbs into the callback. The manager only checks for None — no exception handling needed in duration_hold.py
  - `remove_listener: Callable[[Listener], None]` — removes a listener from the router. Verified idempotent: `listener.cancel()` is a no-op on already-cancelled listeners, and `Router.remove_listener_by_id()` returns early when the listener_id is not found (router.py:51-64)
  - `router: Router` — for synchronous route insertion of cancel listeners
  - `task_bucket: TaskBucket` — for spawning background tasks
  - `logger: logging.Logger` — for structured logging
- Methods (moved from BusService):
  - `immediate_fire_task(listener)` — was `_immediate_fire_task`
  - `start_duration_timer(listener, entity_id, duration_config, invoke_fn)` — was `start_duration_timer`
  - `start_remaining_duration_timer(listener, entity_id, duration_config, invoke_fn, remaining)` — was `start_remaining_duration_timer`
  - `create_cancel_listener(main_listener)` — was `_create_cancel_listener`
  - `hold_matches(listener, event)` — was `_hold_matches`
  - `make_synthetic_state_event(entity_id, current_state)` — was `_make_synthetic_state_event`
- Module-level functions (moved from bus_service.py bottom):
  - `compute_elapsed(current_state, duration_config)` — unchanged
- `read_current_state` does NOT move — its logic is absorbed into the `state_reader` callback that BusService provides (combining `_read_entity_state` + error handling into one callable)

The manager tracks `duration_timers_active` internally and exposes it as a property. BusService delegates `self.duration_timers_active` to the manager.

Dispatch tracking (`_dispatch_pending` / `_dispatch_idle_event`) stays in BusService. The manager does NOT call dispatch tracking callbacks — duration timer fires are explicitly excluded from `await_dispatch_idle` (see `bus_service.py:767-770`). Only `immediate_fire_task` is tracked, and its spawn + done-callback registration stays in `BusService.add_listener` where it already lives.

`DurationHoldManager` imports `build_tracked_invoke_fn` directly from the sibling `bus/invocation.py` module (no callback indirection). It holds `executor` and `config_resolver` as instance attributes and passes them through when building invoke functions in `immediate_fire_task`.

### New module: `src/hassette/bus/invocation.py` (~100 lines)

Extracts the tracked invoke function builder. Contains:

- `build_tracked_invoke_fn(listener, event, topic, executor, config_resolver, is_synthetic)` — a module-level function (not a class, since it's stateless). Encapsulates:
  - Timeout resolution (disabled → None, per-listener → value, else → config default)
  - App-level error handler resolution from `listener.invoker.app_error_handler_resolver`
  - `InvokeHandler` command construction
  - Executor dispatch via `executor.execute(cmd)`

BusService and DurationHoldManager both call this function (BusService for non-duration dispatch, DurationHoldManager for immediate-fire and timer-fire paths).

The `config_resolver` parameter is a `Callable[[], float | None]` that reads the current `event_handler_timeout_seconds` at call time (not capture time), preserving the lazy-resolution behavior for debounced handlers.

### New module: `src/hassette/core/event_filter.py` (~80 lines)

Extracts event filtering into a standalone utility (same pattern as `RegistrationTracker`). Contains:

- `EventFilter` class — constructed with config values (excluded domains, excluded entities):
  - `setup(domains, entities)` — parses into exact/glob sets (was `_setup_exclusion_filters`)
  - `should_skip(topic, event)` — returns True if event should be dropped (was `_should_skip_event`)
- No dependency on `Resource`, `Service`, or `Hassette` — receives config values, not the config object
- Snapshots exclusion config at construction time; does not observe config changes after init (same as current behavior — if hot-reload is added later, EventFilter must be reconstructed)
- `_should_log_event` stays on BusService — it mixes a `@cached_property` with live config reads that cannot be faithfully represented as constructor args without changing behavior

BusService constructs `EventFilter` in `__init__` with values from `self.hassette.config` and delegates skip/log decisions to it.

### BusService after extraction (~450 lines)

Retains:
- `__init__` — constructs EventFilter, DurationHoldManager, wires callbacks
- `add_listener` — orchestrates route insertion, DB registration, delegates duration wiring to manager
- `dispatch` — fanout loop: calls filter, expands topics, matches, spawns `_dispatch` tasks
- `_dispatch` — per-listener dispatch: builds invoke_fn (via `build_tracked_invoke_fn`), delegates duration path to manager, handles non-duration path inline
- `_expand_topics` — topic resolution
- Dispatch idle tracking (`_on_dispatch_done`, `is_dispatch_idle`, `await_dispatch_idle`, `dispatch_pending_count`)
- Registration (`_build_registration`, `_register_in_db`, `await_registrations_complete`, `drain_framework_registrations`)
- Listener CRUD (`remove_listener`, `remove_listeners_by_owner`, `get_listeners_by_owner`)
- Logging (`_should_log_event`, `config_log_level`, `config_log_all_events`)
- Service lifecycle (`before_initialize`, `serve`)

### Import graph (runtime only)

```
core/bus_service.py
  → core/event_filter.py          (same package)
  → bus/duration_hold.py           (core→bus, existing pattern)
  → bus/invocation.py              (core→bus, existing pattern)
  → bus/router.py                  (existing)
  → bus/listeners.py               (existing)

bus/duration_hold.py
  → bus/invocation.py              (sibling)
  → bus/listeners.py               (sibling)
  → bus/router.py                  (sibling)
  → bus/duration_timer.py          (sibling)
  → hassette.events                (leaf)
  → hassette.utils.date_utils      (leaf)

bus/invocation.py
  → core/commands.py               (leaf dataclass module)
  → bus/listeners.py               (sibling)
  → hassette.events                (leaf)

core/event_filter.py
  → hassette.events                (leaf)
  → hassette.utils.glob_utils      (leaf)
```

No cycles. `core/commands.py` is verified as a leaf (its imports: `bus/listeners.py`, `hassette.events`, `hassette.scheduler.classes`, `hassette.types`).

## Replacement Targets

No existing code is being replaced. This is a structural extraction — methods move between files but retain their logic unchanged. The old methods in `bus_service.py` are deleted after extraction (not preserved as stubs or re-exports).

## Convention Examples

### Callback injection pattern (DurationTimer)

**Source:** `src/hassette/bus/duration_timer.py:50-75`

```python
def __init__(
    self,
    task_bucket: "TaskBucket",
    duration: float,
    predicates: "Predicate | None",
    entity_id: str,
    owner_id: str,
    create_cancel_sub: "Callable[[], Subscription]",
    on_cancel: "Callable[[], None] | None" = None,
) -> None:
    self.task_bucket = task_bucket
    self.duration = duration
    self.predicates = predicates
    self.entity_id = entity_id
    self.owner_id = owner_id
    self._create_cancel_sub = create_cancel_sub
    self._on_cancel = on_cancel
```

DurationHoldManager follows this pattern — typed callbacks for dispatch tracking and state reading.

### Standalone utility (RegistrationTracker)

**Source:** `src/hassette/core/registration_tracker.py:1-7`

```python
"""Standalone tracker for pending DB registration tasks.

Encapsulates the prune-and-track, await-with-timeout, and drain patterns
that were previously duplicated in BusService and SchedulerService.

This class has NO dependency on Resource or Service — it is a plain utility.
"""
```

EventFilter follows this pattern — no Resource/Service inheritance, receives config values at construction.

### BusService test fixture (mock construction)

**Source:** `tests/unit/core/test_bus_service_public_accessors.py:27-33`

```python
@pytest.fixture
def bus_service() -> BusService:
    """Construct a BusService backed by mocks, ready for accessor tests."""
    hassette = make_mock_hassette()
    stream = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock()
    return BusService(hassette, stream=stream, executor=executor)
```

New modules should be testable with similar lightweight fixtures — mock callbacks for DurationHoldManager, direct construction for EventFilter.

## Alternatives Considered

### Alternative 1: Extract dispatch pipeline (issue's original proposal)

Extract `dispatch()`, `_expand_topics()`, `_dispatch()`, `_make_tracked_invoke_fn()` into a `DispatchPipeline` class. Rejected because dispatch IS what BusService does — extracting it makes BusService a hollow orchestrator of an orchestrator. The remaining methods (registration, idle tracking, listener CRUD) don't form a coherent "service" without dispatch.

### Alternative 2: Extract only event filtering

The smallest possible extraction (~80 lines). Gets BusService to ~866 lines — still over the 800-line ceiling. Insufficient on its own.

### Alternative 3: Move everything to bus/ (no core/ module)

Put EventFilter in `bus/event_filter.py`. Rejected because the filter is config-driven infrastructure (reads from `hassette.config`), not bus-domain logic. Other `core/` services might want event filtering in the future; keeping it in `core/` makes it reusable without a bus dependency.

## Test Strategy

### Existing Tests to Adapt

Existing tests should continue to pass with minimal changes. Potential adaptations:

- `tests/unit/core/test_bus_service_public_accessors.py` — may need fixture updates if BusService's internal construction changes (e.g., DurationHoldManager wiring)
- `tests/unit/core/test_bus_service_error_handler.py` — must be rewritten to call `build_tracked_invoke_fn()` directly with mock `executor` and `config_resolver` arguments (the method is no longer on BusService)
- `tests/unit/core/test_bus_service_timeout.py` — must be rewritten to call `build_tracked_invoke_fn()` directly with mock `executor` and `config_resolver` arguments (the method is no longer on BusService)
- `tests/unit/bus/test_bus_contract.py` — likely unchanged (tests Bus facade, not internals)
- `tests/integration/test_dispatch_unification.py` — likely unchanged (tests end-to-end behavior)
- `tests/integration/test_core.py` — likely unchanged (tests core lifecycle)
- `tests/integration/test_registration.py` — likely unchanged (tests registration flow)

### New Test Coverage

- **Unit tests for EventFilter** (FR#3): construct with config values, verify `should_skip` returns correct booleans for each filter type (entity exclusion, domain exclusion, system_log, non-HA events, no-payload)
- **Unit tests for DurationHoldManager** (FR#1, FR#5): construct with mock callbacks, verify `immediate_fire_task` calls the correct callbacks in sequence, verify timer start delegates correctly, verify cancel listener creation. Tests that call `create_cancel_listener` must be async (the method calls `asyncio.get_running_loop().create_future()`). Construction-only tests (`__init__` with mock callbacks) may remain synchronous.
- **Unit tests for build_tracked_invoke_fn** (FR#2): verify timeout resolution (disabled, per-listener, config default), verify InvokeHandler construction with correct fields

### Tests to Remove

No tests to remove.

## Documentation Updates

No documentation updates required. This is an internal structural refactor — no user-facing API, CLI, or configuration changes. The `bus_service` module's public interface is unchanged.

## Impact

### Changed Files

- `src/hassette/core/bus_service.py` — reduce from 946 to ~450 lines (remove extracted methods, add DurationHoldManager/EventFilter construction and delegation)
- `src/hassette/bus/duration_hold.py` — **new** (~220 lines)
- `src/hassette/bus/invocation.py` — **new** (~100 lines)
- `src/hassette/core/event_filter.py` — **new** (~80 lines)

### Behavioral Invariants

- All public methods on `BusService` (listed in FR#4) must continue to work identically
- External consumers importing from `hassette.core.bus_service` (Bus facade, AppHandler, ServiceWatcher, RuntimeQueryService, StateProxy, test harness, simulation) require zero import changes
- The `BusService` constructor signature remains unchanged
- `router` attribute stays on BusService (accessed by `app_lifecycle_service.py:551`)
- `task_bucket` behavior unchanged (spawned tasks, done callbacks)

### Blast Radius

Contained to `src/hassette/core/bus_service.py` and its new sibling modules. No downstream consumers, CLI commands, configuration, or API endpoints are affected. The Bus facade (`bus/bus.py`) continues to call `bus_service.add_listener()` and `bus_service.remove_listener()` unchanged.

## Open Questions

None — all decisions resolved during discovery.
