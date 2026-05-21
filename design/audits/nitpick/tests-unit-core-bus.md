# Nitpick Report: tests/unit/core/ and tests/unit/bus/

**Scope:** All `.py` files under `tests/unit/core/` (36 files) and `tests/unit/bus/` (22 files)
**Style only** — correctness and security are out of scope.

---

## Summary Table

| Category | Count | Severity |
|---|---|---|
| Underscore-prefixed helpers (absolute rule violation) | 70+ instances across 35+ files | HIGH |
| Duplicate factory functions across test modules | 5 duplicated families | HIGH |
| Lazy imports inside test functions | 15+ instances | HIGH |
| `@pytest.mark.asyncio` inconsistency | 3 files | MEDIUM |
| Section divider comments | 15+ files | MEDIUM |
| Scattered magic strings | 10+ clusters | MEDIUM |
| Near-duplicate test pairs | 4 files | MEDIUM |
| `_DDL` / `_WORKTREE` module-level underscore constants | 3 files | MEDIUM |
| Over-long test functions | 2 functions | LOW |
| Fixture candidates (repeated constructor calls) | 3 clusters | LOW |

---

## 1. Underscore-Prefixed Helpers (CRITICAL — absolute rule violation)

The personal project rule is absolute: **no `_` prefixes ever**. The following are violations, sorted by file.

### tests/unit/bus/

**`test_bus.py`**
- `_handler_a`, `_handler_b` — local handler functions used as event listeners

**`test_bus_contract.py`**
- `_CustomDbError` — inner test exception class
- `_handler_contract` — local handler function

**`test_bus_error_handler.py`**
- `_handler` — local handler function

**`test_bus_ordering.py`**
- `_handler_alpha`, `_handler_beta`, `_handler_gamma` — local handler functions

**`test_bus_public_private_split.py`**
- `_handler` — local handler function

**`test_bus_timeout_threading.py`**
- `_make_bus()` — module-level factory function

**`test_duration_config.py`**
- `_attach` — staticmethod on inner test class

**`test_duration_timer.py`**
- `_make_timer()`, `_make_event()` — module-level factory functions

**`test_error_context.py`**
- `_make_bus_error_context()` — module-level factory function

**`test_handler_invoker.py`**
- `_make_task_bucket()`, `_simple_handler()` — module-level factory functions

**`test_listener_timeout.py`**
- `_make_listener()` — module-level factory function

**`test_predicates.py`**
- Numerous local `_` prefixed helper lambdas/functions throughout the 740-line file

**`test_registration_parity.py`**
- `_EXEMPTIONS`, `_IDENTITY_FIELDS`, `_OPTIONS_FIELDS`, `_COVERED_FIELDS` — module-level constants (lines 19–40)

**`test_router.py`**
- `_make_listener()` — module-level factory function

**`test_service_data_predicates.py`**
- No underscore-prefixed items, but see Near-Duplicate section below

### tests/unit/core/

**`test_app_lifecycle_service_operations.py`**
- `_track_initialize`, `_track_reconcile`, `_track_scheduler_barrier`, `_track_bus_barrier` — local closures inside test methods

**`test_app_registry.py`**
- `_make_registry()`, `_make_manifest_obj()`, `_make_app_instance()` — instance methods on `TestAppRegistryGetFullSnapshot`

**`test_bus_service_error_handler.py`**
- `_make_bus_service()`, `_make_listener_with_resolver()`, `_make_event()` — module-level factory functions

**`test_bus_service_timeout.py`**
- `_make_bus_service()`, `_make_event()` — module-level factory functions

**`test_command_executor.py`**
- `_make_cmd_invoke_handler()`, `_make_cmd_execute_job()`, `_make_executor()` — module-level factory functions

**`test_command_executor_error_handler.py`**
- `_make_executor()`, `_make_listener()`, `_make_invoke_handler_cmd()`, `_make_execute_job_cmd()`, `_drain_tasks()` — module-level factory functions

**`test_command_executor_execution_id.py`**
- `_make_executor()`, `_make_hass_event()`, `_make_hassette_event()`, `_make_listener()`, `_make_invoke_handler_cmd()`, `_make_execute_job_cmd()`, `_drain_tasks()`, `_is_valid_uuid4()` — module-level factory functions

**`test_command_executor_pipeline.py`**
- `_init_executor()` — inconsistently prefixed while `make_invocation`, `make_job_record`, `make_executor` in the same file have no prefix

**`test_hassette_timeout_warning.py`**
- `_make_hassette_stub()` — module-level factory function

**`test_log_records.py`**
- `_run_migrations_to_head()`, `_open_migrated_db()`, `_seed_log_records()` — module-level factory/helper functions
- `_DDL` — import alias (see Section 7)
- `_WORKTREE` — module-level path constant (see Section 7)
- `_seed_for_execution()` — instance method

**`test_log_records_retention.py`**
- `_seed_both_tables()` — module-level helper function
- `_DDL` — import alias (see Section 7)

**`test_registration_tracker.py`**
- `_make_tracker()` — module-level factory function
- `_noop()`, `_work()`, `_blocked()` — local async functions used as tasks (these are nested inside test methods; debatable whether renaming adds value, but they follow the same absolute rule)

**`test_scheduler_service_barrier.py`**
- `_make_scheduler_service()` — module-level factory function
- `_work()`, `_noop()`, `_blocked()` — local coroutines inside tests

**`test_scheduler_service_dequeue.py`**
- `_make_job()`, `_make_scheduler_service()` — module-level factory functions

**`test_scheduler_service_error_handler.py`**
- `_make_scheduler_service()`, `_make_job()` — module-level factory functions

**`test_scheduler_service_reschedule.py`**
- `_make_scheduler_service()`, `_make_job()`, `_make_interval_trigger()`, `_frozen_now()` — module-level factory functions

**`test_scheduler_service_timeout.py`**
- `_make_scheduler_service()`, `_make_job()` — module-level factory functions

**`test_service_watcher_exhausted.py`**
- `_build_hassette()`, `_DummyService`, `_TempService`, `_make_failed_payload()`, `_make_watcher()` — module-level factories and classes

**`test_shutdown_event_guard.py`**
- `_cleanup_hassette()` — module-level async helper

**`test_telemetry_repository.py`**
- `_make_listener_registration()`, `_make_job_registration()` — module-level factory functions
- `_DDL` — large inline DDL string (see Section 7)

---

## 2. Duplicate Factory Functions Across Test Modules

### `_make_executor()` — three near-identical copies

`test_command_executor.py`, `test_command_executor_error_handler.py`, and `test_command_executor_execution_id.py` each define an independent `_make_executor()` factory that builds a `CommandExecutor` with mocked internals. The factories differ only in minor details (which mocks are pre-attached). This is dead duplication — the factory belongs in a shared `conftest.py` or `test_utils` module.

### `_make_bus_service()` — two near-identical copies

`test_bus_service_error_handler.py` and `test_bus_service_timeout.py` both define `_make_bus_service()` with essentially the same construction logic. These two files cover neighboring concerns and their factories should be unified in the `tests/unit/core/conftest.py`.

### `_make_scheduler_service()` — four near-identical copies

`test_scheduler_service_barrier.py`, `test_scheduler_service_dequeue.py`, `test_scheduler_service_error_handler.py`, `test_scheduler_service_reschedule.py`, and `test_scheduler_service_timeout.py` all define `_make_scheduler_service()`. The bodies are functionally equivalent with minor variation in which config fields are set. One shared factory in conftest with optional overrides would eliminate all five.

### `_make_job()` — three independent copies

`test_scheduler_service_dequeue.py`, `test_scheduler_service_error_handler.py`, `test_scheduler_service_reschedule.py`, and `test_scheduler_service_timeout.py` each define `_make_job()` in isolation. They produce `ScheduledJob` instances with identical minimal fields and would benefit from a shared factory.

### `_make_listener_registration()` / `_make_job_registration()` inline duplication

`test_telemetry_repository.py` defines `_make_listener_registration()` and `_make_job_registration()` as local module-level helpers. The same minimal fixture is substantially reproduced inside `tests/unit/core/conftest.py`. These should be unified.

---

## 3. Lazy Imports Inside Test Functions

Personal project rule: all imports at the top of the file. `TYPE_CHECKING` guards are the only exception.

**`test_predicates.py`** — 12+ instances
Lines inside individual test methods repeatedly import:
```python
from hassette.event_handling.accessors import get_state_value_new
from hassette.event_handling.accessors import get_state_value_old
```
These are function-scoped imports for no reason. Move to top-level imports.

**`test_error_context.py`** line 67
```python
import dataclasses
```
Inside a test method. Move to top-level.

**`test_bus.py`** line 149
```python
from hassette.bus.bus import Bus
```
Inside `test_bus_requires_parent`. Move to top-level.

**`test_scheduler_service_barrier.py`** lines 18, 22
```python
def _make_scheduler_service() -> "SchedulerService":
    from hassette.core.scheduler_service import SchedulerService
```
The import is inside the factory function body. The `# noqa: F821` on the return annotation is the tell. Move the import to top-level and remove the forward reference.

**`test_web_api_service.py`** lines 14–15 (fixture)
```python
def web_api_service(unused_tcp_port_factory) -> WebApiService:
    from tests.conftest import TestConfig
```
`TestConfig` is imported inside the fixture. Move to top-level.

---

## 4. `@pytest.mark.asyncio` Inconsistency

The project uses `asyncio_mode = "auto"` (inferred from the vast majority of async tests having no decorator). Three files break that pattern by applying `@pytest.mark.asyncio` explicitly to selected tests while the rest of the suite omits it:

**`test_bus_public_private_split.py`** — line 90: one test method has the decorator; others in the same file don't.

**`test_handler_invoker.py`** — lines 179, 193, 213, 228, 244, 265: six test methods have the decorator; others in the same file don't.

**`test_runtime_query_service.py`** — lines 191, 227, 254, 270, 284, 291: six test methods in `TestCompletionBatching` have the decorator; the surrounding async tests in the same file don't.

**`test_service_watcher_exhausted.py`** — top-level async test functions (lines 105, 144, 169, 199) use `@pytest.mark.asyncio`; this file has no class grouping and uses only module-level functions. Inconsistent with the class-based pattern elsewhere in the suite.

All four files should have the decorator removed from the individual tests (or added consistently everywhere if the project ever moves away from auto mode, but "auto" mode makes this dead markup today).

---

## 5. Section Divider Comments

The project rule is: **no decorated comment blocks between methods**. The following files use `# ---...---` or `# ===...===` dividers to split test functions into sections:

- `tests/unit/bus/test_bus.py` — multiple `# ---` blocks
- `tests/unit/bus/test_bus_contract.py` — multiple `# ---` blocks
- `tests/unit/bus/test_bus_error_handler.py` — multiple `# ---` blocks
- `tests/unit/bus/test_bus_ordering.py` — multiple `# ---` blocks
- `tests/unit/bus/test_duration_timer.py` — multiple `# ---` blocks
- `tests/unit/bus/test_predicates.py` — multiple `# ---` blocks throughout (~15 dividers)
- `tests/unit/core/test_command_executor_error_handler.py` — multiple `# ---` blocks
- `tests/unit/core/test_command_executor_execution_id.py` — multiple `# ---` blocks
- `tests/unit/core/test_command_executor_pipeline.py` — multiple `# ---` blocks
- `tests/unit/core/test_scheduler_service_dequeue.py` — multiple `# ---` blocks
- `tests/unit/core/test_scheduler_service_reschedule.py` — multiple `# ---` blocks (10+ sections)
- `tests/unit/core/test_telemetry_repository.py` — multiple `# ---` blocks (8+ sections)

All dividers should be removed. Classes or pytest marks can provide grouping where needed; the class names already serve as section headers.

---

## 6. Scattered Magic Strings

### `"state_changed"` / `"hass.event.state_changed"` (tests/unit/bus/)

`test_router.py` uses `"state_changed"` as a topic 20+ times across its tests. `test_error_context.py`, `test_listener_identity.py`, and `test_listeners.py` use `"hass.event.state_changed"` repeatedly. Define a module-level constant:

```python
STATE_CHANGED = "hass.event.state_changed"
```

### `"light.kitchen"` (tests/unit/bus/)

`test_duration_config.py`, `test_duration_timer.py`, `test_listeners.py`, and `test_predicates.py` all repeat `"light.kitchen"` as a test entity ID. Define a constant per file or extract to a shared test constant module.

### `"test.topic"` / `"test/topic"` (tests/unit/bus/ and core/)

`test_bus.py` repeats `"test.topic"` 8+ times. `test_command_executor.py`, `test_command_executor_error_handler.py`, and `test_command_executor_execution_id.py` repeat `"test/topic"` many times each. Define per-file constants.

### `"test_owner"` (tests/unit/bus/ and scheduler tests)

`test_duration_config.py`, `test_duration_timer.py`, `test_listeners.py`, `test_scheduler_service_dequeue.py`, and `test_scheduler_service_reschedule.py` all use `"test_owner"` as an owner ID string. Define a constant.

### `"exec-001"`, `"exec-xyz"`, `"exec-restart-test"`, `"exec-exec"`, `"exec-other"` (test_log_records.py)

Execution ID strings scattered throughout seeding helpers. Group into a named constant block at the top of the file.

### `600.0` in test_hassette_timeout_warning.py

The sentinel timeout value `600.0` appears three times across the test class bodies and the helper. Define:

```python
DEFAULT_TIMEOUT = 600.0
```

### `99999` as a nonexistent FK ID (test_router.py, test_telemetry_repository.py)

Both files use `99999` as a sentinel for a nonexistent database ID. Name it:

```python
NONEXISTENT_ID = 99999
```

### `session_id = 1` and `app_startup_timeout_seconds: 30` (tests/unit/core/conftest.py)

The session ID `1` and timeout `30` appear in conftest and are re-used in `test_app_handler_readiness.py`. Define them as constants in conftest.

---

## 7. Module-Level Underscore-Prefixed Constants

Underscore prefixes on module-level constants are also against the rule (they're not methods, but the same principle applies — there are no external consumers to protect from in a test file).

**`test_log_records.py`**
- `_DDL` (import alias for a DDL constant from test_utils)
- `_WORKTREE` (module-level `Path` constant, line ~25)

**`test_log_records_retention.py`**
- `_DDL` (import alias)

**`test_telemetry_repository.py`**
- `_DDL` (large inline DDL string, lines 21–136)

**`test_registration_parity.py`**
- `_EXEMPTIONS`, `_IDENTITY_FIELDS`, `_OPTIONS_FIELDS`, `_COVERED_FIELDS` (lines 19–40)

All four should drop the leading underscore. `_DDL` used as an import alias can be renamed at the import site: `from hassette.test_utils.database import LOG_RECORDS_DDL as DDL` or just referenced by its original name.

---

## 8. Near-Duplicate Test Pairs

Tests that cover the same ground twice, often with only a variable name changed.

### test_combinator_predicates.py

- `test_allof_evaluates_all_predicates` + `test_allof_requires_all_predicates_true` — both verify AllOf requires all predicates to pass; the distinction (one tests "evaluates all", the other "requires all true") does not add new coverage
- `test_allof_returns_false_when_any_predicate_fails` is a third test for the same path
- Same pattern repeats for AnyOf and Not combinators
- `test_ensure_tuple_with_single` + `test_ensure_tuple_with_tuple` could be merged into a single parametrized test
- `test_normalize_where_with_predicate` + `test_normalize_where_with_callable` could be parametrized

### test_conditions.py

- `test_contains_condition_comprehensive` + `test_contains_condition` — the "comprehensive" version is a superset; the standalone is dead
- Same pattern for `EndsWith`, `StartsWith`, and `Present` conditions — each has a standalone test and a "comprehensive" variant that covers all its cases

### test_service_data_predicates.py

Four near-duplicate pairs all testing the same predicate behavior with slight naming variation:
- `test_service_data_where_not_provided_requires_presence` + `test_service_data_where_typing_any_requires_presence` (lines 21, 29)
- `test_service_data_where_exact_value_matching` + `test_service_data_where_exact_match` (lines 38, 50)
- `test_service_data_where_with_callable_conditions` + `test_service_data_where_with_callable` (lines 61, 76)
- `test_service_data_where_with_glob_patterns` + `test_service_data_where_with_globs` (lines 87, 100)

Each pair tests the same code path. The duplicates should be merged or the weaker one removed.

### test_scheduler_service_reschedule.py

- `test_reschedule_none_removes_job` + `test_reschedule_exhausted_job_via_none_trigger` (in `TestRescheduleNoneRemovesJob`) — both test that `next_run_time()` returning `None` removes the job and does not re-enqueue. The second adds `trig.next_run_time.assert_called_once()` as the only new assertion, which could be added to the first.

---

## 9. Fixture Candidates (Repeated Constructor Calls)

### ListenerMetrics in test_metrics.py

`ListenerMetrics(listener_id=1, owner_id="app", topic="t", handler_method="h")` is constructed ~12 times across the test module with the same minimal arguments. This is a strong pytest fixture candidate:

```python
@pytest.fixture
def metrics() -> ListenerMetrics:
    return ListenerMetrics(listener_id=1, owner_id="app", topic="t", handler_method="h")
```

The current `"t"` and `"h"` values are also excessively terse — `"topic"` and `"handler"` would be clearer.

### `make_task_bucket()` + `Listener.create_cancel_listener()` in test_listeners.py (TestCreateCancelListener)

Every test method in `TestCreateCancelListener` repeats:
```python
tb = make_task_bucket()
listener = Listener.create_cancel_listener(tb, ...)
```
This is a direct fixture extraction opportunity.

### RuntimeQueryService setup in test_runtime_query_service.py

The `runtime` fixture (lines 84–105) manually sets 15+ attributes on a `RuntimeQueryService.__new__()` instance. This is already a fixture, which is good — but the `mock_hassette` fixture (lines 24–81) wires 12+ private attributes onto the mock manually. This setup complexity is a sign the fixture surface needs simplification, not a new finding per se, but note it as a maintainability risk.

---

## 10. Over-Long Test Functions

### `test_persist_batch_includes_source_tier` in test_command_executor_pipeline.py (~133 lines)

This test function contains an inline schema DDL string, fixture setup, record construction, DDL execution, and assertion blocks all in one body. The DDL string alone is ~60 lines. The function should be split: extract the DDL into a module-level constant and use a fixture for the initialized database/executor state.

### `test_get_path_accessor` in test_predicates.py (~70 lines)

70 lines of assertions against a single `get_path_accessor` function. Each assertion group should be its own parametrized case or at minimum broken into three focused test functions (basic path access, nested path access, missing path behavior).

---

## 11. Accessing Private Attributes in Tests

The following tests access `_`-prefixed attributes on production classes directly (not test helpers — actual production object internals). This is acceptable when testing internal invariants, but clusters of private access suggest the public API surface is insufficient for the tests being written:

**`test_app_lifecycle_service_operations.py`** — calls `_reconcile_app_registrations()`, a method with an underscore prefix on the production class. If the method needs to be tested, either rename it or provide a public test hook.

**`test_app_registry.py`** — directly reads `_blocked_apps` on the registry instance.

**`test_bus_service_public_accessors.py`** — directly accesses `_dispatch_pending` and `_dispatch_idle_event` on the bus service. The test file name says "public accessors" but the test body uses private ones.

**`test_registration_tracker.py`** — directly reads and writes `_tasks` on `RegistrationTracker` instances in multiple tests (e.g., `tracker._tasks["my_app"]`). Since `_tasks` is the only meaningful state on this class, this is hard to avoid — but it warrants noting.

---

## 12. Miscellaneous Minor Items

**`test_scheduler_service_reschedule.py`** line 591: inline `SchedulerService.__new__()` setup duplicates the `_make_scheduler_service()` factory defined 35 lines above. The inline setup adds a few extra config fields (`min_delay_seconds`, `max_delay_seconds`, `default_delay_seconds`). Either extend the factory to accept those as parameters or extract a second fixture.

**`test_scheduler_service_reschedule.py`** line 265: another inline `SchedulerService.__new__()` setup block (in `test_pop_due_uses_fire_at_not_next_run`) that could use the existing factory.

**`test_runtime_query_service.py`**: `_start_time = 1704067200.0` is used as a hardcoded epoch value. Name it:
```python
EPOCH_2024_JAN_01 = 1704067200.0
```

**`test_telemetry_repository.py`**: `bad_listener_id = 99999` and `bad_job_id = 99999` are defined inline in two separate tests rather than sharing a module-level constant.

**`test_telemetry_query_helpers.py`**: Imports `_since_clause` — a private function — directly from the production module. If this function is worth testing, it should be renamed without a prefix.

**`test_web_ui_watcher.py`**: Imports `_WATCH_DIRS`, `_WEB_DIR`, and `_change_kind` — three underscore-prefixed production module attributes. All three are either constants or a pure function that could be made public.

**`test_app_registry.py`**: `"only_app"` string literal repeated 5+ times across `TestAppRegistryGetFullSnapshot` — define as a class-level constant.

**`test_command_executor_execution_id.py`**: `cmd.job.job_id = 99` — the magic number `99` has no explanatory name. Use `JOB_DB_ID = 99` or similar.
