# Codebase Nitpick Audit — 2026-05-21

Full-codebase style and hygiene audit across 12 scope chunks. Each chunk was reviewed by an independent subagent using the nitpicker checklist (10 categories). Individual reports are in this directory.

## Reports

| # | Chunk | Scope | Findings | Report |
|---|---|---|---|---|
| 1 | backend-core | `src/hassette/core/` | 51 | [backend-core.md](backend-core.md) |
| 2 | backend-test-utils-models | `src/hassette/test_utils/` + `models/` | 66 | [backend-test-utils-models.md](backend-test-utils-models.md) |
| 3 | backend-event-system | `src/hassette/bus/` + `event_handling/` + `events/` | 39 | [backend-event-system.md](backend-event-system.md) |
| 4 | backend-api-web | `src/hassette/api/` + `web/` | 54 | [backend-api-web.md](backend-api-web.md) |
| 5 | backend-scheduler-resources | `scheduler/` + `task_bucket/` + `resources/` + `app/` + `state_manager/` | 48 | [backend-scheduler-resources.md](backend-scheduler-resources.md) |
| 6 | backend-support | `utils/` + `config/` + `conversion/` + `types/` + `const/` + `migrations/` | 78 | [backend-support.md](backend-support.md) |
| 7 | frontend-components | `frontend/src/components/` | ~61 | [frontend-components.md](frontend-components.md) |
| 8 | frontend-pages-hooks | `frontend/src/pages/` + `hooks/` + `api/` + `utils/` + `state/` | 69 | [frontend-pages-hooks.md](frontend-pages-hooks.md) |
| 9 | tests-unit-core-bus | `tests/unit/core/` + `tests/unit/bus/` | ~60 | [tests-unit-core-bus.md](tests-unit-core-bus.md) |
| 10 | tests-unit-remaining | `tests/unit/resources/` + `web/` + `scheduler/` + `tools/` + `conversion/` + `events/` | ~58 | [tests-unit-remaining.md](tests-unit-remaining.md) |
| 11 | tests-integration | `tests/integration/` | ~24 grouped findings (100+ instances) | [tests-integration.md](tests-integration.md) |
| 12 | tests-e2e-system | `tests/e2e/` + `tests/system/` | ~59 | [tests-e2e-system.md](tests-e2e-system.md) |

**Estimated total: ~600+ individual findings across ~130k lines of code.**

---

## Cross-Cutting Themes

These patterns appear across multiple chunks and represent the highest-leverage cleanup opportunities.

### 1. Underscore-Prefixed Names (PERVASIVE — project rule violation)

The single most common finding across the entire codebase. The project rule is absolute: no `_` prefixes in application code (personal projects, not libraries).

- **Production code:** `_async_handler`, `_injector`, `_record_timing`, `_debounced_call`, `_throttled_call`, `_Color`, `_NESTED_GROUPS`, `_merge_exclude`, `_make_union`, `_type_sort_key` (bus, event_handling, conversion, config, utils)
- **Test code:** 70+ instances in unit tests, 35+ in integration, 30+ in e2e/system. Factory functions (`_make_executor`, `_make_bus_service`, `_make_scheduler`), inner classes (`_DummyService`, `_ConcreteResource`), handler methods (`_on_change`, `_handler_a`), constants (`_ENTITY`, `_DOMAIN`, `_PATCH_TARGET`)
- **Fixtures:** `_log_handler`, `_ensure_spa_built`, `_fastapi_app`, `_set_time_preset_to_1h`

### 2. Lazy Imports (project rule violation)

Imports inside function bodies instead of at module level. The only permitted exception is `TYPE_CHECKING` guards.

- **Production:** `annotation_converter.py`, `state_registry.py`, `validation.py`, `type_utils.py`, `app_utils.py`, `events/hass/hass.py`, `predicates.py`, `resources/base.py`
- **Tests:** `test_listeners.py` (~12 sites), `test_bus.py` (~6), `test_app_test_harness.py` (~7), `test_bus_immediate.py` (5), `test_predicates.py` (12+), `test_ws_helpers.py`, `test_direct_status_assignments.py`

### 3. Section Divider Comments (style rule violation)

`# --- section name ---` or `# ============` blocks used as visual separators. Project style prohibits these.

- Found in 25+ files across production code (`harness.py`, `app_harness.py`, `test_server.py`, `mixins.py`) and tests (12+ unit test files, 10 integration test files)

### 4. Duplicate Factory/Helper Functions Across Test Files

The same helper defined independently in multiple test files instead of living in conftest or a shared module.

- `_make_executor()` — 3 command executor test files
- `_make_scheduler_service()` — 4-5 scheduler test files
- `_make_bus_service()` — 2 bus service test files
- `_make_scheduler()` — 2 unit scheduler files
- `_ConcreteResource` — 2 resource test files (empty conftest exists)
- `_make_job_summary()` — 2 telemetry test files
- `_make_manifest_mock()` — 2 API config test files
- `_make_mock_listener()` / `_make_mock_job()` — 3+ files
- `_noop` — 3 scheduler test files

### 5. Files Over Size Limits

**Over 800 lines (hard ceiling):**
- `src/hassette/bus/bus.py` — 1,122 lines
- `src/hassette/core/command_executor.py` — 976 lines
- `src/hassette/core/bus_service.py` — 947 lines
- `src/hassette/core/telemetry_query_service.py` — 903 lines
- `src/hassette/core/telemetry_repository.py` — 838 lines
- `src/hassette/resources/base.py` — 828 lines
- `src/hassette/test_utils/recording_api.py` — 1,159 lines
- `tests/unit/core/test_lifecycle_propagation.py` — 953 lines
- `tests/integration/test_web_api.py` — 1,393 lines

**Over 400 lines (typical ceiling):**
- `src/hassette/utils/app_utils.py` — 517 lines
- `src/hassette/utils/type_utils.py` — 416 lines
- `src/hassette/scheduler/scheduler.py` — 774 lines

### 6. Magic Numbers and Hard-Coded Values

Most pervasive in:
- **Timeouts/delays:** `wait_for_timeout(300)` ×21, `wait_for_timeout(500)` ×15, `timeout=5000` ×37 in e2e tests
- **Retry counts:** `stop_after_attempt(5)` duplicated in 2 backend files
- **Time calculations:** `86400` and `3600.0` as bare literals in telemetry code
- **Test data:** `"my_app"` ×20, `1700000000.0` in 3 files, `"light.kitchen"` across 4+ bus test files, `"state_changed"` ×20 in `test_router.py`
- **CSS:** `font-size: 10px` in 6 module CSS files, `400px` drawer width as independent literals in 2 files
- **Docker paths:** `/srv/hassette/data`, `/config`, `/apps` as bare literals

### 7. Dead `@pytest.mark.asyncio` Decorators

Project uses `asyncio_mode = "auto"` in `pyproject.toml`, making explicit `@pytest.mark.asyncio` decorators redundant. Found in ~25+ tests across `test_lifecycle_transitions.py`, `test_emit_readiness_event.py`, `test_lifecycle_side_effect_free.py`, `test_start_children_and_wait.py`, and scattered elsewhere.

### 8. Redundant/Dead Code

- 5 unused `LOGGER = getLogger(__name__)` in core module
- Dead CSS classes (~14) in `config-tab.module.css`
- `compute_health_metrics` in `telemetry_helpers.py` never called (logic duplicated inline)
- Duplicate tests in `test_hot_reload.py` (subsets of `test_navigation.py` tests)
- Unused `PAGES` constant in `test_navigation.py`
- Copy-pasted collision-detection block in `bus.py` (lines 197-206 and 372-381)

### 9. Ternary Abuse (Frontend)

5 locations with 2-3 level nested ternaries in JSX: `recent-activity-section.tsx`, `unified-handler-row.tsx`, `config-tab.tsx`, `handler-list.tsx`, `job-detail.tsx`. Plus double-ternary `windowSeconds` in `apps.tsx`.

### 10. Variable Shadowing

- `wait_for = asyncio.Event()` shadows imported `wait_for` utility in `test_state_proxy.py` (4+ sites)
- `isFailing` local boolean shadows imported `isFailing` function in frontend component

---

## Validation Results

Three independent validation subagents reviewed all findings against the actual code.

| Domain | Total Findings | Confirmed | False Positives | Borderline | FP Rate |
|---|---|---|---|---|---|
| Backend (6 reports) | 336 | 315 | 21 | — | 6% |
| Frontend (2 reports) | ~139 | ~81 | ~19 | ~39 taste | 14% |
| Tests (4 reports) | ~88 clusters | 61 | 17 | 10 | 19% |

**Overall: ~90% of findings confirmed as real issues after validation.**

Detailed validation reports:
- [validation-backend.md](validation-backend.md)
- [validation-frontend.md](validation-frontend.md)
- [validation-tests.md](validation-tests.md)

### Common false positive patterns found

- **Pydantic field defaults** — named config fields (`host`, `port`, `cors_origins`, `app_shutdown_timeout_seconds`) are not magic numbers (10 backend FPs)
- **Arbitrary test data** — `entity_id=42`, `timeout=5`, `"light.kitchen"` across different test files is intentional isolation, not duplication
- **Inner closure underscores** — `_noop`, `_handler` inside test function bodies (8-space indent) are not module-level names; the rule targets methods and module-level functions
- **CSS proportional values** — `em` padding in badge/button modules is idiomatic sizing, not magic numbers
- **Dead code that's used outside scope** — `TEST_SOURCE_LOCATION`, `SECONDS_PER_DAY` used in test files beyond the reviewed chunk's scope
