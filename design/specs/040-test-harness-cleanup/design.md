# Design: Test Harness Cleanup

**Date:** 2026-04-25
**Status:** approved
**Research:** /tmp/claude-mine-prior-art-a9olsU/brief.md
**Issues:** #590, #591, #592

## Problem

The test harness maintains a 90-line mock class that manually mirrors the production coordinator's 18 service attributes. Every time a new service is added to the coordinator, the mock must be updated separately — and forgetting to do so causes silent drift rather than a test failure. This manual duplication contradicts the "real objects with controlled cleanup" pattern used by mature projects (Home Assistant, Celery) for the same problem.

Additionally, test isolation between module-scoped fixtures relies on 4 separate autouse cleanup fixtures that each reset one component independently. This is fragile: adding a new stateful component requires adding a new cleanup fixture, and the existing fixtures access production internals through private attributes. Integration test files also access these same private attributes directly, creating a broad surface of implementation coupling.

The overall effect is a test infrastructure that works but is harder to understand, extend, and maintain than it needs to be.

## Goals

- Eliminate the manually maintained mock class entirely — zero lines of duplicated attribute declarations
- Make the test harness use a real coordinator instance, consistent with the production code path
- Remove all private attribute access from integration test files
- Consolidate per-test cleanup into a single entry point that automatically covers all active components
- Ensure that adding a new service to the coordinator requires zero changes to the test mock layer

## User Scenarios

### Test Author: Framework Developer

- **Goal:** Write an integration test for a new feature
- **Context:** Adding a bus listener test, needs a harness with bus and scheduler

#### Writing a new integration test

1. **Declare a fixture dependency**
   - Sees: fixture names in IDE autocomplete, typed as the harness wrapper
   - Decides: which components the test needs (bus, scheduler, state proxy, etc.)
   - Then: receives a harness instance with public accessor properties

2. **Access components under test**
   - Sees: public properties (`harness.bus`, `harness.scheduler`, `harness.state_proxy`)
   - Decides: which component to exercise
   - Then: calls methods on real component instances, not private attributes

3. **Run tests**
   - Sees: automatic cleanup between tests via a single autouse fixture
   - Decides: nothing — cleanup is transparent
   - Then: each test starts with clean component state regardless of what previous tests did

### Service Author: Framework Developer

- **Goal:** Add a new background service to the coordinator
- **Context:** Adding a new service that the coordinator manages

#### Adding a new service

1. **Add the service to the coordinator**
   - Sees: existing service declarations and wiring method
   - Decides: where in the initialization order the new service belongs
   - Then: adds the service to the wiring method; the coordinator's bare constructor already has a null slot

2. **Verify test compatibility**
   - Sees: all existing tests still pass — no mock class to update
   - Decides: whether the harness needs a builder method and starter for the new service
   - Then: if needed, adds a `with_<service>()` builder and starter to the harness

## Functional Requirements

1. The coordinator must support two-phase construction: bare initialization (no side effects, no service wiring) followed by an explicit wiring call that performs all service registration, side-effect initialization, and dependency validation
2. The bare coordinator instance must have all service attribute slots initialized to their empty/null state, so downstream code can safely check for their presence without attribute errors
3. All production call sites (3 locations) must call the wiring method after construction with no behavioral change
4. The test harness must use a real coordinator instance (thin subclass) instead of a manually maintained mock class
5. The thin subclass must override exactly 2 behaviors: skip dependency validation (test harness wires components selectively) and return success immediately from readiness checks (prevent deadlocks during test startup)
6. All 8 integration fixtures that currently yield a raw coordinator must yield the harness wrapper instead, with correct type annotations
7. All integration test files (15 files) must access components through the harness's public accessor properties, not through private attributes on the coordinator
8. A single `reset()` method on the harness must encapsulate all per-test cleanup, checking which components are active and calling the appropriate reset functions
9. The 4 autouse cleanup fixtures must be replaced by 1 that calls `reset()` on the active harness
10. The mock API fixture (yields a tuple, not a harness) must continue to work — its cleanup is handled inside `reset()` when an API mock is present
11. The existing `run_hassette_startup_tasks()` helper (which exists to avoid constructing a full coordinator) must be replaced by bare coordinator construction followed by the public `startup_tasks()` method call — no SimpleNamespace hack, no private method access

## Edge Cases

1. **Fixtures that yield tuples, not harness instances**: The mock API fixture yields `(Api, SimpleTestServer)`. This fixture is excluded from the consolidated cleanup fixture set. API mock reset is handled by `reset()` when called on any harness that has an API mock active.

2. **Function-scoped vs module-scoped fixtures**: Two fixtures (`hassette_with_app_handler`, `hassette_with_app_handler_custom_config`) are function-scoped because their tests mutate app handler state. The consolidated cleanup fixture must handle both scopes.

3. **Bus and Scheduler are siblings of StateProxy, not children**: In the harness, `Bus` and `Scheduler` are registered as siblings of `StateProxy` under `_TestableHassette`. `reset_state_proxy()` resets the proxy's internal state but does not clear the harness-level bus listeners or scheduler jobs. The `reset()` method resets each component independently when active — no conditional skipping.

4. **Concurrent fixture usage**: A test may use multiple harness fixtures from different modules. The consolidated cleanup fixture iterates all matching fixture names and resets each one. `reset()` is idempotent — `has_component()` guards skip absent components, so extra resets are safe and cheap.

5. **The `hassette_instance` fixture**: `tests/integration/conftest.py` has a separate `hassette_instance` fixture that creates a real fully-wired coordinator for lifecycle tests. After the two-phase split, this becomes `Hassette(config)` + `wire_services()`. Its teardown accesses `_event_stream_service` and `_bus_service.stream` directly — these accesses are on the real coordinator and are acceptable (not going through the harness).

## Acceptance Criteria

1. The manually maintained mock class is deleted — zero lines remain
2. All existing tests pass with no behavioral changes
3. No integration test file contains private attribute access on fixture parameters — verified by grep for `\._[a-z]` patterns on harness fixture params. `HassetteHarness` internals (`harness.py`) retain private attribute writes to `_TestableHassette` as an intentional coupling boundary — tests never see this. Accesses on `hassette_instance` in `test_core.py` are excluded (that fixture yields a real `Hassette` and its private-attribute access tests internal wiring).
4. The harness wrapper type appears in all integration fixture type annotations
5. Exactly 1 autouse cleanup fixture exists in integration conftest, replacing the previous 4
6. Adding a new service to the coordinator requires zero changes to any mock class
7. The test suite runs with `pytest-randomly` without ordering-dependent failures

## Dependencies and Assumptions

- The coordinator's `Resource` base class supports construction without a task bucket (it does — task bucket defaults to auto-creation)
- All 7 behavioral methods on the current mock (`send_event`, `wait_for_ready`, `get_app`, `loop`, `ws_url`, `rest_url`, `event_streams_closed`) already exist on the real coordinator class (verified)
- The existing reset functions in `reset.py` correctly reset all mutable state for their respective components

## Architecture

### Two-Phase Coordinator Construction

Split `Hassette.__init__` into two methods:

**`__init__(self, config: HassetteConfig)`** — bare setup only:
- `self.config = config`
- `enable_logging(self.config.log_level, ...)` — must precede `super().__init__()` because `Resource.__init__` calls `_setup_logger()`
- `super().__init__(self)` — Resource base (creates task bucket, logger, children list; sets `unique_id` to a UUID)
- Declare all ~18 service slots as `None` (same attributes currently in `_HassetteMock`)
- `self._loop = None`, `self._loop_thread_id = None`
- `self._init_order: list[type[Resource]] = []`, `self._init_waves: list[list[type[Resource]]] = []` — empty until `wire_services()` populates them
- Public instance slots: `self.api = None`, `self.states = None`, `self.state_registry = None`, `self.type_registry = None`

No side effects beyond logging configuration. No context var registration, no env file loading, no service wiring.

**`startup_tasks(self) -> None`** — one-time environment and manifest setup:
- `load_dotenv()` for configured env files (when `config.import_dot_env_files` is True)
- `config.set_validated_app_manifests()`
- `run_apps_pre_check()` (when configured)

This method is public because test code calls it directly via `run_hassette_startup_tasks()`. 7 of 11 test callers need the `load_dotenv` path; the remaining 4 test `import_dot_env_files=False` (which `startup_tasks()` handles by skipping the load).

**`wire_services(self) -> None`** — context registration, service wiring, and graph validation:
- `context.set_global_hassette(self)` / `context.set_global_hassette_config(self.config)`
- `self.startup_tasks()`
- All 18 `add_child()` calls in dependency order
- Dependency graph validation (`validate_dependency_graph`, `topological_sort`, `topological_levels`)
- Guard at the top of `run_forever()`: `if not self._init_waves: raise RuntimeError("call wire_services() before run_forever()")`
- `event_streams_closed` property: add `None` guard for `_event_stream_service` (return `True` when `None`)

Because `context.set_global_hassette` is in `wire_services()` and the harness never calls `wire_services()`, the harness's explicit registration at `HassetteHarness.__init__` remains the sole registration path for test instances — no change to harness context management is required.

The 3 production call sites become:
```python
# __main__.py
core = Hassette(config=config)
core.wire_services()

# tests/system/conftest.py
hassette = Hassette(config)
hassette.wire_services()

# tests/integration/conftest.py — hassette_instance fixture
instance = Hassette(test_config)
instance.wire_services()
```

### Thin Test Subclass

`_TestableHassette` in `src/hassette/test_utils/harness.py` — ~10 lines replacing 90:

```python
class _TestableHassette(Hassette):
    def _should_skip_dependency_check(self) -> bool:
        return True

    async def wait_for_ready(
        self, resources: list[Resource] | Resource, timeout: float | None = None
    ) -> bool:
        return True
```

`HassetteHarness.__init__` changes from `self.hassette = _HassetteMock(config=self.config)` to `self.hassette = _TestableHassette(config=self.config)`.

`HassetteHarness` must also add proxy properties for attributes that tests access directly on the fixture result. The existing accessors (`bus`, `scheduler`, `state_proxy`, `bus_service`, `scheduler_service`, `app_handler`) are joined by: `task_bucket`, `send_event`, `shutdown_event`, `api`, and `states` — all delegating to `self.hassette`. For `send_event`, the monkey-patch pattern in `test_service_watcher.py` (which assigns `hassette.send_event = mock_send`) must be updated to assign on `harness.hassette.send_event` directly, since property setters would add unnecessary complexity.

### Delete _HassetteMock

The entire `_HassetteMock` class (lines 90–181 of `harness.py`) is deleted. All its behavioral methods are already on real `Hassette`. The `_TestableHassette` subclass handles the 2 test-specific overrides.

### Fixture Migration

All 8 fixtures in `fixtures.py` that yield `cast("Hassette", harness.hassette)` change to yield `harness` directly:

```python
# Before
async def hassette_with_bus(...) -> AsyncIterator[Hassette]:
    async with hassette_harness(test_config).with_bus() as harness:
        yield cast("Hassette", harness.hassette)

# After
async def hassette_with_bus(...) -> AsyncIterator[HassetteHarness]:
    async with hassette_harness(test_config).with_bus() as harness:
        yield harness
```

The `hassette_with_mock_api` fixture is unchanged — it yields `tuple[Api, SimpleTestServer]` which is a different pattern.

### Integration Test File Migration

15 integration test files contain private attribute access on fixture parameters. Each file needs:
1. Parameter type annotation: `Hassette` → `HassetteHarness`
2. Private attribute access: `hassette._bus` → `hassette.bus`, `hassette._scheduler` → `hassette.scheduler`, `hassette._state_proxy` → `hassette.state_proxy`
3. Import changes: remove `Hassette` import if only used for type annotation; add `HassetteHarness` import

Files affected: `conftest.py`, `test_apps.py`, `test_apps_env.py`, `test_bus.py`, `test_bus_error_handler.py`, `test_core.py`, `test_file_watcher.py`, `test_framework_telemetry.py`, `test_hot_reload.py`, `test_lifecycle_propagation.py`, `test_scheduler.py`, `test_scheduler_error_handler.py`, `test_source_capture_integration.py`, `test_state_proxy.py`, `test_states.py`.

### Consolidated Cleanup

Add `HassetteHarness.reset()`:

```python
async def reset(self) -> None:
    if self.has_component("state_proxy"):
        await reset_state_proxy(self.state_proxy)
    if self.has_component("bus"):
        await reset_bus(self.bus)
    if self.has_component("scheduler"):
        await reset_scheduler(self.scheduler)
    if self.api_mock is not None:
        reset_mock_api(self.api_mock)
```

Note: `Bus` and `Scheduler` are siblings of `StateProxy` under the harness's `_TestableHassette` — not children of `StateProxy`. `reset_state_proxy()` resets the proxy's own internal state but does not clear the harness-level bus listeners or scheduler jobs. Each component is always reset independently when active. The cost is negligible (one `remove_all_listeners()` + one `_remove_all_jobs()` call per test).

Replace 4 autouse fixtures in `tests/integration/conftest.py` with 1:

```python
_HARNESS_FIXTURES = frozenset({
    "hassette_with_nothing",
    "hassette_with_bus",
    "hassette_with_scheduler",
    "hassette_with_file_watcher",
    "hassette_with_state_proxy",
    "hassette_with_state_registry",
    "hassette_with_app_handler",
    "hassette_with_app_handler_custom_config",
})

@pytest.fixture(autouse=True)
async def cleanup_harness(request: pytest.FixtureRequest) -> None:
    for name in _HARNESS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        await harness.reset()
```

### Cleanup of run_hassette_startup_tasks

The `run_hassette_startup_tasks()` function in `fixtures.py` exists because constructing a full `Hassette` had too many side effects — it used a `SimpleNamespace` hack to call `_startup_tasks()` in isolation. After two-phase construction, the hack is replaced by the public `startup_tasks()` method:

```python
def run_hassette_startup_tasks(config: HassetteConfig) -> None:
    Hassette(config).startup_tasks()
```

**Caller audit** (11 call sites): 7 callers need `load_dotenv` (they test env file loading with `import_dot_env_files=True`), 4 callers test `import_dot_env_files=False` (which `startup_tasks()` handles by skipping the load). All callers need `config.set_validated_app_manifests()`. Replacing with `config.set_validated_app_manifests()` only would silently drop `load_dotenv` coverage for 7 callers — `test_config.py:405` explicitly documents xdist interactions with `load_dotenv`. The helper must continue calling the full `startup_tasks()` flow.

## Alternatives Considered

### Auto-populate mock attributes from coordinator introspection

Keep `_HassetteMock` as a `Resource` subclass but auto-set null service slots by inspecting `Hassette.__init__`'s assignments at construction time. This eliminates the manual attribute list but preserves the mock class and the conceptual overhead of two parallel hierarchies. Rejected because the two-phase construction approach is simpler and eliminates the mock entirely.

### MagicMock(spec=Hassette) with behavioral overrides

Replace `_HassetteMock` with `MagicMock(spec=Hassette)` and patch the behavioral methods. Auto-mirrors all attributes. Rejected because: (1) `autospec` doesn't detect `__init__`-level attributes without an instance, (2) known deadlock risk with MagicMock in async contexts (documented in project memory), (3) behavioral methods need real implementations, not mock return values.

### Constructor parameter (test_mode flag)

Add `test_mode: bool = False` to `Hassette.__init__` that skips dependency checks and makes `wait_for_ready` a no-op. Rejected because it leaks test concerns into production code and violates separation of concerns. The thin subclass achieves the same result without polluting the production class.

## Test Strategy

- **Correctness**: Run the full test suite (`uv run nox -s dev -- -n 2`) after each phase to verify no regressions
- **Drift verification**: Grep for `._bus\b`, `._scheduler\b`, `._state_proxy\b`, `._app_handler\b` in integration test files to verify all private access is eliminated
- **Ordering independence**: Run with `pytest-randomly` to verify no ordering-dependent failures from cleanup changes
- **Cleanup completeness**: Verify that a test registering bus listeners and scheduler jobs leaves no residual state for the next test (existing tests already verify this implicitly)

## Documentation Updates

- `tests/TESTING.md`: Update fixture types (yield `HassetteHarness` not `Hassette`), cleanup pattern (single `reset()` not 4 fixtures), remove "out of scope for WP04" notes
- Docstrings on `Hassette.__init__` and `wire_services()` explaining the two-phase pattern
- `_TestableHassette` docstring explaining why it exists

## Impact

### Files modified

**Core production code (1 file)**:
- `src/hassette/core/core.py` — split `__init__` into `__init__` + `wire_services()`

**Test utilities (3 files)**:
- `src/hassette/test_utils/harness.py` — delete `_HassetteMock`, add `_TestableHassette`, add `reset()`, update `HassetteHarness.__init__`
- `src/hassette/test_utils/fixtures.py` — change 8 fixture return types and yield values, update `run_hassette_startup_tasks`
- `src/hassette/test_utils/reset.py` — no changes (existing functions reused)

**Production call sites (2 files)**:
- `src/hassette/__main__.py` — add `core.wire_services()` after construction
- `tests/system/conftest.py` — add `hassette.wire_services()` after construction

**Integration tests (16 files)**:
- `tests/integration/conftest.py` — replace 4 cleanup fixtures with 1, update `hassette_instance`
- 15 integration test files — parameter types, private access → public accessors, import changes

**Documentation (1 file)**:
- `tests/TESTING.md` — reflect new fixture types and cleanup pattern

**Total**: ~23 files. Blast radius is contained to test infrastructure and the 3-line production code split. The `wire_services()` change is backward-compatible (same behavior, different call structure).

## Open Questions

None — all design decisions resolved during discovery and challenge.
