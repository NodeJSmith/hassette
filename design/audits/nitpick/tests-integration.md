# Nitpick Report: tests/integration/

**Scope:** All 63 `.py` files in `tests/integration/` (~21,600 lines)
**Categories reviewed:** Magic numbers/strings, scattered constants, dead code, naming inconsistencies, structural messiness, import hygiene, hard-coded values, formatting inconsistencies

---

## 1. Magic Numbers and Strings

### Repeated string literals without constants

**test_web_api.py** — `"my_app"` appears 20+ times across test data, fixture setup, and assertions with no constant. Every single test class seeds this string independently.

**test_web_api.py:line ~350+** — `"database is locked"` appears approximately 7 times in `TestDatabaseRetryBehavior` without a named constant.

**test_web_api.py** — `1700000000.0` timestamp appears 10+ times across `TestTelemetrySinceParam` and `TestBusListenersSinceParam` test classes. A `BASE_TS` constant is defined in `telemetry_query_helpers.py` for the DB-layer tests, but `test_web_api.py` duplicates this literal independently.

**test_web_api.py** — `"2024-01-01T00:00:00"` appears 4 times in the `mock_hassette` fixture body.

**test_web_api.py** — `"light.kitchen"` and `"sensor.temp"` entity IDs appear in multiple fixtures and test bodies without a module-level constant.

**test_telemetry_route.py:58** — `last_executed_at=1700000000.0` in `_make_job_summary()` is the same epoch constant used in `test_web_api.py` with no shared definition.

**test_dispatch_unification.py, test_framework_telemetry.py** — `"test.topic"` and `"hass.event.test"` topic strings each appear 4–6 times without constants.

**test_command_executor.py** — `"test_command_executor.py:1"` appears multiple times as a magic source location string. `TEST_SOURCE_LOCATION` is imported from `hassette.test_utils.config` but is used inconsistently — some sites use it, others repeat the inline literal.

**test_web_ui_watcher.py:50, 62, 73** — `"static/css/style.css"`, `"static/js/app.js"`, `"templates/pages/dashboard.html"` each appear twice (once in path construction, once in the broadcast assertion). Candidates for constants.

---

## 2. Scattered Constants (Same Value Across Multiple Files)

**`BASE_TS = 1_000_000.0`** is defined in `telemetry_query_helpers.py` and imported by `test_telemetry_query_service.py`, `test_telemetry_query_service_aggregates.py`, `test_telemetry_query_service_misc.py`, `test_telemetry_timed_out.py`, and `test_history.py`. Good — centrally defined and properly imported.

**`STUB_TIMESTAMP = 1_700_000_000.0`** defined in `test_global_jobs_and_service_info.py:38` and `1700000000.0` used bare in `test_web_api.py` and `test_telemetry_route.py:58`. These are the same conceptual "representative epoch" — should share a single definition or at least acknowledge they're the same value.

**`DURATION = 0.05`** defined independently in both `test_bus_duration.py:35` and `test_bus_error_handler_combos.py:33`. Same value, same semantic meaning (50ms fast-enough-for-tests timer), zero coordination.

**`WAIT_TIMEOUT = 2.0`** defined in `test_command_executor_error_handler.py:17`. The value `2.0` also appears bare in several other files (test_bus_error_handler.py, test_scheduler_error_handler.py) as wait_for timeout arguments. Pattern without a shared constant.

---

## 3. Ternary Abuse

No ternary abuse found. The few conditional expressions in the suite are simple and readable.

---

## 4. Dead Code

### Underscore-prefixed helpers that are "private by convention" but shouldn't be

The project rule is no underscore prefixes on methods or module-level helpers. This rule is violated pervasively:

**test_web_api.py** — `_make_log_record()`, `_mock_submit()` — module-level helper functions with underscore prefixes.

**test_web_api.py** — `_LOGS_REPO` — module-level constant with underscore prefix. (Constants are not the subject of this rule, but it's inconsistent with `TEST_SOURCE_LOCATION` style used elsewhere in the codebase.)

**test_websocket_service.py** — `_build_fake_ws()`, `_make_failing_recv_task()` — module-level helper functions.

**test_bus.py:309** — `_assert_glob_matching()` — module-level helper function.

**test_command_executor.py** — `_make_listener_registration()`, `_make_job_registration()`, `_make_mock_listener()`, `_make_mock_job()` — four module-level helpers with underscores.

**test_dispatch_unification.py:37** — `_make_mock_listener()` — module-level helper.

**test_registration.py:29, 52, 69** — `_make_mock_listener()`, `_make_mock_job()`, `_stub_task_bucket()` — module-level helpers.

**test_api_helpers.py** — `_IB_RECORD`, `_IN_RECORD`, `_IT_RECORD`, `_IS_RECORD`, `_IDT_RECORD`, `_IBT_RECORD`, `_CTR_RECORD`, `_TMR_RECORD`, `_SERVICE_RESPONSE` — nine module-level record constants with underscore prefixes.

**test_session_manager.py:20** — `_make_crashed_event()` — module-level helper.

**test_global_jobs_and_service_info.py** — `_make_job_summary()` — module-level helper.

**test_telemetry_route.py:36** — `_make_job_summary()` — module-level helper (same name as in test_global_jobs_and_service_info.py, defined independently).

**test_command_executor_error_handler.py:34, 44** — `_make_mock_listener()`, `_make_mock_job()` — module-level helpers.

**test_schema_freshness.py:19** — `_create_stub_hassette()` — module-level helper.

**test_api_app_config.py:14** — `_make_manifest_mock()` — module-level helper.

**test_api_app_source.py:23** — `_make_manifest_mock()` — same function name, different file, underscore prefix.

**test_app_utils.py:7** — references `hassette.utils.app_utils._module_name_for` — underscore-prefixed function imported in the test. This is a production code name, not a test helper, but it surfaces here.

### Inner app class methods with underscore prefixes

**test_app_test_harness.py** — Approximately 18 inner app class methods with underscore prefixes: `_on_change`, `_slow_handler`, `_on_attr`, `_on_call`, `_on_loaded`, `_on_registered`, `_on_restart`, `_on_start`, `_on_stop`, `_on_connected`, `_on_disconnected`, `_on_state`, `_on_running`, `_on_stopping`, `_on_crashed`, `_on_failed`, `_on_status`, `_on_started`. These are handlers on inline test App classes — there is zero reason to prefix them with `_`.

**test_scheduler.py:263, 277** — `_OnceExhaustionApp._task`, `_AfterExhaustionApp._task`, `_OnceGroupApp._task` — handler methods on inner app classes with underscore prefix. The class names also use `_` prefixes.

**test_drain_iterative.py:46, 73, etc.** — `Depth1App._on_change`, `Depth2App._on_change`, `Depth3App._on_change`, `_task_a`, `_task_b`, `_secondary`, `_on_change` — inner app class handler methods all prefixed with `_`.

**test_app_harness_simulation.py:33, 40** — `SimTestApp._on_temp`, `SimTestApp._daily_task` — handler methods with underscore prefix.

**test_bus_duration.py** and **test_bus_immediate.py** — inner fixture harnesses do not have this problem; handlers are defined as local `async def handler(...)` closures. Good.

### Lazy imports inside functions and methods

**test_app_test_harness.py** — Multiple lazy imports inside test functions:
- `from unittest.mock import AsyncMock, patch` (inside a test function, line ~289)
- `from hassette.events.hassette import HassetteServiceEvent` (appears ~4 times inside different test bodies, lines ~534, 588, 608, 693)
- `from hassette.events.hassette import HassetteAppStateEvent` (lines ~671, 813)

**test_listeners.py** — `from hassette.bus.rate_limiter import RateLimiter` imported inside approximately 12 test methods across `TestDebounceLogic`, `TestRateLimiterCancel`, and `TestThrottleLogic`. This is the single worst lazy-import violation in the entire suite — the import belongs at the top of the file.

**test_bus.py** — `from hassette.core.commands import InvokeHandler` and `from hassette.events.base import Event` imported inside ~6 test functions. Also `from hassette.bus.rate_limiter import RateLimiter` and `from unittest.mock import patch` in individual test bodies.

**test_bus_immediate.py** — `from whenever import ZonedDateTime` imported inside 4 test functions (`test_immediate_synthetic_event_structure`, `test_immediate_duration_fires_when_elapsed_exceeds`, `test_immediate_duration_starts_timer_for_remaining`, `test_immediate_duration_once_fires_exactly_once`). `from hassette.test_utils.helpers import create_state_change_event` imported inside `test_immediate_duration_once_fires_exactly_once`.

**test_telemetry_execution_id.py:13** — imports `_inv_insert_params`, `_job_insert_params` from `telemetry_repository` — underscore-prefixed production internals imported directly in tests. Indicates the test is piercing the module boundary.

**test_history.py:71** — `api_client._api_service._get_history_raw(...)` — accesses two levels of underscore-prefixed attributes on production objects. Not a lazy import violation, but worth noting as a testing boundary smell.

### Commented-out code and unexplained skips

No commented-out test functions found. No unexplained `pytest.mark.skip` found. Clean on this front.

### Unresolved TODOs

**test_scheduler.py:374** — Comment: `"Note: jitter application to sort_index is not yet implemented (see TODO in classes.py)."` — references an open TODO in production code. The test is deliberately soft on the assertion because the feature isn't done. This is acceptable documentation but worth tracking.

---

## 5. Naming Inconsistencies

### Shadow variable: imported function name overwritten by local variable

**test_state_proxy.py** — `wait_for` is imported from `hassette.test_utils` (line 14-ish). Then at multiple points within test functions, a local variable `wait_for = asyncio.Event()` (lines ~206, 258, 285, 638) shadows the imported utility. This will silently break any code in the same function that tries to call `wait_for(...)` after the assignment. Critical naming collision.

### Generic/unclear names

**test_telemetry_query_service.py:39** — `_l2 = await insert_listener(...)` — underscore prefix on a result variable meaning "unused listener", mimicking Python convention for throwaway variables. If `_l2` is only inserted for side effect, the variable need not be named at all; write `await insert_listener(...)`.

**test_states.py:443** — `light_manager._cache` — accessing a private cache attribute directly. Acceptable for testing internal caching behavior, but it's a fragile coupling.

**test_resource_deps.py:50, 59** — Inner class names `_GatedDep` and `_DependentService` — underscore-prefixed local class names inside a test function. Not a method, but the project rule is no underscore prefixes. These should be `GatedDep` and `DependentService`.

**test_lifecycle_propagation.py** — Similar: no underscore-prefixed inner class names here (clean).

### Inconsistent fixture naming patterns

**test_bus_duration.py** — fixture named `dur_harness`
**test_bus_immediate.py** — fixture named `imm_harness`
**test_bus_error_handler_combos.py** — fixture named `combo_harness`

These three files define structurally near-identical local harness fixtures (same body: `HassetteHarness(...).with_bus().with_scheduler().with_state_proxy().with_state_registry()`, same api_mock setup, same `mark_ready` call). The naming pattern is inconsistent (`dur_`/`imm_`/`combo_`) and the implementations are duplicated. Candidate for a shared parameterizable fixture or a conftest entry.

**test_ws_endpoint.py** — defines local `app` and `client` fixtures that shadow the module-scoped `app` and `client` fixtures from `conftest.py`. The conftest fixtures are designed for the real web-layer tests; this file needs different behavior, so it overrides them locally — but the naming collision means any reader must check carefully which fixture wins in each file.

**test_dashboard_api.py** — also defines a local `client` fixture that yields `(ac, stub)` tuple, conflicting with conftest `client` which yields a single value.

**test_api_app_config.py** and **test_api_app_source.py** — both define local `mock_hassette` and `client` fixtures with the same naming as conftest fixtures. Four files override `client` with incompatible signatures.

### Quasi-setUp pattern in one test class

**test_states.py:28** — `_send_and_wait()` is a module-level helper function with underscore prefix (see naming rule).

**test_apps.py:27** — `TestApps` class has a `setup` autouse fixture that assigns `self.hassette` and `self.app_handler`. This is the only class in the file using this pattern — all other integration test classes use plain fixture arguments. Inconsistent style.

**test_hot_reload.py:57** — `TestBasicHotReload` and other classes in this file also use `setup` autouse fixtures. Internally consistent within this file but still mixing pytest class-fixture pattern with the rest of the suite.

---

## 6. Structural Messiness

### Files over 800 lines

| File | Lines |
|---|---|
| `test_web_api.py` | 1393 |
| `test_app_test_harness.py` | 831 |
| `test_app_factory_lifecycle.py` | ~820 |
| `test_bus.py` | 822 |
| `test_listeners.py` | 825 |
| `test_websocket_service.py` | 846 |
| `test_service_watcher.py` | 820 |
| `test_global_jobs_and_service_info.py` | ~820 |
| `test_state_proxy.py` | 690 (within limit, but approaching) |
| `test_annotation_conversion.py` | ~700 (within limit) |

`test_web_api.py` at 1393 lines is more than 1.7x the stated maximum. It should be split into separate files by test class or feature area (auth, app lifecycle, telemetry, listeners, bus operations, error handling).

### Duplicated harness fixture body

`test_bus_duration.py:38-63`, `test_bus_immediate.py:30-57`, and `test_bus_error_handler_combos.py:37-57` each define a module-local harness fixture with an essentially identical body (7-12 lines of `HassetteHarness` setup, `api_mock`, `mark_ready`, try/yield/finally). The only difference is the fixture name. This is a structural duplication candidate — a shared `bus_harness_factory` fixture in conftest, or a shared helper that all three call.

### Duplicated `capture_event` pattern in test_service_watcher.py

**test_service_watcher.py** — At least 4 tests define an inline `async def capture_event(event)` closure and directly reassign `hassette.send_event = capture_event`. This teardown/capture pattern is repeated verbatim. A fixture or shared helper would eliminate the duplication.

### Section divider comments

The project coding style rule prohibits `# ---...---` section divider comment blocks. These are present in:

- `test_web_api.py` — multiple `# -----------...` dividers
- `test_websocket_service.py` — multiple `# --- ... ---` dividers
- `test_app_test_harness.py` — multiple `# ---...---` dividers
- `test_bus.py` — multiple `# ---...---` dividers
- `test_service_watcher.py` — multiple `# ---...---` dividers
- `test_api_helpers.py` — multiple `# ---...---` dividers
- `test_scheduler.py` — multiple `# ---...---` dividers (e.g., `# Subtask 4:`, `# Subtask 5:`, etc.)
- `test_bus_duration.py` — `# -----------...` dividers
- `test_bus_immediate.py` — `# -----------...` dividers
- `test_drain_iterative.py` — `# -----------...` dividers

### Parameterize candidates

**test_web_api.py — `TestAppKeyValidation`** — Three test methods (`test_start_invalid_app_key`, `test_stop_invalid_app_key`, `test_reload_invalid_app_key`) each carry an identical `@pytest.mark.parametrize` with the same 4-item list: `["!!invalid", "0starts_with_digit", "-starts_with_dash", "a" * 129]`. This should be a single parametrize across actions.

**test_web_api.py — `ListenerSummary` construction** — Two near-identical 25-line `ListenerSummary(...)` constructions in different test classes (around lines 203-229 and 587-616) that share most field values. Candidate for a shared factory helper.

**test_registration.py:29, 52** — `_make_mock_listener()` and `_make_mock_job()` are very similar to the same-named functions in `test_command_executor.py` and `test_dispatch_unification.py`. The same boilerplate mock-builder pattern is repeated across 4 files without sharing.

### Long test functions

**test_web_api.py** — `mock_hassette` fixture (~50 lines). Acceptable but dense; most of the length comes from constructing nested mock objects.

**test_app_test_harness.py** — The "calls list + inner app + assertion" idiom is repeated ~10 times with slight variations. Each instance is short but together they represent structural duplication that could be a parameterized helper.

### Inconsistent use of `conftest.py` vs local fixtures

Several files define local fixtures that duplicate or shadow conftest fixtures:

- `test_database_service.py` — defines a local `db_hassette` fixture (shadows conftest `db_hassette`)
- `test_global_jobs_and_service_info.py` — also defines a local `db_hassette`
- `test_framework_telemetry.py` — defines a local `db_hassette`
- `test_session_manager.py` — defines a local `db_hassette`

Four separate `db_hassette` definitions with minor variations in parameters. The conftest version should be flexible enough to cover all these cases, or the variants should be named distinctly.

---

## 7. Import Hygiene

### Ungrouped imports

**test_bus_immediate.py:131** — `from whenever import ZonedDateTime` inside function body (also flagged under lazy imports above).

**test_bus_immediate.py:496** — `from hassette.test_utils.helpers import create_state_change_event` inside function body — this is a second import of a module that is already imported at file scope on line 17 (`from hassette.test_utils.helpers import create_state_change_event`). The in-function import is entirely redundant.

**test_annotation_conversion.py, test_injection.py, test_extraction.py, test_type_detection.py** — These files have a `# pyright: reportInvalidTypeForm=none` disable comment at line 1, which is legitimate. However the comment is duplicated verbatim in the docstring comment immediately below — `# disabling reportInvalidTypeForm - i know this is invalid...` — this self-narration comment should either be in the pyright pragma line or removed.

### `# noqa: F401` fixture re-exports

`test_telemetry_query_service.py`, `test_telemetry_query_service_aggregates.py`, `test_telemetry_query_service_misc.py`, `test_telemetry_timed_out.py`, `test_telemetry_execution_id.py` — All import fixtures from `telemetry_query_helpers` with `# noqa: F401` comments:
```python
from .telemetry_query_helpers import (
    db,  # noqa: F401 (pytest fixture)
    db_hassette,  # noqa: F401 (pytest fixture)
    svc,  # noqa: F401 (pytest fixture)
)
```
This is the correct pattern for pytest fixture re-exports and is consistent across all five files. Not a bug, but a recurring visual noise. The project could consider using `conftest.py` re-exports instead to eliminate the noqa comments.

### Unused import in test_web_api.py

**test_web_api.py** — `_LOGS_REPO` is defined as a module-level constant but should be verified not to be dead. If it's referenced from multiple tests it's fine; if only used in one place it's a false-constant that should be inlined.

---

## 8. Hard-coded Environment Values

**test_apps_env.py** — Hard-coded environment variable names `ENV_IMPORT_KEY = "HASSETTE_TEST_APP_IMPORT"` and `ENV_SETTINGS_KEY = "MY_SECRET"` are correctly defined as module-level constants. Good practice.

**test_apps_env.py** — Hard-coded filenames and class names (`ENV_READER_FILENAME = "env_reader_app.py"`, `ENV_READER_CLASS = "EnvReaderApp"`, etc.) are all module-level constants. Good.

**test_history.py:10** — `TEST_DATA_PATH = Path.cwd().joinpath("tests", "data", "api_responses")` — uses `Path.cwd()` instead of `Path(__file__).parent.parent / "data" / "api_responses"`. `cwd()` is fragile — it depends on where pytest is invoked from. The pattern `Path(__file__).resolve().parent.parent / ...` (as used in `test_app_factory_lifecycle.py:25`) is more robust. Inconsistency across files.

**test_packaging.py:11** — `_PROJECT_ROOT = Path(__file__).resolve().parents[2]` — correct pattern.

**test_database_service_migrations.py:11** — `MIGRATIONS_PATH = Path(__file__).resolve().parent.parent.parent / ...` — correct pattern.

---

## 9. Formatting Inconsistencies

### Section dividers (covered above under Structural Messiness §6)

See the list of files with `# ---...---` dividers above.

### Docstring completeness inconsistency

**test_api_helpers.py** — `TestInputBoolean` test methods have rich one-line docstrings. `TestInputNumber` methods (`test_list_input_numbers`, `test_create_input_number`, etc.) lack docstrings. Inconsistent treatment within the same file.

**test_states.py** — Module docstring explains purpose. Most test methods have docstrings. `_send_and_wait` helper has no docstring.

**test_models.py** — Has a `logger = logging.getLogger(__name__)` at module scope and then calls `logger.info(...)` inside test functions. Per the project testing rules, tests should not assert on logs, but actively *emitting* info logs from test functions is also unusual — it produces log noise in the test output with no benefit. The `logger.info("All %d state models...")` calls serve as non-asserting commentary.

### Assertion message style inconsistency

**test_bus_duration.py** and **test_bus_immediate.py** — use f-string assertion messages (`assert ... , f"Expected..."`) consistently.

**test_scheduler.py** — mixes f-string assertion messages with plain string messages (e.g., `"once_job should be registered"` vs `f"Expected {expected}, got {actual}"`).

**test_lifecycle_propagation.py:57, 66, 78** — accesses `bus._shutdown_completed` (private attribute) directly in assertions. Technically valid for testing internal invariants, but inconsistent with the test suite's general avoidance of private-attribute access.

### Fixture parameter naming inconsistency

**test_telemetry_query_service.py** — `db: tuple[DatabaseService, int]` — tuple unpacked inside the test as `db_svc, session_id = db`. This two-step unpack is repeated in every test method. A named fixture that yields the already-unpacked pair would be cleaner.

**test_registration.py:78** — `_spawn(coro: object, **kwargs: object) -> MagicMock:  # noqa: ARG001` — inner function uses underscore-prefixed parameter name style for an argument (`ARG001` suppressed because it's intentional). This is the correct pattern for an intentionally-unused argument, but `_spawn` itself has an underscore prefix (it's a local nested function, not a method — the rule is specifically about methods, so this is borderline).

### Minor: raw `asyncio.create_task` used without names in some tests

**test_app_test_harness.py** — Some tests create tasks via `asyncio.create_task(coro)` without a `name=` argument. Other tests in the same file do provide names. The inconsistency makes task traces harder to read on failures.

---

## Summary by Severity

### High (rule violations, anti-patterns)

1. **Lazy imports** — `from X import Y` inside test methods: test_listeners.py (~12 sites), test_bus.py (~6 sites), test_app_test_harness.py (~7 sites), test_bus_immediate.py (5 sites)
2. **Underscore prefixes on module-level helpers** — ~15 files affected, ~35+ functions/constants
3. **Underscore prefixes on inner app class handler methods** — test_app_test_harness.py (~18 methods), test_scheduler.py (3 app classes), test_drain_iterative.py (7+ methods), test_app_harness_simulation.py (2 methods)
4. **Shadow variable `wait_for`** — test_state_proxy.py: local `asyncio.Event` named `wait_for` shadows imported utility function at 4+ sites
5. **Section divider comments** — 10 files with `# ---...---` or `# -------...` decorative dividers

### Medium (hygiene and duplication)

6. **Magic string `"my_app"` x20** — test_web_api.py, no constant
7. **Magic timestamp `1700000000.0`** — independent definitions in test_web_api.py and test_telemetry_route.py; should share with `BASE_TS` or a new constant
8. **`DURATION = 0.05`** duplicated — test_bus_duration.py and test_bus_error_handler_combos.py; same value, same semantics, no coordination
9. **4 files over 800 lines** with test_web_api.py at 1393 — needs splitting
10. **Identical parametrize lists** — TestAppKeyValidation's 3 methods all carry the same 4-item invalid-key list; should be a single parametrize-by-action
11. **3 near-identical harness fixtures** — test_bus_duration.py/imm/combo all duplicate the same 15-line setup body
12. **`capture_event` pattern duplicated** — test_service_watcher.py, ~4 tests
13. **4 local `db_hassette` fixture definitions** — test_database_service.py, test_global_jobs_and_service_info.py, test_framework_telemetry.py, test_session_manager.py all shadow the conftest fixture
14. **`client`/`mock_hassette` fixture shadowing** — test_ws_endpoint.py, test_dashboard_api.py, test_api_app_config.py, test_api_app_source.py all define local versions of conftest fixtures

### Low (style and consistency)

15. **`"database is locked"` x7** — test_web_api.py, no constant
16. **`test_history.py:10` uses `Path.cwd()`** — fragile; should be `Path(__file__).parent`-relative
17. **`_make_job_summary()` defined twice** — test_global_jobs_and_service_info.py and test_telemetry_route.py, independently, same structure
18. **`_make_manifest_mock()` defined twice** — test_api_app_config.py and test_api_app_source.py, independently
19. **`_make_mock_listener()` / `_make_mock_job()` defined in 3+ files** — test_command_executor.py, test_dispatch_unification.py, test_registration.py, test_command_executor_error_handler.py
20. **Docstring inconsistency in test_api_helpers.py** — InputBoolean tests have docstrings, InputNumber tests do not
21. **`logger.info()` calls inside test functions** — test_models.py; log noise with no assertion value
22. **`asyncio.create_task` without `name=` argument** — some tests in test_app_test_harness.py; inconsistent within the file
23. **Redundant import** — test_bus_immediate.py line ~496 imports `create_state_change_event` inside a function body when it's already imported at module scope
24. **`_l2 = await insert_listener(...)` with throwaway name** — test_telemetry_query_service.py:39; just `await insert_listener(...)` if unused
