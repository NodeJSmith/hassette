# Design: Test Infrastructure Deduplication & LLM Prevention

**Date:** 2026-07-08
**Status:** draft
**Scope-mode:** hold
**Research:** `design/research/2026-07-08-llm-test-infra-duplication/research.md`

## Problem

The test infrastructure has accumulated duplication debt: ~173 local `make_*/build_*` factory functions scattered across 387 test files, while `test_utils/factories.py` (built to absorb them) holds only 3 factories. The same conceptual object (`ScheduledJob`, `Event`, `CommandExecutor` mock) is built 6-11 different ways across sibling files. Factory names are overloaded — `make_job` and `make_manifest` each mean 2-3 different return types depending on which file you're in.

This duplication is the predictable result of LLM-assisted development without structural prevention. The project's test infrastructure has no enforcement: CLAUDE.md points to TESTING.md (a two-hop discovery chain), no `.claude/rules/` file addresses test writing, and no lint rule catches factory reinvention. An LLM that doesn't read TESTING.md has nothing stopping it from creating yet another `make_job()`.

Additionally, 13 of 19 test app files in `tests/data/apps/` are dead code (verified by full test suite run — 8662 passed after deletion), 4 test_utils exports have zero callers, and 3 fixtures (`app`, `client`, `runtime_query_service`) sit in the wrong directory level.

## Goals

1. Consolidate the 5 worst factory duplication hotspots into shared, override-friendly factories
2. Delete confirmed dead code across test data, test_utils exports, and fixtures
3. Fix misplaced fixtures and naming collisions identified by the audit
4. Establish a `.claude/rules/test-conventions.md` that closes the two-hop discovery gap
5. Add CLAUDE.md files to key test directories with module-specific fixture pointers
6. Write a `tools/check_test_factories.py` linter that catches future factory reinvention
7. Document decision rules in TESTING.md for the mock strategy choice and naming conventions

## Non-Goals

- Restructuring `harness.py` (820 lines) — worth doing but a separate scope
- Splitting `recording_api.py` or making its CRUD methods table-driven
- Changing test directory structure or co-locating tests with source
- Addressing the pre-existing Python 3.14 async mock failures (separate issue)
- Replacing `hassette_instance` in `tests/integration/conftest.py` with `HassetteHarness` — the highest-severity audit finding, but it touches 31 test functions across 3 files (`test_core.py`, `test_fatal_shutdown.py`, `test_resource_deps.py`) and warrants its own spec

## User Scenarios

### Framework Developer: Writing a new test

- **Goal:** Add tests for a new or modified component using the correct shared infrastructure
- **Context:** During feature development, when the developer (or LLM) needs to create test fixtures

#### Finding the right factory

1. **Opens or creates a test file**
   - Sees: If a CLAUDE.md exists in the test directory, it lists the module-specific fixtures and helpers available
   - Decides: Which factory or fixture to use for the test's setup
   - Then: Imports from `hassette.test_utils` rather than defining a local helper

2. **Attempts to define a local factory**
   - Sees: Pre-commit hook reports a violation if the local `def make_*` name matches or closely matches a shared factory
   - Decides: Whether this is a genuinely local concern or should use the shared factory
   - Then: Either imports the shared factory or adds an exemption annotation

### Framework Developer: Adding a new shared factory

- **Goal:** Promote a frequently-duplicated local helper to `test_utils/factories.py`
- **Context:** After noticing the same helper defined in 3+ files

#### Promoting a factory

1. **Adds the factory to `test_utils/factories.py`**
   - Sees: Existing factories follow keyword-only args with sensible defaults
   - Decides: Which parameters to expose (union of the local variants' parameters)
   - Then: Adds the factory, updates `__init__.py` exports if Tier 1, adds to the linter's registry

2. **Migrates callers**
   - Sees: grep for the old local function name across test files
   - Decides: Whether each local variant is subsumed by the shared factory or legitimately different
   - Then: Replaces local definitions with imports; the linter prevents regression

## Functional Requirements

- **FR#1** `test_utils/factories.py` exports `make_scheduled_job()` — a keyword-only factory returning a real `ScheduledJob` with overridable fields (`job`, `name`, `owner_id`, `next_run`, `trigger`, `group`, `jitter`, `timeout`, `timeout_disabled`, `error_handler`, `mode`, `db_id`, `predicate`), defaulting to `owner_id="test_owner"`, `name="test_job"`, `next_run=date_utils.now()`, `job=lambda: None`
- **FR#2** `test_utils/factories.py` exports `make_mock_executor()` — returns a `MagicMock` with `execute = AsyncMock()`. Replaces 4 byte-identical local definitions (`test_bus_service_timeout.py`, `test_bus_service_error_handler.py`, `test_invocation.py`, `test_duration_hold.py`). Two additional `make_executor` definitions in `test_loop_watchdog.py` and `test_protect_loop_monkeypatch.py` build `ExecutionMarker`-based mocks with different attributes and are not subsumed — they stay local with `# factory-local:` annotations
- **FR#3** `test_utils/factories.py` exports `make_mock_event()` — returns `MagicMock(spec=Event)`
- **FR#4** `test_utils/factories.py` exports `make_recording_api(states=None)` — returns a `RecordingApi` wired to a `make_mock_hassette(sealed=False)` with `state_registry = STATE_REGISTRY` and an `AsyncMock(spec=StateProxy)` whose `.states` is `states or {}` and `.is_ready` returns `True`
- **FR#5** `test_utils/factories.py` exports `make_hassette_event(topic="hassette.ready", data=None)` — returns `Event(topic=topic, payload=HassettePayload(data=data))`
- **FR#6** `test_utils/factories.py` exports `make_mock_parent(app_key="test_app", index=0, ...)` — returns a `MagicMock` with `app_key`, `index`, `unique_name`, `source_tier`, `class_name`, and `app_config` attributes. Replaces the canonical definition in `tests/unit/conftest.py` plus 3 inline `Mock()`/`MagicMock()` assignments (`tests/unit/bus/conftest.py`, `tests/unit/scheduler/conftest.py`, `tests/unit/bus/test_bus_timeout_threading.py`) and 1 full `def make_mock_parent(*)` factory in `tests/unit/test_scheduler_resource.py:17`. Additionally, `tests/unit/test_forgotten_await_completeness.py:33` imports `make_mock_parent` from `tests/unit/conftest` as a plain function and must update its import to the shared factory. Inline `mock_parent = Mock()` constructions with the same field set exist in `tests/integration/bus/test_execution_modes.py:521` and `tests/unit/test_source_tier_propagation.py:74,:137` — these are inline (not `def`s) and won't be caught by the linter, but should be migrated to use the shared factory during the caller migration
- **FR#7** All local definitions that are subsumed by FR#1-6 are deleted and replaced with imports from the shared factory
- **FR#8** The 13 dead test app files in `tests/data/apps/` are deleted (already done on this branch — verified by test suite)
- **FR#9** Dead exports are removed: `emit_service_event()` from `helpers.py` (and its re-export from `_internal/__init__.py` and `__init__.py`), `make_listener_metric()` and `setup_registry()` from `web_helpers.py` (and their re-exports). `hassette_with_nothing` fixture is deleted from `fixtures.py` (it is NOT in `__all__` or re-exported — it's registered via `pytest_plugins` in `tests/conftest.py`). The dangling `"hassette_with_nothing"` string in `_HARNESS_FIXTURES` (`tests/integration/conftest.py`) and its reference in `TESTING.md:119-123` are also removed. Note: `mock_transport_builder` fixture was already removed from `cli/conftest.py` by the clean code sweep (commit `05912d8d`)
- **FR#10** Dead bare `@pytest.mark.asyncio` markers are removed from `tests/unit/core/test_logging_service.py` (13 markers) where `asyncio_mode = "auto"` makes them no-ops. Note: 5 other files use `@pytest.mark.asyncio(loop_scope="function")` which overrides the default `asyncio_default_test_loop_scope = "session"` — these are functionally significant and are not removed
- **FR#11** `app`, `client`, and `runtime_query_service` fixtures move from `tests/integration/conftest.py` to `tests/integration/web_api/conftest.py` (their sole dependency `mock_hassette` exists only there)
- **FR#12** `noop()` moves from `tests/unit/scheduler/conftest.py` to `test_utils/helpers.py`, replacing the existing unused sync `def noop() -> None: pass` (zero callers) with the async version `async def noop() -> None: pass`. Migrates 21 total reimplementations: `tests/unit/test_scheduler_resource.py:76` (module-level), `tests/unit/test_scheduled_job.py:31` (module-level), `tests/unit/test_task_bucket.py:179` (nested), `tests/integration/database/test_database_service.py:429` (nested), and `tests/integration/test_scheduler_mode.py` (17 nested copies, one per test method). Additionally, 7 files in `tests/unit/scheduler/` import `noop` from `conftest.py` as a plain function (not a fixture) and must update their import path: `test_scheduled_job_mark_registered.py`, `test_scheduled_job_timeout.py`, `test_scheduled_job_lifecycle.py`, `test_scheduler_error_handler.py`, `test_scheduler_timeout_threading.py`, `test_scheduler_coroutine_conversion.py`, `test_scheduler_where.py`. Note: `tests/unit/core/test_database_service.py:237` defines `async def noop_coro()` — a different name, not in migration scope
- **FR#13** `tests/unit/conftest.py::make_test_config` is renamed to `make_sync_executor_config` (collides with the public `test_utils.config.make_test_config`). Consumer `tests/unit/test_sync_executor_service_wiring.py` imports and calls this function (lines 33, 188, 216, 228) and must be updated in the same commit
- **FR#14** The `hassette_with_bus` override in `tests/unit/bus/conftest.py` gets a docstring explaining the intentional scope/type change, following the pattern of `telemetry/conftest.py::db_hassette`
- **FR#15** `web_helpers.py::make_manifest()` gains an `autostart` parameter, and the local duplicate in `tests/unit/web/test_mappers.py:144` is deleted
- **FR#16** `.claude/rules/test-conventions.md` names the canonical test infrastructure, links the decision table, and includes an explicit prohibition against defining local `make_*` functions without checking shared factories first
- **FR#17** CLAUDE.md files in `tests/unit/bus/`, `tests/unit/core/`, `tests/integration/bus/`, `tests/integration/web_api/`, and `tests/integration/telemetry/` list the module-specific fixtures and helpers available in those directories
- **FR#18** `tools/check_test_factories.py` is a pre-commit linter that flags local `def make_*`/`def build_*` definitions in test files when a shared factory with a matching name exists in the registry
- **FR#19** TESTING.md is updated to remove references to deleted items (`make_listener_metric`, `setup_registry`, `hassette_with_nothing`), remove the dangling `hassette_with_nothing` entry from the `_HARNESS_FIXTURES` list documentation and update the fixture count from "8 module-scoped" to "7 module-scoped", add the `make_*/create_*/build_*` naming convention, add a "Before writing a new factory" checklist, and update the factory inventory with the 6 new factories. (The "Choosing a Mock Strategy" decision rule already exists at TESTING.md:27-37 and needs no changes.)
- **FR#20** `tests/data/events/device_tracker_event.json` is deleted (wrong format, zero references)

## Edge Cases

- **Local factory with same name but different return type**: `make_job` in `test_scheduler_service_error_handler.py` returns a `MagicMock` — this is legitimately different from the shared `make_scheduled_job()` which returns a real `ScheduledJob`. The linter must support an exemption mechanism for these cases.
- **Local factory that's a strict subset**: `make_hassette_event()` in `test_event_filter.py` takes no args while the shared version takes `topic` and `data`. The zero-arg call `make_hassette_event()` must continue to work with the shared version's defaults.
- **`make_real_job` already exists in `web_helpers.py`**: Its signature overlaps with the new `make_scheduled_job`. Both are needed — `make_real_job` serves web-layer tests with web-specific defaults (`app_key`, `instance_index`), while `make_scheduled_job` serves unit tests with scheduler-specific defaults (`timeout`, `error_handler`, `mode`). Document the distinction in TESTING.md's factory guide.
- **Two local `make_manifest()` returning `AppManifest` (not `AppManifestInfo`)**: `tests/integration/test_app_factory_lifecycle.py:53` and `tests/unit/test_config_classes.py:14` both build `AppManifest` (the config-layer registration model), a legitimately different type from `web_helpers.make_manifest()` which returns `AppManifestInfo` (the runtime snapshot model). These are not consolidated by FR#15 — they build a different type and are intentionally left local. The TESTING.md naming convention section should note this distinction.
- **`make_mock_parent()` has 4 distinct field-set shapes**: (1) full 6-field `def` in `tests/unit/conftest.py` (`app_key`, `index`, `unique_name`, `source_tier`, `class_name`, `app_config`); (2) 5-field inline in `bus/conftest.py` and `test_execution_modes.py` (omits `app_config`); (3) 4-field in `scheduler/conftest.py`, `test_bus_timeout_threading.py`, and `test_scheduler_resource.py` def (`app_key`, `index`, `source_tier`, `class_name` — omits both `unique_name` and `app_config`); (4) `test_source_tier_propagation.py:74,:137` includes `unique_name` but omits `class_name` — the inverse omission from shape 3. The shared factory includes all fields with defaults — callers that didn't set those fields get harmless extra attributes.
- **`make_event()` has 2 legitimately-different local variants**: `test_duration_timer.py` (plain `MagicMock`, no `spec=Event`) and `test_service_data_predicates.py` (takes `service_data` arg, returns `SimpleNamespace`). These are not subsumed by `make_mock_event()` and should stay local with `# factory-local:` annotations.
- **Pre-existing shared `make_job()` in `web_helpers.py`**: A third meaning of `make_job` (returns `SimpleNamespace` for web serialization) already exists as a shared export alongside `make_real_job()`. The new `make_scheduled_job()` is a fourth factory for the same concept. The naming convention in TESTING.md must distinguish all three: `make_scheduled_job` (unit tests), `make_real_job` (web behavior tests), `make_job` (web serialization duck-types).
- **Linter false positives for legitimately local factories**: A test file defining `make_special_widget()` that has no shared counterpart should not be flagged. The linter matches against a registry of known shared factory names, not a blanket ban on `make_*`.
- **Additional `make_manifest` variants the linter would flag**: `tests/unit/core/test_app_change_detector.py:102` (fixture factory returning `Callable`) and `tests/unit/core/test_app_registry.py:510` (class method returning `SimpleNamespace`) both define `make_manifest` at function scope. These have clearly distinct signatures and should be exempted with `# factory-local:` annotations. The linter's AST traversal matches `ast.FunctionDef` nodes, which includes nested defs and class methods — the exemption mechanism handles these cases.

## Acceptance Criteria

- **AC#1** `grep -rn "def make_job\b" tests/` returns exactly 2 results: the legitimately distinct MagicMock-based local variant in `test_scheduler_service_error_handler.py` plus the unrelated nested `make_job(label, signal)` in `tests/integration/test_scheduler.py:172` (returns a callable, not a `ScheduledJob` — not in consolidation scope). The 9 real-`ScheduledJob` variants that existed before are gone. (FR#1, FR#7)
- **AC#2** `grep -rn "def make_event\b" tests/` returns zero results for the 4 byte-identical `MagicMock(spec=Event)` definitions; legitimately-different variants (`test_duration_timer.py` — no spec; `test_service_data_predicates.py` — `SimpleNamespace` with `service_data`) may remain with `# factory-local:` annotations (FR#3, FR#7)
- **AC#3** `grep -rn "def make_executor\b" tests/` returns exactly 4 results: the 2 real-`CommandExecutor` builders (`tests/unit/core/conftest.py` and `tests/unit/core/test_command_executor_pipeline.py`) plus 2 legitimately-different `MagicMock` builders in `tests/unit/core/test_loop_watchdog.py` and `tests/unit/core/test_protect_loop_monkeypatch.py` (these build `ExecutionMarker`-based mocks, not `execute=AsyncMock()` pattern — exempt with `# factory-local:`). The 4 identical `execute=AsyncMock()` mock versions are gone. (FR#2, FR#7)
- **AC#4** `ls tests/data/apps/` shows exactly 6 `.py` files: `disabled_app.py`, `failing_init_app.py`, `multi_instance_app.py`, `my_app.py`, `my_app_sync.py`, `no_autostart_app.py` (no `__init__.py` — the directory has never had one) (FR#8)
- **AC#5** `grep -rn "emit_service_event\|make_listener_metric\|setup_registry\|hassette_with_nothing" src/hassette/test_utils/` returns zero results (`mock_transport_builder` already removed by clean code sweep) (FR#9)
- **AC#6** `grep -rn "pytest.mark.asyncio" tests/unit/core/test_logging_service.py` returns zero results (FR#10)
- **AC#7** `grep -rn "def app\b\|def client\b\|def runtime_query_service\b" tests/integration/conftest.py` returns zero results — all three moved to `web_api/conftest.py` (FR#11)
- **AC#8** `.claude/rules/test-conventions.md` exists and names at least the 10 most-used test_utils symbols with import paths (FR#16)
- **AC#9** `tools/check_test_factories.py` runs successfully as a pre-commit hook and reports zero violations after the factory consolidation is complete (FR#18)
- **AC#10** `uv run nox -s dev` passes with zero regressions from the baseline (all FRs)
- **AC#11** TESTING.md contains a `make_*/create_*/build_*` naming convention section and a "Before writing a new factory" checklist (FR#19)

## Key Constraints

- New factories in `factories.py` must follow the existing style: keyword-only args, every field has a default, imports shared constants from `test_utils.config` where applicable.
- The linter must follow the pattern of existing pre-commit `tools/check_*.py` scripts (`check_lazy_imports.py`, `check_llm_cruft.py`, `check_module_boundaries.py`) — AST-based or regex-based, `sys.exit(1)` on failure, wired into `.pre-commit-config.yaml`. Do not use `check_internal_patches.py` as the exemplar — it is CI-only, not pre-commit.
- Factory renames (`make_test_config` → `make_sync_executor_config`) must update all import sites in the same commit — no parallel old/new paths.
- CLAUDE.md files in test directories must stay under 20 lines each — module-specific pointers only, universal guidance lives in the rule file.

## Dependencies and Assumptions

- The 13 dead test app deletions are already committed on this branch. The design assumes the test suite passes without them (verified: 8662 passed, 0 failures related to deletions).
- `web_helpers.py::make_real_job()` continues to exist alongside the new `make_scheduled_job()` — they serve different test layers.
- The pre-commit framework is already configured in `.pre-commit-config.yaml` with an established pattern for `tools/check_*.py` hooks.

## Architecture

### Factory consolidation

Add 6 factories to `src/hassette/test_utils/factories.py`, following the existing keyword-only style with sensible defaults. Each factory replaces specific local duplicates:

| New factory | Returns | Replaces | Migration count |
|---|---|---|---|
| `make_scheduled_job(**kw)` | `ScheduledJob` | 9 local `make_job()` that build real `ScheduledJob`s | 9 files |
| `make_mock_executor()` | `MagicMock` | 4 byte-identical `make_executor()` (2 additional `ExecutionMarker`-based variants stay local) | 4 files |
| `make_mock_event()` | `MagicMock(spec=Event)` | 4 functionally-identical `make_event()` | 4 files |
| `make_recording_api(states=None)` | `RecordingApi` | 3 near-identical factories | 3 files |
| `make_hassette_event(topic, data)` | `Event` | 2 byte-identical factories | 2 files |
| `make_mock_parent(**kw)` | `MagicMock` | 2 `def` variants (`conftest.py`, `test_scheduler_resource.py`) + 3 inline `Mock()`/`MagicMock()` assignments (`bus/conftest.py`, `scheduler/conftest.py`, `bus/test_bus_timeout_threading.py`) + 3 additional inline constructions | 8 sites across 7 files |

Factories that return real objects (`make_scheduled_job`, `make_hassette_event`) use the `make_` prefix. Factories that return mocks (`make_mock_executor`, `make_mock_event`, `make_mock_parent`) use the `make_mock_` prefix. `make_recording_api` returns a real object wired to mocks — `make_` prefix because the return type is the real `RecordingApi`. This naming convention is documented in TESTING.md.

The 2 `make_job` definitions that return `MagicMock` (not real `ScheduledJob`) remain local — they intentionally avoid constructing a real object and are not subsumed by the shared factory. Note that `web_helpers.py` already exports a shared `make_job()` (returns `SimpleNamespace` for web serialization tests) and `make_real_job()` (returns real `ScheduledJob` for web-layer behavior tests) — these are a third and fourth meaning of "make job" and must be documented in TESTING.md's factory guide alongside the new `make_scheduled_job()`. The naming convention section should clarify: `make_scheduled_job()` for unit/scheduler tests, `make_real_job()` for web-layer behavior tests, `make_job()` (web_helpers) for serialization duck-types.

### Linter design

`tools/check_test_factories.py` follows the pre-commit linter pattern used by `check_lazy_imports.py`, `check_llm_cruft.py`, and `check_module_boundaries.py` (all wired into `.pre-commit-config.yaml`). Note: `check_internal_patches.py` is a CI-only lint (`.github/workflows/lint.yml`), not a pre-commit hook — do not use it as the wiring exemplar:

1. Maintains a `SHARED_FACTORIES` registry mapping factory names to their import paths (e.g., `{"make_scheduled_job": "hassette.test_utils.factories", "make_mock_event": "hassette.test_utils.factories", ...}`)
2. Scans test files via AST for `ast.FunctionDef` nodes whose name matches a key in the registry — **a name match alone triggers a violation** (this is the primary detection: an LLM creating a new duplicate won't have an import to check against)
3. Checks whether the file also imports the shared version — if it does, the violation message notes the shadow explicitly; if not, the message suggests the import path
4. Supports a `# factory-local: <reason>` annotation on the `def` line to exempt legitimately local factories that share a name with a registry entry (e.g., a `make_job()` returning `MagicMock` instead of `ScheduledJob`)
5. Reports violations with the message: `"Local 'make_foo()' shadows shared factory — use 'from hassette.test_utils.factories import make_foo'"`
6. Exits 0 on clean, 1 on violations

The registry is a flat dict in the linter source — no external config file. Adding a new shared factory means adding one line to the registry.

### Rule file design

`.claude/rules/test-conventions.md` is loaded on every session. Content:

- Names the canonical factories in `test_utils/factories.py` and `test_utils/helpers.py` with import paths
- Links directly to the TESTING.md decision table (one hop, not two)
- Explicit prohibition: "Before defining a local `make_*` or `build_*` function in a test file, check `test_utils/factories.py` and `test_utils/helpers.py` for an existing factory"
- Names the `make_mock_hassette()` vs `create_hassette_stub()` decision rule inline (3-4 lines)
- Lists the 10 most-used test_utils symbols

### Test directory CLAUDE.md files

Each under 20 lines. Structure:

```markdown
# Tests: <module>

## Available fixtures (this directory's conftest.py)
- `fixture_name` — what it provides

## Shared helpers
- `from helpers import func` — what it does

## Key conventions
- One-liner about the module-specific testing pattern
```

5 directories get CLAUDE.md files: `tests/unit/bus/`, `tests/unit/core/`, `tests/integration/bus/`, `tests/integration/web_api/`, `tests/integration/telemetry/`.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions. The linter follows the pre-commit `tools/check_*.py` pattern (`check_lazy_imports.py`, `check_llm_cruft.py`, `check_module_boundaries.py`). Factories follow `factories.py`'s existing style.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| 9 local `make_job()` returning `ScheduledJob` | `make_scheduled_job()` in `factories.py` | Delete local definitions, add imports |
| 4 local `make_executor()` (4 identical mock, 2 different stay local) | `make_mock_executor()` in `factories.py` | Delete 4 identical mock definitions, add imports; exempt 2 `ExecutionMarker`-based variants |
| 4 local `make_event()` | `make_mock_event()` in `factories.py` | Delete local definitions, add imports |
| 3 local `make_recording_api()` | `make_recording_api()` in `factories.py` | Delete local definitions, add imports |
| 2 local `make_hassette_event()` | `make_hassette_event()` in `factories.py` | Delete local definitions, add imports |
| 2 `def make_mock_parent()` + 3 inline `Mock()`/`MagicMock()` assignments + 3 inline constructions | `make_mock_parent()` in `factories.py` | Delete 2 local defs, replace 6 inline constructions with factory call |
| Local `make_invoke_handler_cmd` in `test_command_executor_execution_id.py` | Existing shared `make_invoke_handler_cmd` in `factories.py` | Delete local, add import |
| Local `make_manifest` in `test_mappers.py` | Extended `make_manifest()` in `web_helpers.py` (add `autostart` param) | Delete local, update shared |

## Convention Examples

### Existing factory style (keyword-only, defaults, real return type)

**Source:** `src/hassette/test_utils/factories.py`

```python
def make_listener_registration(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    handler_method: str = "test_app.on_event",
    topic: str = "hass.event.state_changed",
    source_tier: SourceTier = "app",
) -> ListenerRegistration:
    return ListenerRegistration(
        app_key=app_key, instance_index=instance_index, ...
    )
```

### Mock factory style (no args, descriptive docstring)

**Source:** `src/hassette/test_utils/factories.py`

```python
def make_invoke_handler_cmd(
    *,
    source_tier: SourceTier = "app",
    listener_id: int = 1,
    topic: str = "test/topic",
    listener: Any | None = None,
    event: Any | None = None,
) -> MagicMock:
    """Build a MagicMock spec'd to InvokeHandler with an invocable listener."""
    cmd = MagicMock(spec=InvokeHandler)
    cmd.source_tier = source_tier
    ...
    return cmd
```

### Pre-commit linter pattern (AST-based, sys.exit)

**Source:** `tools/check_lazy_imports.py` (pre-commit hook exemplar)

```python
#!/usr/bin/env python3
"""Pre-commit hook: detect lazy imports in src/hassette/."""
# ... AST scanning, sys.exit(1) on violations, wired into .pre-commit-config.yaml
```

### Fixture override documentation pattern

**Source:** `tests/integration/telemetry/conftest.py`

```python
@pytest.fixture
def db_hassette(premigrated_db_path, ...) -> Hassette:
    """Override of tests/integration/conftest.py::db_hassette.

    Adds web_api={"run": True} so telemetry endpoints are reachable.
    """
```

## Alternatives Considered

### Do nothing (instruction-only approach)

Add a `.claude/rules/test-conventions.md` and CLAUDE.md files without factory consolidation or linting. The prior art research shows this reduces but cannot prevent duplication — "The AI can drift, but the tooling cannot." Rejected because the existing ~130 local factories would remain, and new ones would continue to accumulate across sessions.

### Scaffold-first approach (MCP template generation)

Generate test files from templates that include the correct imports. The prior art research (AgiFlow's scaffold-mcp) shows this works well for uniform test patterns. Rejected because hassette's test patterns are too diverse for a single template — the lint-rule approach is more surgical.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/test_make_test_config.py` — verify it still imports from the correct location after the `make_test_config` rename in `tests/unit/conftest.py`
- Any test file whose local factory is being replaced — verify the import path change doesn't break fixture resolution

### New Test Coverage

- **FR#18**: `tests/unit/tools/test_check_test_factories.py` — unit tests for the new linter: positive case (local factory shadows shared → violation), negative case (local factory with no shared counterpart → clean), exemption annotation case (`# factory-local:` → clean)

### Tests to Remove

No tests to remove.

## Documentation Updates

- **TESTING.md**: Remove references to `make_listener_metric`, `setup_registry`, `hassette_with_nothing`. Add "Choosing a Mock Strategy" decision rule. Add `make_*/create_*/build_*` naming convention. Add "Before writing a new factory" checklist. Update factory inventory with the 6 new factories.
- **CLAUDE.md** (root): No changes needed — it already points to TESTING.md correctly.
- **.claude/rules/test-conventions.md**: New file (FR#16).
- **5 test directory CLAUDE.md files**: New files (FR#17).

## Impact

### Changed Files

- **create** `.claude/rules/test-conventions.md`
- **create** `tools/check_test_factories.py`
- **create** `tests/unit/tools/test_check_test_factories.py`
- **create** `tests/unit/bus/CLAUDE.md`
- **create** `tests/unit/core/CLAUDE.md`
- **create** `tests/integration/bus/CLAUDE.md`
- **create** `tests/integration/web_api/CLAUDE.md`
- **create** `tests/integration/telemetry/CLAUDE.md`
- **modify** `src/hassette/test_utils/factories.py` — add 6 factories
- **modify** `src/hassette/test_utils/__init__.py` — update exports for new factories
- **modify** `src/hassette/test_utils/_internal/__init__.py` — update re-exports
- **modify** `src/hassette/test_utils/helpers.py` — delete `emit_service_event`, replace sync `noop` with async `noop`
- **modify** `src/hassette/test_utils/web_helpers.py` — delete `make_listener_metric` and `setup_registry`, add `autostart` param to `make_manifest`
- **modify** `src/hassette/test_utils/fixtures.py` — delete `hassette_with_nothing`
- **modify** `tests/TESTING.md` — decision rules, naming convention, factory checklist
- **modify** `tests/integration/conftest.py` — remove `app`, `client`, `runtime_query_service`
- **modify** `tests/integration/web_api/conftest.py` — receive `app`, `client`, `runtime_query_service`
- **modify** `tests/unit/conftest.py` — rename `make_test_config` → `make_sync_executor_config`, delete `make_mock_parent` (moved to factories.py)
- **modify** `tests/unit/bus/conftest.py` — add docstring to `hassette_with_bus` override, use shared `make_mock_parent`
- **modify** `tests/unit/scheduler/conftest.py` — delete `noop` (moved), use shared `make_mock_parent` in `make_scheduler`
- **modify** `.pre-commit-config.yaml` — add `check_test_factories.py` hook
- **modify** ~43 unique test files — replace local factory definitions with imports from shared factories, update import paths for moved/renamed functions (deduplicated: some files need multiple factories replaced; includes 7 `noop` import-path updates in `tests/unit/scheduler/`, 5 files with local `noop()` reimplementations, `test_sync_executor_service_wiring.py` for the `make_test_config` rename, and `test_forgotten_await_completeness.py` for the `make_mock_parent` import)
- **delete** `tests/data/events/device_tracker_event.json`
- **delete** 13 test app files in `tests/data/apps/` (already done)

### Behavioral Invariants

- All currently-passing tests must continue to pass with zero regressions
- `hassette.test_utils.__all__` (Tier 1 public API) must not lose any existing exports
- Existing callers of `web_helpers.make_manifest()` must not break when the `autostart` parameter is added (it has a default)

### Blast Radius

Factory consolidation touches ~43 unique test files but each change is mechanical (delete local `def`, add `from hassette.test_utils.factories import ...`). No production code is modified. The linter and rule file are additive. Risk is low.

## Open Questions

None — all decisions resolved during discovery.
