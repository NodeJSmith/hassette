# Design: Test Infrastructure Cleanup

**Date:** 2026-04-24
**Status:** approved
**Research:** Challenge findings at `/tmp/claude-mine-challenge-ja52QP/findings.md` (27 findings from 5-critic codebase audit); design challenge at `/tmp/claude-mine-define-challenge-ct32lt/findings.md` (26 findings from 6-critic design review); infrastructure survey of all conftest files and test_utils modules

## Problem

The test harness has accumulated structural debt that undermines its primary purpose: catching real failures. Silent exception swallowing at 7 distinct points in teardown means assertion failures are logged instead of raised. Hardcoded metadata tables drift from production's algorithmic derivation with no detection. Shared mutable class-level state creates config races between concurrent test setups. Tight coupling to framework internals through 100+ direct accesses to private attributes amplifies every refactor into a cross-cutting change. Test-only flags embedded in production code create architectural violations that constrain future design.

The result: tests pass when they should fail, fixture cleanup failures propagate silently to downstream tests, and every change to the framework's internal structure requires synchronized edits across harness code, mixin modules, recording API, and individual test files.

## Goals

1. Zero silent exception swallowing in test teardown — every assertion failure and cleanup error surfaces to the test framework
2. Algorithmically derived startup ordering — the harness derives component order from the same dependency graph as production, eliminating hardcoded metadata drift
3. No shared mutable class-level state — config construction is stateless and race-free
4. Single adaptation point for framework internals — private attribute access from outside `harness.py` is replaced with stable public accessors
5. No test-only flags in production code — test hooks are reachable only through harness-layer interfaces
6. All fixture cleanup uses yield-based patterns with error surfacing
7. No hardcoded sleeps in test infrastructure (polling loops in test bodies are separate from infrastructure)
8. Measurable improvement in test suite reliability on resource-constrained hosts

## User Scenarios

### Framework Developer: Maintainer adding a new service

- **Goal:** Add a new core service with dependency declarations and have the harness support it automatically
- **Context:** During feature development, when the developer needs integration tests for a new service

#### Adding a new harness component

1. **Declares `depends_on` on the service class**
   - Sees: The production dependency graph determines startup ordering
   - Decides: What other services this one depends on
   - Then: The harness automatically derives startup order from the new dependency

2. **Adds a builder method and starter to the harness**
   - Sees: A single location to add the component (`_starters` dict + `with_*()` method)
   - Decides: What mock wiring the component needs
   - Then: The consistency test validates the harness metadata matches real `depends_on`

3. **Writes integration tests using the harness**
   - Sees: Builder-chain API (`harness.with_new_service().with_bus()`)
   - Decides: Which components the test needs
   - Then: Dependencies are resolved automatically; startup order is correct by construction

### App Developer: End user testing automations

- **Goal:** Write reliable tests for Home Assistant automations using the public test API
- **Context:** During app development, using `AppTestHarness` and `RecordingApi`

#### Testing an automation with state changes

1. **Sets up the harness with config and initial state**
   - Sees: Clear error messages when config validation fails
   - Decides: Which entities to seed and what initial state they have
   - Then: State is seeded without race conditions regardless of test concurrency

2. **Simulates events and asserts on API calls**
   - Sees: Exact-match and partial-match assertion options with clear naming
   - Decides: Whether to assert exact kwargs or allow partial matching
   - Then: Drain completes deterministically; handler exceptions surface as test failures

3. **Cleans up between tests**
   - Sees: Cleanup errors reported at the test boundary where they occurred
   - Decides: Nothing — cleanup is automatic via yield fixtures
   - Then: Next test starts with guaranteed clean state

### CI System: Automated test runner

- **Goal:** Run the full test suite reliably with deterministic results
- **Context:** GitHub Actions, potentially on resource-constrained runners

#### Running integration tests with module-scoped fixtures

1. **Initializes module-scoped harnesses**
   - Sees: Consistent startup ordering matching production
   - Decides: Nothing — fixtures are automatic
   - Then: All components reach ready state with checked timeouts

2. **Runs tests with autouse cleanup**
   - Sees: Cleanup errors surfaced immediately, not deferred to downstream tests
   - Decides: Nothing — autouse fixtures handle reset
   - Then: Each test starts with verified clean state

3. **Tears down harnesses**
   - Sees: All resources shut down with logged results; assertion failures raised after cleanup completes
   - Decides: Nothing — teardown is automatic
   - Then: No leaked task factories, context vars, or background tasks

## Functional Requirements

### Stream 1: Harness Dependency Model

1. The harness must derive component startup order from `_DEPENDENCIES` at module load time via a string-based topological sort (not reusing `service_utils.topological_sort`, which operates on `type[Resource]`)
2. Every entry in the harness dependency metadata must have a corresponding builder method and starter, or be explicitly excluded with documented rationale
3. A consistency test must verify that the set of startable components matches the dependency metadata (no ghost entries)
4. Dead code must be removed: `start_resource` function, `_tasks` list and cancellation loop in `stop()`, and `service_watcher` ghost entry (present in `_DEPENDENCIES`, `_STARTUP_ORDER`, and `_COMPONENT_CLASS_MAP` but has no builder, starter, or `_start_*` method). After removing `_tasks`, document `self._exit_stack` as the canonical cleanup registry for starters that need background-task cleanup

### Stream 2: Teardown and Lifecycle Reliability

5. Teardown must surface assertion failures (`assert_clean()`) to the test framework after completing all other cleanup steps
6. The `shutdown_resource` helper must log shutdown failures instead of suppressing them. The teardown loop must not break on first failure — all resources must receive a shutdown attempt regardless of earlier failures; exceptions are collected and re-raised as an `ExceptionGroup` after all resources have been attempted
7. All integration cleanup fixtures must use yield-based patterns with error surfacing (no bare `except Exception: pass`)
8. The `asyncio.sleep(0)` calls after fully-awaited `shutdown_resource()` in `stop()` must be removed — `shutdown()` already awaits to completion, so these are unnecessary cooperative yields, not polls
9. The task factory installed during `start()` must be saved (`get_task_factory()`) and restored during `stop()` — this is a latent bug affecting module-scoped fixtures where sequential `HassetteHarness` instances inherit a stale factory
10. The context variable token from `set_global_hassette()` must be saved at `start()` and reset via `HASSETTE_INSTANCE.reset(token)` during `stop()` — this is a latent bug; `AppTestHarness` already handles this correctly via `context.use()`

### Stream 3: State Integrity and Fixture Correctness

11. Config construction for `AppTestHarness` must not use shared class-level mutable state; each instantiation must be stateless
12. The `get_states_raw` return value on the default API mock must be explicitly configured (not relying on `MagicMock.__iter__` behavior)
13. The exception recorder on `TaskBucket` must support multiple concurrent recorders without silent overwrite
14. The global registry isolation fixture (`_isolate_registries`) must use deep copies for mutable registry contents
15. Event fixture randomization must use a deterministic seed (logged for reproducibility)
16. The `hassette_with_app_handler` fixture must be unblocked for module scope after the config race is fixed

### Stream 4: Coupling Reduction

17. Harness mixins and `RecordingApi` must access framework internals through public accessor properties on `HassetteHarness`, not through `_HassetteMock` private attributes
18. `_test_seed_state` must be removed from `StateProxy` and reimplemented as a harness-level helper that writes to `state_proxy.states` under the proxy's lock (with `asyncio.wait_for(lock.acquire(), timeout=5.0)` to convert hangs into diagnostic failures). `_test_trigger_due_jobs` must be renamed to public `trigger_due_jobs()` on `SchedulerService`, documented as bypassing the serve loop for controlled test dispatch — a single public method is less coupling than exposing `_job_queue`
19. URL and auth header configuration for `ApiResource` must be injectable through keyword-only constructor parameters (`*, rest_url: str | None = None, headers_factory: Callable[[], dict[str, str]] | None = None`); when `None`, `on_initialize` falls back to property-derived values; the harness passes explicit values, production does not
20. `SimpleTestServer` must own its reset contract via a `reset()` method instead of external private-field mutation
21. The no-op `cast("ApiProtocol", RecordingApi)` must be removed — conformance is already verified by Pyright (structural) and `test_recording_api_protocol_parity.py` (behavioral), both strictly stronger than `@runtime_checkable isinstance`
22. The three overlapping config construction patterns (`TestConfig`, `_HermeticHassetteConfig`, `make_test_config()`) must be consolidated into a single mechanism

### Stream 5: E2E Infrastructure

23. The 565-line `mock_hassette` fixture must be extracted into a dedicated module with composable factory functions
24. The `live_server` fixture must use event-driven startup detection (not `time.sleep` polling) and verified shutdown
25. The `_fastapi_app` fixture's patcher must be properly stopped during teardown
26. Fixture definitions shared between integration and e2e conftest files (`runtime_query_service`, `app`) must be deduplicated
27. Legacy snapshot factories (`make_old_app_instance`, `make_old_snapshot`) must be removed if unused, or migrated if still referenced

### Stream 6: API Surface and Developer Experience

28. `RecordingApi` must provide `assert_called_exact` for exact-match assertions alongside the existing `assert_called` (partial match), with an `assert_called_partial` non-deprecated alias for discoverability; `tests/TESTING.md` must document both methods and the default partial-match behavior
29. The drain mechanism must emit a warning when bus-level tasks are detected but not drained
30. The `wait_for_ready` return value in `HassetteHarness.start()` must be checked, with a timeout error raised on failure
31. The `wait_for_ready` no-op behavior in `_HassetteMock` must be documented with guidance on testing startup races
32. `RecordingApi` helper CRUD methods must be genericized using the existing `_RECORD_TYPE_TO_DOMAIN` dispatch table in `recording_api.py`, reducing the per-domain method count without modifying production model classes
33. Timeout constants used across test infrastructure must be centralized with documented rationale

## Edge Cases

1. **Concurrent `AppTestHarness` instances for the same `App` class** — after Stream 3, the ClassVar channel is replaced by a closure (race-free by construction). The `_HERMETIC_CONFIG_CACHE` is retained to prevent Pydantic subclass accumulation
2. **Cleanup failure during cleanup** — if `reset_state_proxy()` fails, the error must surface without preventing subsequent cleanup steps from running
3. **Module-scoped fixture with function-scoped test failure** — a crashed test must not leave the module-scoped harness in a state that poisons the next test
4. **E2E server startup timeout** — if the uvicorn server fails to bind, the error must be immediate and diagnostic, not a 10-second hang
5. **TaskBucket with multiple exception recorders** — install/uninstall must be LIFO-safe; uninstalling a recorder that was already uninstalled must not raise
6. **Empty `_DEPENDENCIES` graph** — topological sort of an empty graph must produce an empty startup order, not an error
7. **`ApiResource` constructor injection with None values** — the harness must handle the case where URL or headers are not yet configured at construction time
8. **`assert_called_exact` with no recorded calls** — must produce a clear error message, not a confusing empty-dict comparison

## Acceptance Criteria

1. The test suite passes on all three Python versions (3.11, 3.12, 3.13) with zero silent exception swallowing — verified by grep for `except Exception: pass` in test infrastructure files returning zero results
2. The harness startup order is derived algorithmically — no `_STARTUP_ORDER` list exists in `harness.py`
3. `hassette_with_app_handler` fixture is module-scoped — verified by reading `fixtures.py` and confirming `scope="module"`
4. Zero `getattr(self.hassette, "_test_mode"` occurrences in production code
5. Zero `harness.hassette._` accesses from `simulation.py`, `time_control.py`, and `recording_api.py` — all go through public accessors. `web_mocks.py` (MagicMock stub — different code path) and `reset.py` (`_shutting_down`, `_shutdown_completed` — no proposed accessor) are out of scope; tracked with inline comments for follow-up
6. No `time.sleep` or `asyncio.sleep(0.05)` fixed delays in test infrastructure code (excluding test bodies that intentionally test timing)
7. The e2e conftest is under 400 lines with fixture factories extracted to a module
8. `RecordingApi` helper CRUD methods are reduced from 32 to a generic core (dispatching via `_RECORD_TYPE_TO_DOMAIN` in `recording_api.py`) plus thin typed delegations — no production model changes
9. All cleanup fixtures use `yield` with error surfacing
10. Test suite execution time does not regress by more than 5% (and may improve from eliminating fixed sleeps and enabling module-scoped `app_handler`)

## Dependencies and Assumptions

1. **PR #585 (sleep replacements)** — already merged; this work builds on the deterministic polling patterns it introduced
2. **PR #584 (wave-based startup/shutdown)** — already merged; the `topological_sort` and `topological_levels` functions in `service_utils.py` are available for reuse
3. **`pydantic-settings`** — Stream 3 requires understanding `settings_customise_sources` to eliminate the ClassVar communication channel
4. **`pytest-asyncio`** — the project uses `asyncio_mode = "auto"` with session-scoped event loops; changes to fixture scoping must be compatible
5. **Assumption:** The two-harness architecture (`HassetteHarness` for integration, `AppTestHarness` for app testing) is currently assumed sound — this design improves both without merging them, but the architecture itself is open to challenge if a better structure emerges
6. **Assumption:** The `_RecordingSyncFacade` code generation pipeline (`tools/generate_sync_facade.py`) will be re-run after `RecordingApi` CRUD genericization

## Architecture

### Stream ordering and rationale

Streams are ordered so each makes the next safer:

**Stream 1 (Dependency Model)** is a small, self-contained change to `harness.py` that removes ghost metadata, derives startup order, and deletes dead code. It establishes the pattern of "derive from source of truth" that the rest of the cleanup follows.

**Stream 2 (Teardown Reliability)** is the highest-impact safety improvement. After this stream, every test failure surfaces at the correct boundary, making it safe to make the deeper structural changes in subsequent streams.

**Stream 3 (State Integrity)** fixes shared-state races and fixture correctness. This must come after Stream 2 because the config race fix (F3) changes `AppTestHarness._setup()` ordering, and we need reliable teardown to catch any regressions.

**Stream 4 (Coupling Reduction)** is the largest structural change — it introduces a public accessor layer on `HassetteHarness`, removes production test-mode flags, and makes `ApiResource` injectable. This benefits from the safety nets established in Streams 2-3.

**Stream 5 (E2E Infrastructure)** is isolated from the other streams (e2e tests run independently) but benefits from the patterns established earlier. The `mock_hassette` extraction and `live_server` fix are self-contained.

**Stream 6 (API Surface)** is polish — adding `assert_called_exact`/`assert_called_partial`, genericizing CRUD methods, centralizing timeouts. Low risk, high quality-of-life.

### Key architectural decisions

**Dependency derivation (Stream 1):** Replace the four parallel metadata tables (`_DEPENDENCIES`, `_STARTUP_ORDER`, `_COMPONENT_CLASS_MAP`, `_starters`) with:
- `_COMPONENT_CLASS_MAP` — retained as the authoritative mapping of harness names to real service classes
- `_starters` — retained as the dispatch table for component startup
- `_DEPENDENCIES` — retained as the authority (string-keyed), with explicit overrides for components whose harness deps intentionally diverge from production (e.g., `app_handler` and `state_proxy` omit `WebsocketService`/`ApiResource`); `service_watcher` ghost entry removed
- `_STARTUP_ORDER` — eliminated; computed at module load time via a string-based topological sort over `_DEPENDENCIES` (not reusing `service_utils.topological_sort`, which operates on `type[Resource]`)

A structural test asserts `_starters.keys() == set(_COMPONENT_CLASS_MAP.keys()) | set(harness_only_components)` (with `harness_only_components` explicitly enumerated). The existing bidirectional consistency test (`test_harness_dependency_consistency.py`) is updated and kept alongside the structural test — the two are orthogonal: the structural test catches ghost starters, the bidirectional test catches drift between `_DEPENDENCIES` and production `depends_on`.

**Hermetic config fix (Stream 3):** Replace the `_hermetic_init_kwargs` ClassVar communication channel with a closure-based approach. Instead of writing to a shared class variable, `_make_hermetic_config()` captures `config_dict` in a closure passed to `settings_customise_sources`, protected by the existing per-class lock (`_get_class_lock`). The `_HERMETIC_CONFIG_CACHE` is retained — its purpose is preventing Pydantic subclass accumulation in `__subclasses__()` and the validator cache, not race amortization; without it, each call creates a permanently registered model subclass that accumulates across a 2394-test suite. The ClassVar race is theoretical under asyncio's cooperative multitasking (no `await` between the write and read), but eliminating the shared mutable state is defensive hardening.

**Public accessor layer (Stream 4):** Add properties to `HassetteHarness`:
- `harness.state_proxy` → `self.hassette._state_proxy`
- `harness.bus_service` → `self.hassette._bus_service`
- `harness.scheduler_service` → `self.hassette._scheduler_service`
- `harness.bus` → `self.hassette._bus`
- `harness.scheduler` → `self.hassette._scheduler`
- `harness.app_handler` → `self.hassette._app_handler`

Mixins (`SimulationMixin`, `TimeControlMixin`) and `RecordingApi` access these through the harness, not through `_HassetteMock` directly. External test code that accesses `harness.hassette._*` is updated to use the new properties.

**Test-mode removal (Stream 4):** `_test_seed_state` is removed from `StateProxy` and reimplemented as a harness-level helper that writes directly to `state_proxy.states` under the proxy's lock (with `asyncio.wait_for(lock.acquire(), timeout=5.0)` to convert hangs into diagnostic failures). `_test_trigger_due_jobs` is renamed to public `trigger_due_jobs()` on `SchedulerService` — a single public, documented method that bypasses the serve loop is less coupling than exposing `_job_queue` to the harness. The `_test_mode` flag is removed from `_HassetteMock` and all `getattr(self.hassette, "_test_mode")` checks in production code are deleted.

**ApiResource injection (Stream 4):** Add keyword-only constructor parameters to `ApiResource`: `*, rest_url: str | None = None, headers_factory: Callable[[], dict[str, str]] | None = None`. When `None`, `on_initialize` falls back to property-derived values (`self.hassette.rest_url`, `self.hassette.config.headers`). The harness passes explicit values at construction time instead of patching private properties via string paths; production code passes neither (uses defaults).

**CRUD genericization (Stream 6):** Implement 4 generic methods on `RecordingApi` (`_list_helpers`, `_create_helper`, `_update_helper`, `_delete_helper`) dispatching via the existing `_RECORD_TYPE_TO_DOMAIN` dict in `recording_api.py`. The 32 existing methods become thin typed delegations. `InputSelectRecord` deep-copy handling is encoded in the dispatch table (not on the model class). No production model changes — `_RECORD_TYPE_TO_DOMAIN` is already in the correct layer and stays there. The `_RecordingSyncFacade` generator is updated to handle the new delegation pattern.

### Files affected per stream

**Stream 1** (~5 files):
- `src/hassette/test_utils/harness.py` — remove ghost entry, derive ordering, delete dead code
- `tests/unit/test_harness_dependency_consistency.py` — update for derived `_DEPENDENCIES`; add structural `_starters.keys()` test alongside existing bidirectional test
- `src/hassette/test_utils/fixtures.py` — no change expected

**Stream 2** (~6 files):
- `src/hassette/test_utils/harness.py` — fix `stop()` teardown, restore task factory, save ContextVar token
- `tests/integration/conftest.py` — convert 4 cleanup fixtures to yield pattern with error surfacing
- `src/hassette/test_utils/reset.py` — no functional change, but callers change

**Stream 3** (~6 files):
- `src/hassette/test_utils/app_harness.py` — eliminate ClassVar race in hermetic config
- `src/hassette/test_utils/harness.py` — configure `get_states_raw` on default API mock
- `src/hassette/task_bucket.py` — change exception recorder to list
- `tests/conftest.py` — verify/fix `_isolate_registries` deep copy; seed event shuffling
- `src/hassette/test_utils/fixtures.py` — upgrade `hassette_with_app_handler` to module scope

**Stream 4** (~12 files):
- `src/hassette/test_utils/harness.py` — add public accessor properties
- `src/hassette/test_utils/simulation.py` — use accessors instead of `harness.hassette._*`
- `src/hassette/test_utils/time_control.py` — use accessors
- `src/hassette/test_utils/recording_api.py` — use accessors for `_state_proxy`
- `src/hassette/test_utils/reset.py` — add `SimpleTestServer.reset()`, delegate
- `src/hassette/test_utils/test_server.py` — add `reset()` method
- `src/hassette/core/state_proxy.py` — remove `_test_seed_state` and `_test_mode` checks
- `src/hassette/core/scheduler_service.py` — rename `_test_trigger_due_jobs` to public `trigger_due_jobs()`
- `src/hassette/core/api_resource.py` — add injectable `rest_url`/`headers_factory` constructor params
- `src/hassette/test_utils/config.py` — consolidate config patterns
- `tests/unit/test_framework_injection_points.py` — delete `TestStateProxySeedState` and `_test_mode`-dependent tests; migrate state-seeding coverage to harness-level tests
- `tests/integration/conftest.py` — update `reset_mock_api` to delegate to `server.reset()`
- Tests using `harness.hassette._*` — update to use public accessors

**Stream 5** (~5 files):
- `tests/e2e/conftest.py` — extract `mock_hassette`, fix `live_server` (event-driven startup + `thread.is_alive()` verified shutdown), fix patcher leak
- `tests/e2e/mock_fixtures.py` (new) — extracted factory functions
- `src/hassette/test_utils/web_helpers.py` — remove legacy factories if unused
- `tests/integration/conftest.py` — deduplicate shared fixtures

**Stream 6** (~8 files):
- `src/hassette/test_utils/recording_api.py` — add `assert_called_exact`, add `assert_called_partial` alias, genericize CRUD via existing `_RECORD_TYPE_TO_DOMAIN`
- `src/hassette/test_utils/sync_facade.py` — regenerated after CRUD changes
- `src/hassette/test_utils/simulation.py` — add bus-level task drain warning
- `src/hassette/test_utils/harness.py` — check `wait_for_ready` return value
- `tools/generate_sync_facade.py` — update for new CRUD pattern
- `tests/integration/test_app_harness_simulation.py` — replace `_FREEZE_TIME_LOCK.locked()` assertion with behavioral test (attempt second `freeze_time()` inside active freeze, assert `RuntimeError`)
- Tests and conftest files — centralize timeout constants

## Alternatives Considered

**Alternative 1: Incremental fixes per finding.** Address each of the 27 challenge findings as individual PRs. Rejected because many findings are interconnected (e.g., the teardown reliability fixes enable safe refactoring in later streams), and per-finding PRs would create 27 small changes that are harder to review in aggregate and more likely to create merge conflicts.

**Alternative 2: Full test rewrite.** Rewrite the entire test infrastructure from scratch. The current assessment is that the problems are implementation quality (silent failures, tight coupling, shared mutable state) rather than architectural — but the architecture itself (two harness types, builder pattern, module-scoped fixtures with autouse cleanup) has not been independently validated and may warrant reconsideration.

**Alternative 3: Skip production code changes.** Limit scope to test infrastructure only, keeping `_test_mode` flags in production code. Rejected because the user explicitly approved production code changes, and removing test-mode coupling from production code is the architecturally correct approach.

## Test Strategy

Each stream's changes are verified by:

1. **Existing test suite** — all 2394 tests must pass after each stream. Regressions are blockers.
2. **Stream-specific verification:**
   - Stream 1: Structural test asserting `_starters.keys()` matches dependency metadata; bidirectional consistency test updated and retained
   - Stream 2: Verify no `except Exception: pass` in test infrastructure; manual test that a cleanup failure surfaces
   - Stream 3: Test concurrent `AppTestHarness` instantiation for the same App class
   - Stream 4: Grep for `harness.hassette._` and `_test_mode` in production — zero hits
   - Stream 5: E2E suite passes; `mock_hassette` is importable from extracted module
   - Stream 6: Test `assert_called_exact` with both match and mismatch cases
3. **Pyright** — clean type checking after each stream
4. **Performance** — nox dev session timing compared before/after; module-scoped `app_handler` should improve integration test speed

## Documentation Updates

- `tests/TESTING.md` — update to reflect new fixture patterns (yield-based cleanup, public accessors, exact-match vs partial-match assertions with clear documentation of default partial-match behavior)
- `CLAUDE.md` — update "Regression test patterns" section to document `wait_for_ready` no-op limitation and the correct approach for startup-race tests
- Docstrings on `HassetteHarness` public accessors, `RecordingApi.assert_called` (document partial matching), `RecordingApi.assert_called_exact` (new method)

## Impact

- **Test infrastructure:** ~25 files modified across `src/hassette/test_utils/`, `tests/conftest.py`, `tests/integration/conftest.py`, `tests/e2e/conftest.py`
- **Production code:** 3 files (`state_proxy.py`, `scheduler_service.py`, `api_resource.py`) — removing test-mode flags and adding constructor injection
- **Generated code:** `sync_facade.py` regenerated after CRUD changes
- **Blast radius:** High within test infrastructure, low for production code. Each stream is independently shippable — if a stream introduces regressions, it can be reverted without affecting other streams — **except** Stream 4, whose production removals and harness additions are atomic and must ship together.

<!-- Gap check 2026-04-25: 3 gaps found — all in Stream 4 (Callers category):
  - tests/integration/test_bus_immediate.py (~15 _test_seed_state calls, _test_mode) → WP04 subtask 10
  - tests/integration/test_bus_duration.py (_test_seed_state, _test_mode) → WP04 subtask 11
  - tests/integration/test_bus_error_handler_combos.py (~9 _test_seed_state calls, _test_mode) → WP04 subtask 12
  Categories searched: Tests, Callers, Validators/guards, Generated code, Type aliases. Skipped: CSS/layout, SQL, Documentation (no relevant surface). -->

## Open Questions

None — all design decisions are resolved. The challenge findings provided concrete options for each finding, and the user's discovery answers resolved all scope and constraint questions.
