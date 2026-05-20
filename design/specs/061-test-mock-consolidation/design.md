# Design: Test Mock Consolidation

**Date:** 2026-05-19
**Status:** approved
**Scope-mode:** hold
**Research:** /tmp/claude-test-cleanup-audit-zf9eWW/research-brief.md, /tmp/claude-test-cleanup-audit-XDFQQ8/research-brief.md

## Problem

~15 test files define their own factory functions for constructing mock hassette objects, with ~7 more importing those factories — ~22 files total involved in the pattern. Each factory manually sets 3–25 configuration attributes on mock objects, resulting in ~250 lines of duplicated factory definitions across the 15 definition sites. These factories have drifted — identical fields carry different values across files, and new configuration fields require updating every factory individually. There is no single authoritative pattern for test hassette construction outside of the harness-based integration tests, despite a well-designed hermetic configuration factory already existing in the shared test utilities.

The cost is threefold:
1. **Maintenance burden** — every new configuration field potentially requires edits across all 15 factory definition sites
2. **Drift** — factories silently diverge (e.g., one file sets a queue size to 500 while another sets 1000), meaning tests run against inconsistent configuration shapes
3. **Onboarding friction** — new contributors copy-paste from whichever test file they find first, perpetuating the fragmentation

## Goals

- Zero local hassette mock factories — all test files use the shared factory
- Adding a configuration field requires updating at most one file (the shared factory's defaults)
- Net reduction in test code line count
- Test configuration is validated by the real configuration model, eliminating silent drift from invalid or inconsistent field values
- Clear naming convention distinguishes database-backed fixtures from lightweight stubs

## Non-Goals

- Modifying `create_hassette_stub()` (web/API mock factory) — separate follow-up
- Changing test assertions or test function names
- Improving test coverage or adding new tests
- Relocating Docker test files or merging duplicate telemetry model tests
- Addressing `caplog` test usage (tracked in #473)
- Promoting `bus_test_helpers.py` to shared utilities
- Migrating `test_hassette_timeout_warning.py` — it uses `object.__new__(Hassette)` to bypass `__init__` and test real methods on partially-wired objects; `make_mock_hassette()` is the wrong tool for this pattern

## User Scenarios

### Developer: framework contributor
- **Goal:** add a new configuration field to hassette
- **Context:** modifying the configuration model and needs tests to pass

#### Adding a new config field

1. **Add the field to the configuration model**
   - Sees: the config model with existing fields
   - Decides: field name, type, and default value
   - Then: all test factories automatically inherit the new default via the real configuration model — no test files need updating

#### Writing a new test that needs a hassette mock

1. **Import the shared factory**
   - Sees: one factory function in `test_utils` with clear documentation
   - Decides: which overrides (if any) the test needs
   - Then: gets a fully-wired mock hassette with validated configuration in 1–3 lines

### Developer: app author writing tests
- **Goal:** test a custom hassette app
- **Context:** using the public test utilities to set up a mock hassette

#### Setting up a mock for app testing

1. **Call the shared factory with app-specific overrides**
   - Sees: factory accepts keyword overrides for any configuration field
   - Decides: which fields to customize for the test scenario
   - Then: gets a mock hassette with real configuration defaults plus their overrides

#### Passing an invalid config override

1. **Call the factory with a bad value**
   - Sees: a validation error from the configuration model at construction time, with the invalid field and value in the traceback
   - Decides: fix the override value to match the configuration model's type constraints
   - Then: the factory succeeds with the corrected value

#### Accessing a non-existent config field after migration

1. **Run a test that previously relied on auto-vivified mock attributes**
   - Sees: an `AttributeError` on the real configuration object (instead of the silent `MagicMock` auto-vivification that returned a mock)
   - Decides: the test was relying on a phantom field — either the field name is wrong or the test's assumption about config structure is outdated
   - Then: fixes the field reference or adds the field as an explicit override

## Functional Requirements

- **FR#1** A shared factory function produces a mock hassette object with real, validated configuration and mock non-configuration attributes
- **FR#2** The factory accepts keyword overrides for any configuration field, merged on top of test-appropriate defaults
- **FR#3** The factory sets standard non-configuration attributes (readiness signals, shutdown signals, thread identity, event loop reference, service stubs) so callers don't need to wire them manually
- **FR#4** A shared database-initialization fixture creates a database service and session row, yielding the service and session identifier
- **FR#5** The session-scoped database template fixture uses validated configuration instead of manually-set mock attributes
- **FR#6** No test file outside `test_utils` defines its own hassette mock factory function
- **FR#7** Database-backed hassette fixtures use a distinct name from lightweight stubs to prevent naming confusion
- **FR#8** Dead fixtures that are defined but never consumed by any test are removed

## Edge Cases

- **Session-scoped fixtures** — the factory needs to work without `tmp_path` (which is function-scoped). Session-scoped callers must use `tmp_path_factory.mktemp()` and pass the result as `data_dir`.
- **Tests that mutate config mid-test** — rare (3 in-scope files: `test_app_lifecycle_service.py`, `test_database_service.py` [unit], `test_command_executor.py`), but if a test modifies `hassette.config.X` after construction, the real configuration model raises a validation error (frozen model). These tests must pass the desired value as a `config_overrides` parameter at construction time instead of mutating post-construction. **Pre-migration audit required:** grep for all `hassette.config.*` and `executor.hassette.config.*` mutation sites, extract the assigned values, and cross-reference against `ge`/`le`/`gt`/`lt` constraints in `src/hassette/config/models.py`. Tests that require values outside Pydantic constraint ranges (e.g., `queue_max=0` below `ge=1`) must retain a mock config layer for that specific field or the constraint must be relaxed.
- **Tests that assert `config.reload()` was called** — with real config, `reload()` would actually execute. These need `hassette.config.reload = Mock()` patched on top.
- **`config_dir` directory creation** — `HassetteConfig` validators create the `config_dir` directory during construction. The hermetic factory already handles this, but tests should verify no stale directories leak between runs.
- **Accessing unlisted attributes on the mock** — the factory calls `seal(hassette)` after wiring all known attributes, so accessing an attribute not explicitly set by the factory raises `AttributeError`. This catches tests that relied on auto-vivified phantom attributes. Tests that need additional attributes must pass `sealed=False`, set their extras, and optionally seal the mock themselves.

## Acceptance Criteria

- **AC#1** All test files use the shared factory; `grep -r '_make_hassette_stub\|_make_mock_hassette\|_make_hassette_mock\|_make_ws_hassette_stub' tests/` returns zero results AND no inline `mock_hassette` fixture outside `test_utils` or `e2e/` manually sets `.config.` attributes on a `MagicMock` (FR#6)
- **AC#2** The `initialized_db` fixture exists in exactly one location (`tests/integration/conftest.py`) and is not duplicated in any test file (FR#4)
- **AC#3** Adding a new field with a default to any configuration model subgroup requires zero test file changes — only the configuration model default is needed. Fields without defaults require updating `make_test_config()` only (FR#1, FR#2)
- **AC#4** The full test suite passes with no regressions (`uv run nox -s dev -- -n 2`)
- **AC#5** Net reduction in test code lines (measured by `git diff --stat` against the branch point)
- **AC#6** The 5 dead root-level fixtures (`test_data_path`, `test_config_path`, `test_events_path`, `test_api_responses_path`, `test_apps_path`) are removed from `tests/conftest.py` (FR#8)
- **AC#7** Database-backed integration test fixtures use a name distinct from `mock_hassette` (FR#7)
- **AC#8** `make_ws_hassette_stub()` is exported from `hassette.test_utils` and used by both WebSocket test files (FR#1)

## Key Constraints

- The shared factory must not introduce import-time side effects — constructing `HassetteConfig` via `make_test_config()` creates directories for both `data_dir` and `config_dir`, so both must be scoped to test-provided paths. The factory defaults `config_dir` to `data_dir / "config"` to prevent writes to the developer's system directory (`~/.config/hassette/v0`).
- Tests that currently work with `MagicMock` config (where any attribute access silently succeeds) may break when switched to real config (where accessing a non-existent field raises `AttributeError`). This is intentional — it surfaces tests that relied on phantom config fields — but each failure must be investigated, not blindly suppressed.
- The `_migrated_db_template` fixture is session-scoped and runs outside an async event loop. It currently uses `asyncio.new_event_loop()` manually. The factory must work in this context (no `asyncio.get_running_loop()` dependency for config construction).

## Dependencies and Assumptions

- `make_test_config()` in `src/hassette/test_utils/config.py` is stable and correctly produces hermetic configuration. Its shared mutable cell must be protected with a `threading.Lock` before this migration promotes it to canonical usage — currently safe for async-only but not for OS threads
- The existing test suite is green on the branch before migration begins
- `create_hassette_stub()` consumers (web/API/e2e tests) are not affected by this change — they continue using their own factory

## Architecture

### New factory: `make_mock_hassette()`

Location: `src/hassette/test_utils/mock_hassette.py`

The factory combines `make_test_config()` for validated configuration with an `AsyncMock` shell for non-configuration attributes. It accepts two categories of parameters:

1. **Config overrides** — passed through to `make_test_config()` as keyword arguments
2. **Behavioral flags** — control non-config mock wiring (e.g., `set_ready=True`, `set_loop=True`)

```python
def make_mock_hassette(
    *,
    data_dir: Path | str | None = None,
    set_ready: bool = True,
    set_loop: bool = True,
    sealed: bool = True,
    **config_overrides: Any,
) -> AsyncMock:
```

When `data_dir` is `None`, the factory generates a temporary directory via `tempfile.mkdtemp()`. This is the default for unit tests that don't care about the directory. Integration tests that need DB isolation pass `tmp_path` or `tmp_path_factory.mktemp()`.

**Trade-offs of this approach:**
- Real config validation catches invalid field combinations early, but also means tests fail faster on typos — a net positive, but developers see Pydantic `ValidationError` tracebacks instead of silent mock passes
- `tempfile.mkdtemp()` default avoids requiring `tmp_path` in every unit test, but leaked tempdirs accumulate if tests crash before cleanup. Acceptable for test infra; pytest's `tmp_path` is preferred for integration tests where directory lifecycle matters
- `seal()` prevents phantom attribute access but adds friction for tests that need extra attributes — they must pass `sealed=False` and wire attributes manually. This friction is intentional: it forces explicit declaration of test dependencies

Non-configuration attributes wired by default:
- `hassette.ready_event` — `asyncio.Event()`, set if `set_ready=True`
- `hassette.shutdown_event` — `asyncio.Event()`, not set
- `hassette.event_streams_closed` — `False`
- `hassette._loop_thread_id` — `threading.get_ident()`
- `hassette.loop` — `asyncio.get_running_loop()` if `set_loop=True`, else `None`
- `hassette._scheduler_service.register_removal_callback` — `Mock()`
- `hassette._scheduler_service.deregister_removal_callback` — `Mock()`
- `hassette._bus_service.remove_listeners_by_owner` — `Mock()`
- `hassette._bus_service.get_listeners_by_owner` — `Mock(return_value=[])`
- `hassette.session_id` — `None` (set by `initialized_db` after DB setup)
- `hassette.database_service` — `None` (set by `initialized_db` after DB setup)
- `hassette.wait_for_ready` — `AsyncMock(return_value=True)`
- `hassette.children` — `[]`

After wiring all attributes, the factory calls `seal(hassette)` (`unittest.mock.seal`) to prevent further attribute auto-vivification. Accessing an attribute not set by the factory raises `AttributeError`. Tests that need additional attributes beyond the defaults pass `sealed=False`, set their extras, and optionally seal the mock themselves.

### Consolidated `initialized_db` fixture

Location: `tests/integration/conftest.py`

Extracted from the 4 duplicate definitions. Depends on `premigrated_db_path` (already in integration conftest) and a `db_hassette` fixture that uses `make_mock_hassette()`. The factory's defaults include all fields needed by all 4 current consumers (`bus_excluded_domains`, `bus_excluded_entities`, event-logging booleans, etc.) so no per-file overrides are needed for the common case. Tests that need different values (e.g., `telemetry_write_queue_max=500`) override at their call site.

### `_migrated_db_template` update

The existing session-scoped fixture in `tests/integration/conftest.py` replaces its 14-line MagicMock config block with a `make_mock_hassette()` call that preserves the template's intentional overrides:

```python
mock = make_mock_hassette(
    data_dir=tmpl_dir,
    set_loop=False,
    database={"max_size_mb": 0, "telemetry_write_queue_max": 500},
    lifecycle={"resource_shutdown_timeout_seconds": 5},
    web_api={"run": True},
)
```

`set_loop=False` prevents the `get_running_loop()` call since this runs outside an event loop. Four values differ from `make_test_config()` defaults and must be preserved as explicit overrides:

- `database.max_size_mb=0` — disables size failsafe (default: 500)
- `database.telemetry_write_queue_max=500` — smaller queue for tests (default: 1000)
- `lifecycle.resource_shutdown_timeout_seconds=5` — faster shutdown (default: 10)
- `web_api.run=True` — `make_test_config()` defaults this to `False`

The remaining 11 values in the original fixture (`retention_days`, `write_queue_max`, `migration_timeout_seconds`, logging levels, etc.) all match model or `make_test_config()` defaults and are safely omitted.

### Fixture naming

Database-backed integration test fixtures that use `premigrated_db_path` will be named `db_hassette` instead of `mock_hassette`. Lightweight unit test fixtures keep the name `mock_hassette` or use inline `make_mock_hassette()` calls. This distinguishes the two patterns at grep time.

### Dead fixture removal

Remove from `tests/conftest.py`:
- `test_data_path` (line 175)
- `test_config_path` (line 184)
- `test_events_path` (line 190)
- `test_api_responses_path` (line 196)
- `test_apps_path` (line 202)

These are session-scoped path fixtures that no test or fixture consumes (5 total, including `test_events_path`). The module-level constants (`TEST_DATA_PATH`, etc.) remain — they're used by `TestConfig` and other fixtures.

### Module export

Add `make_mock_hassette` and `make_ws_hassette_stub` to `src/hassette/test_utils/__init__.py` so end users can import them as `from hassette.test_utils import make_mock_hassette, make_ws_hassette_stub`.

### WebSocket preset wrapper: `make_ws_hassette_stub()`

Location: `src/hassette/test_utils/mock_hassette.py` (alongside `make_mock_hassette`)

A thin wrapper around `make_mock_hassette()` that bakes in the 20 config overrides needed for WebSocket sub-millisecond retry/timeout testing: 13 `websocket.*` namespace fields plus 7 non-websocket fields that differ from model defaults (`logging.log_level="DEBUG"`, `logging.websocket="DEBUG"`, `logging.task_bucket="DEBUG"`, `default_cache_size=1024`, `lifecycle.resource_shutdown_timeout_seconds=1`, `lifecycle.task_cancellation_timeout_seconds=1`, `verify_ssl=False`). Both `test_ws_connection_state.py` and `test_websocket_readiness_events.py` share this identical config set. Domain-specific presets like this are permitted as thin wrappers when a coherent set of 5+ overrides is shared across 2+ files.

## Convention Examples

### Hermetic config factory (the foundation)

**Source:** `src/hassette/test_utils/config.py`

```python
def make_test_config(*, data_dir: Path | str, **overrides: Any) -> HassetteConfig:
    defaults: dict[str, Any] = {
        "token": "test-token",
        "base_url": "http://test.invalid:8123",
        "data_dir": data_dir,
        "disable_state_proxy_polling": True,
        "app": {"autodetect": False},
        "web_api": {"run": False},
        "run_app_precheck": False,
    }
    merged = {**defaults, **overrides}

    cls, cell = _get_hermetic_hassette_config_cls()
    cell[0] = merged
    return cls()
```

### Current unit test factory (what we're replacing)

**Source:** `tests/unit/resources/conftest.py`

```python
def _make_hassette_stub(*, strict_lifecycle: bool = False) -> AsyncMock:
    hassette = AsyncMock()
    hassette.config.logging.log_level = "DEBUG"
    hassette.config.strict_lifecycle = strict_lifecycle
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 1
    # ... 10 more lines of manual config
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_running_loop()
    hassette._scheduler_service.register_removal_callback = Mock()
    # ... more service stubs
    return hassette
```

DO: Use `make_mock_hassette(strict_lifecycle=True)` — one line, validated config.
DON'T: Manually set config fields on a mock — they drift and bypass validation.

### Well-designed web factory (quality bar, out of scope)

**Source:** `src/hassette/test_utils/web_mocks.py`

```python
def create_hassette_stub(
    *,
    run_web_api: bool = True,
    run_web_ui: bool = True,
    cors_origins: tuple[str, ...] = ("http://localhost:3000",),
    # ... focused parameters, not raw config fields
) -> MagicMock:
```

Note: parameters are domain-meaningful (`run_web_api`) not raw config paths (`config.web_api.run`). The new factory should follow this style for behavioral flags.

### Session-scoped DB template (migration target)

**Source:** `tests/integration/conftest.py`

```python
@pytest.fixture(scope="session")
def _migrated_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmpl_dir = tmp_path_factory.mktemp("db_template")
    mock = MagicMock()
    mock.config.data_dir = tmpl_dir
    mock.config.database.path = None
    mock.config.database.retention_days = 7
    # ... 12 more lines of manual config
    mock.ready_event = asyncio.Event()

    db_service = DatabaseService(mock, parent=mock)
    # ...
```

AFTER: `mock = make_mock_hassette(data_dir=tmpl_dir, set_loop=False, database={"max_size_mb": 0, "telemetry_write_queue_max": 500}, lifecycle={"resource_shutdown_timeout_seconds": 5}, web_api={"run": True})` — 4 intentional overrides preserved, 14 lines become 1 call.

## Alternatives Considered

### Option: Consolidate into shared MagicMock factory without real config

Extract the common mock pattern into one shared fixture but keep config as MagicMock auto-vivified attributes. This eliminates duplication but not drift — the shared factory still manually sets config fields that can diverge from real defaults, and adding a new field still requires updating the shared factory.

Rejected because it doesn't address the root cause (unvalidated config) and `make_test_config()` already exists.

### Option: Use real `Hassette` instances

Construct actual `Hassette` objects for tests. This would eliminate all mocking concerns but `Hassette.__init__()` has side effects (enables logging, creates `TaskBucket`) that make it too heavy for unit tests. The harness already provides real `Hassette` instances for integration tests that need them.

Rejected because the constructor side effects make it impractical for the ~15 unit test files that need lightweight mocks.

## Test Strategy

This change modifies test infrastructure, not application code. Verification is:

1. **Full test suite passes** — `uv run nox -s dev -- -n 2` with zero regressions
2. **Grep verification** — confirm zero local factory definitions remain
3. **Line count verification** — `git diff --stat` shows net reduction

No new tests are needed for the factory itself — the existing tests ARE the tests. If a migrated test passes, the factory works correctly for that test's requirements.

## Documentation Updates

- Update `tests/TESTING.md` to document `make_mock_hassette()` as the standard pattern for constructing test hassette objects, replacing the current guidance that says "local to each test file"
- Add `make_mock_hassette` to the `test_utils` public API documentation in `docs/`

## Impact

**Files modified:** ~30 test files (factory removal + import change), 3 conftest files (fixture consolidation), 1 new file (`mock_hassette.py`), 1 updated export (`test_utils/__init__.py`), 1 doc file (`TESTING.md`)

**Blast radius:** Test infrastructure only. No application code changes. No API changes. No frontend changes.

**Risk:** Low. Each file migration is mechanical (replace local factory with shared factory call). The real config validation may surface tests that relied on phantom fields — these are real bugs being exposed, not regressions.

<!-- Gap check 2026-05-19: 2 gaps included — 14 inline mock_hassette fixtures with manual config (unit: test_app_handler_readiness.py, test_app_lifecycle_service.py, test_database_service.py, test_log_records.py, test_runtime_query_service.py, test_web_ui_watcher.py; integration: test_database_service.py, test_telemetry_query_service.py, test_session_manager.py, test_framework_telemetry.py, test_telemetry_execution_id.py, test_telemetry_timed_out.py, test_global_jobs_and_service_info.py, test_web_ui_watcher.py) → T03/T04; dead fixture test_events_path → T05 -->

## Open Questions

None — all design decisions resolved during discovery.
