# Nitpick Validation Report: Test Suite

Validates findings from the four test-suite nitpick reports against the actual codebase.
Each finding was checked at the cited file and line. Disposition is **Confirmed**, **False Positive**, or **Borderline**.

---

## Report 1: tests/unit/core/ and tests/unit/bus/

### Confirmed Findings

**Underscore-prefixed module-level helpers and constants** — Confirmed pervasive.
All cited module-level factory functions (`_make_executor()`, `_make_bus_service()`, `_make_scheduler_service()`, `_make_job()`, `_make_timer()`, etc.) and module-level constants (`_EXEMPTIONS`, `_IDENTITY_FIELDS`, `_OPTIONS_FIELDS`, `_COVERED_FIELDS` in `test_registration_parity.py`) are genuinely at module scope with no technical reason for the `_` prefix. Same for class-level methods on `TestAppRegistryGetFullSnapshot`. Count: 60+ instances confirmed.

**Underscore-prefixed module-level handler stubs in test_bus.py** — `_handler_a` and `_handler_b` are defined at module level (lines 30, 34), confirmed. These are module-level async functions with underscore prefixes.

**Duplicate factory functions** — All five families confirmed as real duplication:
- `_make_executor()`: three copies at module level across `test_command_executor.py` (line 40), `test_command_executor_error_handler.py` (line 19), `test_command_executor_execution_id.py` (line 21). Bodies are nearly identical — same 15+ lines of `CommandExecutor.__new__()` setup — with minor additions in the latter two.
- `_make_bus_service()`: two copies confirmed nearly identical (same 15-line body, only type annotation differs: `float` vs `float | None`).
- `_make_scheduler_service()`: five copies confirmed across five files.
- `_make_job()`: four copies confirmed.
- `_make_listener_registration()` / `_make_job_registration()`: duplication with conftest confirmed.

**Lazy imports in test functions** — All confirmed real:
- `test_predicates.py`: 15+ lazy imports of `get_state_value_new`, `get_state_value_old`, `Increased`, `Comparison`, `IsIn`, `summarize_top_level` inside individual test function bodies (lines 463–738).
- `test_error_context.py` line 67: `import dataclasses` inside a test method body.
- `test_bus.py` line 149: `from hassette.bus.bus import Bus` inside `test_bus_requires_parent`.
- `test_scheduler_service_barrier.py` lines 18/22: import inside factory function body.

**`@pytest.mark.asyncio` inconsistency** — Confirmed valid. `asyncio_mode = "auto"` is set in `pyproject.toml` (line 120). All four cited files have redundant decorators: `test_bus_public_private_split.py` (1 decorator), `test_handler_invoker.py` (6 decorators), `test_runtime_query_service.py` (6 decorators), `test_service_watcher_exhausted.py` (4 decorators).

**`_DDL` import alias** — Confirmed. `test_log_records.py` imports as `LOG_RECORDS_TEST_DDL as _DDL`. `test_telemetry_repository.py` defines `_DDL` as a large inline string at module level (line 21). `test_log_records_retention.py` also imports as `_DDL`.

**`_WORKTREE` constant** — Confirmed. `test_log_records.py` line 33: `_WORKTREE = Path(__file__).parent.parent.parent.parent` — module-level constant with underscore prefix.

**Near-duplicate test pairs in `test_service_data_predicates.py`** — Confirmed real duplication. Four pairs verified:
- `test_service_data_where_not_provided_requires_presence` vs `test_service_data_where_typing_any_requires_presence`: identical predicate, identical test data, one extra comment about "any value type."
- `test_service_data_where_exact_value_matching` vs `test_service_data_where_exact_match`: same predicate behavior, same assertions, minor field variation.
- `test_service_data_where_with_callable_conditions` vs `test_service_data_where_with_callable`: same callable pattern, same assertion.
- `test_service_data_where_with_glob_patterns` vs `test_service_data_where_with_globs`: identical glob behavior, different verbosity.

**`99999` sentinel in `test_telemetry_repository.py`** — Confirmed. Defined as `bad_listener_id = 99999` and `bad_job_id = 99999` as local variables in two separate test methods (lines 1070, 1097) rather than a shared constant.

**`test_command_executor_execution_id.py` `cmd.job.job_id = 99`** — Confirmed, magic number with no named explanation.

**`"test.topic"` repeated 14 times in `test_bus.py`** — Confirmed. String literal appears 14 times in a 173-line file. Module-level constant warranted.

**`600.0` in `test_hassette_timeout_warning.py`** — Confirmed. Value appears 5 times (lines 9, 10, 30, 44, 58) as both default parameter values and explicit arguments with no named constant.

**Over-long function `test_persist_batch_includes_source_tier`** — Confirmed. Inline DDL string creates a 133-line test function.

### False Positives

**`_track_initialize`, `_track_reconcile`, `_track_scheduler_barrier`, `_track_bus_barrier`** (`test_app_lifecycle_service_operations.py`) — FALSE POSITIVE. All are inner closures defined inside test method bodies (at 8-space indentation). The project rule about no underscore prefixes applies to methods and module-level functions; inner closures inside test functions are the borderline case noted in the validation task. These specific ones are test-internal side-effect trackers that are never called externally.

**`_noop()`, `_work()`, `_blocked()` in `test_registration_tracker.py` and `test_scheduler_service_barrier.py`** — FALSE POSITIVE. Verified all are inner closures at method-body indentation (8-space), not module-level functions. The rule applies to methods and module-level names.

**Near-duplicate pairs in `test_conditions.py`** — FALSE POSITIVE. The nitpicker claims `test_contains_condition` is dead because `test_contains_condition_comprehensive` is a superset. Verified: they use entirely different keywords (`"test"` vs `"kitchen"`), different entity-ID use cases, and different edge cases (the standalone tests string-contains with entity IDs; the comprehensive tests with `""` and `None`). These are genuinely distinct test scenarios, not duplicates.

**`"light.kitchen"` across multiple bus test files** — FALSE POSITIVE per the validation criteria. The value appears in 4 different test files (`test_duration_config.py`: 17 times, `test_duration_timer.py`: 6 times, `test_listeners.py`: 8 times, `test_predicates.py`: 30 times), but these are separate files testing unrelated features. Per the validation rules, duplication across files testing different features is intentional isolation. Within `test_predicates.py` alone (30 occurrences), a per-file constant `KITCHEN_ENTITY = "light.kitchen"` would be warranted — so this is **confirmed within a single file** but is a false positive as a cross-file finding.

**`"test_owner"` across multiple files** — FALSE POSITIVE as a cross-file finding for the same reason. Each file independently owns its test setup.

**Section divider comments** — BORDERLINE (see below).

### Borderline

**Section divider comments in test files** — BORDERLINE. The project rule says no section dividers, but several of the flagged files are very long (e.g., `test_telemetry_repository.py` at 1261 lines, `test_predicates.py` at 741 lines, `test_scheduler_service_reschedule.py` at 668 lines). The dividers provide real navigation value. Marking as borderline rather than confirmed: technically a rule violation, but the fix (class-based grouping) is more disruptive than the problem at this scale.

**`"session_id = 1"` and `app_startup_timeout_seconds: 30` in conftest** — BORDERLINE. These are configuration defaults used in a small number of locations. A constant would be correct style but the impact of the raw values is minimal.

---

## Report 2: tests/unit — remaining directories

### Confirmed Findings

**`_PATCH_TARGET` duplicated across scheduler test files** — Confirmed. Identical string `"hassette.scheduler.scheduler.capture_registration_source"` defined independently in `test_scheduler_error_handler.py` (line 9) and `test_scheduler_timeout_threading.py` (line 34). Same value, same module, no coordination.

**`_make_scheduler()` duplicated** — Confirmed near-identical. Both files define `_make_scheduler()` with the same ~18 lines of `Scheduler.__new__()` setup; the only difference is one extra line initializing `scheduler._error_handler = None` in one file.

**`_noop()` defined three times across scheduler test files** — Confirmed. `async def _noop() -> None: pass` exists identically in `test_scheduler_error_handler.py` (line 32), `test_scheduler_timeout_threading.py` (line 30), and `test_scheduled_job_timeout.py` (line 39). No `tests/unit/scheduler/conftest.py` exists to centralize it.

**`_ConcreteResource` duplicated in resources tests** — Confirmed. `class _ConcreteResource(Resource): async def on_initialize(self) -> None: pass` defined independently in `test_emit_readiness_event.py` (line 16) and `test_lifecycle_side_effect_free.py` (line 9). The `tests/unit/resources/conftest.py` exists but contains only a module docstring.

**`test_lifecycle_transitions.py` — all 16 async tests decorated with `@pytest.mark.asyncio`** — Confirmed valid. With `asyncio_mode = "auto"` in pyproject.toml, all 16 decorators are dead markup. Also confirmed in `test_emit_readiness_event.py` (2), `test_lifecycle_side_effect_free.py` (2), `test_start_children_and_wait.py` (4).

**`test_lifecycle_propagation.py` over 800 lines** — Confirmed at 953 lines.

**`_shutdown_order` and `_init_order` as module-level mutable shared state** — Confirmed. Both are module-level lists (lines 123, 331) requiring `.clear()` calls scattered through tests. Genuine test coupling risk.

**Lazy imports in `test_ws_helpers.py` and `test_direct_status_assignments.py`** — Confirmed. `import anyio` inside a test method body and `from hassette.resources.mixins import LifecycleMixin` inside `test_harness_status_bypass`.

**All underscore-prefixed module-level helpers and classes** — Confirmed pervasive across all listed files (`_SimpleResource`, `_SimpleService`, `_ConcreteResource`, `_make_resource`, `_Parent`, `_ReadyOnInit`, `_NeverReady`, `_ClosedResourceService`, `_make_leaf`, etc.).

**`"0.24.0"` version string repeated 7 times** — Confirmed. The actual project version in `pyproject.toml` is `0.32.0`. The `0.24.0` in test fixtures is fake pyproject content that will mislead readers when it diverges further from the real version. Extracting to a constant (or using `"0.1.0"` as an obviously-fake placeholder) is warranted.

### False Positives

**Magic numbers in `test_mappers.py`** — FALSE POSITIVE. The values `42`, `123.4`, `42.5`, `100`, `5`, `300.0` are default values in a `_make_system_status()` factory. Each appears once in the factory defaults and once in the corresponding assertion — this is the intended pattern for pass-through field tests. There is no semantic concept these numbers represent beyond "a non-zero distinguishable value." A constant like `UPTIME_SECONDS = 123.4` would add no clarity. The nitpicker's concern about `100`, `5`, `300.0` being "three separate arbitrary values in one call site" misses that this is exactly what the test is doing — using distinct values to verify each field is preserved independently.

**`test_lifecycle_transitions.py:308–315` — monkey-patch fragility** — FALSE POSITIVE for a nitpick report. This is a correctness concern, not a style issue. Flagging it as "structural messiness" is out of scope for style-only review. (The pattern is real and fragile, but belongs in a testing practices review, not a style audit.)

**`test_generate_sync_facade.py:24` — ternary with outer parens** — FALSE POSITIVE. `(lambda: None)` with outer parens is minor formatting noise; this finding is too granular to act on. The parens have zero behavioral impact and reasonable people disagree on whether they aid readability.

### Borderline

**`test_scheduler_error_handler.py:96–120` `test_convenience_methods_pass_on_error`** — BORDERLINE. Testing 7 convenience methods in one function body is a valid parametrize opportunity, but the current form is readable and the test is unambiguous. Not a clear violation.

**`sys.path.insert(0, ...)` in `test_generate_sync_facade.py`** — BORDERLINE. The nitpicker is right that this is a code smell; the missing comment about why is a fair callout. But this is a codegen path edge case, not a common pattern.

---

## Report 3: tests/integration/

### Confirmed Findings

**Lazy imports in test methods** — Confirmed and severe:
- `test_listeners.py`: `from hassette.bus.rate_limiter import RateLimiter` repeated inside ~12 test methods (confirmed at lines 84, 107, 124, 159, 179, 211, 231, 238, 257, 284, 310, 312, 339). The import belongs at module top-level.
- `test_bus_immediate.py`: `from whenever import ZonedDateTime` inside 4 test functions; also a redundant in-function re-import of `create_state_change_event` at line ~496 when it is already imported at module scope.
- `test_app_test_harness.py`: multiple lazy imports of `AsyncMock`, `patch`, `HassetteServiceEvent`, `HassetteAppStateEvent` inside test bodies.

**Underscore-prefixed module-level helpers** — Confirmed across 15+ integration test files. All cited instances (`_make_log_record`, `_mock_submit`, `_build_fake_ws`, `_make_failing_recv_task`, `_assert_glob_matching`, `_make_listener_registration`, `_make_mock_listener`, `_make_mock_job`, `_stub_task_bucket`, etc.) are genuine module-level functions.

**Underscore-prefixed inner app class handler methods** — Confirmed. `test_app_test_harness.py` has ~18 inner app class methods with `_` prefix (`_on_change`, `_slow_handler`, etc.). `test_scheduler.py` app inner class methods (`_task`). `test_drain_iterative.py` inner class handlers (`_on_change`, `_task_a`, `_task_b`). These are methods on inner test App classes — the `_` prefix serves no purpose.

**`wait_for` shadow variable** — Confirmed but severity is lower than reported. Verified that the shadow (`wait_for = asyncio.Event()`) occurs at the start of each function that uses it, and the imported `wait_for()` utility is called in separate methods that do not shadow it. There is no case where the imported `wait_for()` is called after the shadow assignment within the same function. The shadow is still a naming hazard — a future developer could add a call to the utility inside one of the shadowing methods and get a silent bug. The finding is valid but the "critical" label is overstated.

**3 near-identical harness fixture bodies** — Confirmed. `test_bus_duration.py`, `test_bus_immediate.py`, and `test_bus_error_handler_combos.py` each define a local `HassetteHarness` setup fixture with essentially the same body.

**`DURATION = 0.05` duplicated** — Confirmed. Same value, same semantic meaning (50ms timer), defined independently in `test_bus_duration.py` (line 35) and `test_bus_error_handler_combos.py` (line 33).

**4 local `db_hassette` fixture definitions** — Confirmed. Shadowing conftest fixture across 4 integration test files.

**`test_web_api.py` at 1393 lines** — Confirmed, 1.7x the stated maximum.

**`_make_job_summary()` defined twice** — Confirmed. Independent definitions in `test_global_jobs_and_service_info.py` and `test_telemetry_route.py`.

**`_make_manifest_mock()` defined twice** — Confirmed. Independent definitions in `test_api_app_config.py` and `test_api_app_source.py`.

**`_make_mock_listener()` / `_make_mock_job()` in 3+ files** — Confirmed. Boilerplate mock-builder repeated across `test_command_executor.py`, `test_dispatch_unification.py`, `test_registration.py`, `test_command_executor_error_handler.py`.

**`"my_app"` 20+ times without constant** — Confirmed in `test_web_api.py`. Every test class seeds this string independently.

**`1700000000.0` timestamp without shared constant** — Confirmed. Appears bare in `test_web_api.py` and `test_telemetry_route.py:58`, independently from `STUB_TIMESTAMP` in `test_global_jobs_and_service_info.py`.

**`test_history.py` uses `Path.cwd()`** — Confirmed. `TEST_DATA_PATH = Path.cwd().joinpath(...)` at line 10. Fragile; should use `Path(__file__).resolve().parent`.

**Identical `@pytest.mark.parametrize` lists in `TestAppKeyValidation`** — Confirmed. Three test methods each carry the same 4-item invalid-key list.

**`_l2 = await insert_listener(...)` — throwaway named variable** — Confirmed. If `_l2` is only inserted for side-effect, `await insert_listener(...)` with no assignment is clearer.

### False Positives

**`"my_app"` finding severity** — The finding itself is confirmed, but the MEDIUM severity is apt. This is style cleanup, not a bug.

**`# noqa: F401` fixture re-exports** — FALSE POSITIVE as a finding. The report acknowledges these are correct pattern but flags them as "recurring visual noise." This is not a finding to act on; re-exporting fixtures via explicit imports with `# noqa: F401` is the standard pytest pattern and cleaner than conftest re-exports in some cases.

**`asyncio.create_task` without `name=` in test_app_test_harness.py** — FALSE POSITIVE as a nitpick. Task names aid debugging but are not required, and inconsistency within one file is extremely low impact.

**`test_ws_endpoint.py` / `test_dashboard_api.py` local fixture shadowing** — FALSE POSITIVE for conflation. These files intentionally define local `client` fixtures with different behavior than the conftest fixture — this is documented pytest behavior for per-file overrides. It's only a problem if the shadow is accidental, and in these cases the different setup (returning a tuple vs single value) makes it clearly intentional. The naming could be improved but it's not a bug.

**`_inv_insert_params` / `_job_insert_params` import from telemetry_repository** — Not strictly a nitpick finding (it's a boundary smell, correctly labeled as such). Out of scope for a style audit.

### Borderline

**Section divider comments** — BORDERLINE. Same rationale as Report 1: several flagged files exceed 800 lines where dividers provide genuine navigation value.

**Docstring inconsistency in `test_api_helpers.py`** — BORDERLINE. Legitimate observation but very low impact.

**`logger.info()` calls inside test functions in `test_models.py`** — BORDERLINE. Log noise with no assertion value is wasteful but harmless.

---

## Report 4: tests/e2e/ and tests/system/

### Confirmed Findings

**`wait_for_timeout(300)` / `wait_for_timeout(500)` without constants** — Confirmed. 21 occurrences of `300` and 15 of `500` across multiple e2e test files. These values represent distinct wait categories (filter settle vs animation settle) that would benefit from named constants. The nitpicker's suggested names `FILTER_SETTLE_MS = 300` and `ANIMATION_SETTLE_MS = 500` are reasonable, though the exact semantic boundary between them should be verified.

**`timeout=5000` / `timeout=10000` scattered across e2e tests** — Confirmed. 37 bare occurrences of `5000` and several of `10000` with no constants.

**`{"width": 375, "height": 812}` raw literal in `test_logs.py:275`** — Confirmed. `MOBILE_VIEWPORT` is already defined in `conftest.py:46` with the exact same values and is not imported or used in `test_logs.py`.

**`{"width": 800, "height": 600}` and `{"width": 2400, "height": 600}` without constants** — Confirmed. The `800×600` size appears in `test_logs.py` (lines 178, 191) and `test_responsive.py` (line 186) as "narrow viewport" for truncation tests; `2400×600` appears in `test_logs.py` (line 207) as "wide viewport." These are named concepts (narrow/wide) that warrant constants.

**`"2024-01-01T00:00:00"` 11+ times in `conftest.py`** — Confirmed. Every entity's `last_changed`/`last_updated` in seed data uses this identical literal across 12 occurrences. A `_SEED_TIMESTAMP` constant is clearly warranted.

**`_ENTITY` / `_DOMAIN` in 5 system test files** — Confirmed. Exact copies of `_ENTITY = "light.kitchen_lights"` and `_DOMAIN = "light"` in `test_api.py`, `test_app_lifecycle.py`, `test_bus.py`, `test_state_proxy.py`, `test_web_api.py`. Five identical definitions, no shared source.

**`PAGES` constant defined but never used in `test_navigation.py`** — Confirmed dead code. `PAGES` is defined at line 13 as a list of 3-tuples and never referenced anywhere else in the file. `SIDEBAR_LINKS` and `SIDEBAR_ACTIVE` serve the actual parametrization.

**Empty `# App filter` section header in `test_logs.py`** — Confirmed. A duplicate `# App filter` section header block (lines 240-243) exists with no tests under it, immediately before an `# Error toast` section. A second `# App filter` header at line 268 has actual tests. The first is dead markup.

**Duplicate tests in `test_hot_reload.py`** — Confirmed. `test_spa_navigates_without_full_reload` and `test_spa_handles_direct_deep_link` exist in both `test_hot_reload.py` and `test_navigation.py` with the same names. The `test_navigation.py` versions are strict supersets. Pytest collects both, silently running them twice.

**Underscore-prefixed module-level helpers in e2e test files** — Confirmed. `_open_status_filter`, `_open_palette`, `_wait_for_log_entries`, `_clear_theme_pref` are module-level helper functions with underscore prefixes called from multiple tests.

**Underscore-prefixed pytest fixtures in e2e `conftest.py`** — Confirmed. `_log_handler` (line 130), `_ensure_spa_built` (line 172), `_fastapi_app` (line 227), `_set_time_preset_to_1h` (line 291) are pytest fixtures — their names appear in test function signatures, making the underscore prefix misleading.

**Underscore-prefixed helpers and class in `system/conftest.py`** — Confirmed. `_session_ready`, `_ws_probe`, `_SystemTestConfig` are all directly referenced by name from other fixtures and should not have the prefix.

**Underscore-prefixed inner closures in `test_bus.py` (system)** — Confirmed. `async def _capture(...)` variants at 10 locations are local closures inside test function bodies. While these are inner closures (borderline per validation rules), the project's absolute no-underscore rule applies here and `capture` / `capture_a` / `capture_b` is clearly better.

**Underscore-prefixed callbacks in `test_scheduler.py` (system)** — Confirmed. `async def _callback()` and `async def _row_exists()` are inner closures; same reasoning as above.

**`_enable_autodetect` and `_find_app` in `test_app_lifecycle.py`** — Confirmed. Both are module-level helper functions called directly in tests.

**`self._greeting` in `apps/config_app.py`** — Confirmed. An underscore-prefixed instance attribute with no reason for the prefix.

**`"127.0.0.1"` repeated 4 times without constant** — Confirmed. Four occurrences in `conftest.py` (lines 248, 269, 276, 383) with no `_SERVER_HOST` constant.

**`datetime` import in `system/test_api.py`** — Confirmed rule violation. `from datetime import UTC, datetime, timedelta` at line 3; the project rule requires `whenever` for all date/time operations. The usage at line 94 should use `Instant.now().subtract(seconds=120)`.

**Repeated `wait_for_state_proxy_ready` lambda in `test_state_proxy.py` and `test_reconnection.py`** — Confirmed. The same `lambda: state_proxy.is_ready() and len(state_proxy.states) > 0` with `timeout=15.0` appears 5 times across two files. A shared helper in conftest would eliminate all five.

**`page.goto(...) + page.wait_for_load_state("networkidle")` repeated 30+ times** — Confirmed. The two-line navigation pattern appears throughout `test_url_routing.py`, `test_navigation.py`, and `test_app_detail.py` with no shared helper.

### False Positives

**`HA_URL = "http://localhost:18123"` in `system/conftest.py`** — FALSE POSITIVE as a nitpick finding. The report acknowledges it's a constant, not a buried literal. The port-synchronization concern with `docker-compose.yml` is real but too speculative for a style audit.

**`import re` in `test_apps_list.py`** — FALSE POSITIVE. The import IS used (line 58, `re.compile(...)`). The nitpicker's suggestion to replace `re.compile(r"/apps/my_app")` with a plain string is debatable — `to_have_url(re.compile(...))` is the conventional Playwright pattern for URL prefix matching. Not a violation.

**`base_url="http://localhost:8126"` in `mock_fixtures.py`** — FALSE POSITIVE for a style audit. This is a configuration value in test infrastructure, not a magic number in a test body. It's in an appropriate location.

**`test_config.py` — 7 near-identical tests** — BORDERLINE (see below), but the "collapse into parametrize" suggestion requires verifying that each test genuinely asserts only one thing about the page. The structure may be intentional for test isolation and failure legibility.

### Borderline

**`wait_for_timeout(300)` / `wait_for_timeout(500)` as named constants** — These are Playwright animation-settle waits. The nitpicker is right that naming them would help, but the semantic distinction between "filter settle" and "animation settle" is genuinely ambiguous in some locations — some `300` calls follow filter changes, others follow navigation. A single sweeping rename may misclassify some. Confirmed as a real improvement opportunity but with the caveat that the constant names need verification per call site.

**`test_config.py` seven near-identical tests** — BORDERLINE. One-test-per-assertion is a valid pattern for E2E tests where each navigation+assertion pair is independently meaningful for failure diagnosis. Parametrizing would reduce test count but make individual failures harder to diagnose. The finding is valid as a style observation but the suggested fix has a tradeoff.

---

## Aggregate Summary

| Report | Confirmed | False Positives | Borderline |
|---|---|---|---|
| tests/unit/core/ and bus/ | 17 finding clusters | 4 | 2 |
| tests/unit/ remaining | 10 finding clusters | 3 | 2 |
| tests/integration/ | 16 finding clusters | 5 | 3 |
| tests/e2e/ and system/ | 18 finding clusters | 5 | 3 |
| **Total** | **61** | **17** | **10** |

### Key false positives to note

1. **Inner closures (`_noop`, `_work`, `_blocked`, `_track_*`)** — The underscore-prefix rule applies to module-level and class-level names. All cited examples are inner closures at method-body indentation. BORDERLINE at worst, not confirmed violations.

2. **`test_conditions.py` near-duplicates** — The "comprehensive" vs standalone condition tests use different test data and test subtly different edge cases. Not duplicate.

3. **Cross-file string constants** — `"light.kitchen"`, `"test_owner"`, `"my_app"` appearing in different test files testing different features is intentional isolation, not duplication. The findings are only valid within a single file.

4. **`test_mappers.py` magic numbers** — `42`, `123.4`, `100`, `5`, `300.0` are arbitrary distinguishable values in a pass-through field test factory. No constant would add clarity.

5. **`# noqa: F401` fixture re-exports** — Correct pytest pattern, not a finding.

### Highest-confidence confirmed findings (act on these first)

1. **Lazy imports in `test_listeners.py`** — 12 in-method imports of `RateLimiter`. Single highest-density violation.
2. **`test_spa_navigates_without_full_reload` and `test_spa_handles_direct_deep_link` in `test_hot_reload.py`** — Duplicate tests being run twice silently.
3. **`PAGES` dead constant in `test_navigation.py`** — Confirmed dead code.
4. **`datetime` import in `system/test_api.py`** — Rule violation (must use `whenever`).
5. **`_ENTITY`/`_DOMAIN` in 5 system files** — Easy shared-constant extraction.
6. **Empty `# App filter` section in `test_logs.py`** — Dead section header, remove.
7. **Redundant `@pytest.mark.asyncio` decorators** — 28+ confirmed across 7+ files; mechanical removal with `asyncio_mode = "auto"`.
8. **`_make_scheduler()` / `_noop` / `_PATCH_TARGET` triplicated in scheduler tests** — Easy conftest extraction that eliminates the most concentrated duplication.
