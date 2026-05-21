# Nitpick Report: tests/unit — remaining directories

**Scope:** `tests/unit/resources/`, `tests/unit/web/`, `tests/unit/scheduler/`,
`tests/unit/tools/`, `tests/unit/conversion/`, `tests/unit/events/`

---

## 1. Magic Numbers and Strings

**`test_mappers.py:194–195`** — `42` and `123.4` appear as defaults in `_make_system_status()` and are then asserted verbatim at lines 212 and 214. They also reappear unrelated at line 263 (`42.5`). No constant for what any of these values represent.

**`test_mappers.py:251`** — `100`, `5`, `300.0` used as named-field values in `_make_system_status(entity_count=100, app_count=5, uptime_seconds=300.0)` and immediately asserted at lines 256–258. Three separate arbitrary values in one call site with no constants.

**`test_scheduler_error_handler.py:9` and `test_scheduler_timeout_threading.py:34`** — `_PATCH_TARGET = "hassette.scheduler.scheduler.capture_registration_source"` is defined identically in both files. Same string constant, two definitions.

**`test_generate_constraints.py:67,73`** — `"0.24.0"` as `hassette_version` default and in explicit calls. The version string also appears inside `SIMPLE_PYPROJECT`, `PYPROJECT_WITH_EXTRAS`, `PYPROJECT_MULTI_EXTRAS`, `PYPROJECT_NO_DEPS` as the `version = "0.24.0"` field — 7 occurrences total. Should be a single module-level constant.

---

## 2. Scattered Constants

**`test_scheduler_error_handler.py:32–33` and `test_scheduler_timeout_threading.py:30–31`** — `async def _noop() -> None: pass` is defined identically in both files. Also defined in `test_scheduled_job_timeout.py:39–41` as an async noop. Three identical one-body helper functions that belong in the scheduler test package's `conftest.py` (which doesn't exist — the `tests/unit/scheduler/` directory has no `conftest.py`).

**`test_scheduler_error_handler.py` and `test_scheduler_timeout_threading.py`** — `_make_scheduler()` body is near-identical across both files (the only difference is one extra line initializing `scheduler._error_handler = None`). 18 lines of boilerplate copied between two sibling files that share a conftest.

**`test_scheduled_job_timeout.py:91–96` and `test_scheduler_error_handler.py:36–41`** — Two pairs of error handler stubs (`_error_handler_a`/`_error_handler_b` vs `_handler_a`/`_handler_b`) serve the same purpose — named distinct async callables for identity comparisons. Same concept, different names, in two files.

**`test_emit_readiness_event.py:16–21` and `test_lifecycle_side_effect_free.py:9–14`** — `class _ConcreteResource(Resource)` with identical body (`async def on_initialize(self) -> None: pass`) defined independently in two files. Should be in `tests/unit/resources/conftest.py`, which currently exists but is empty.

---

## 3. Ternary Abuse

**`test_generate_sync_facade.py:24`** — `callable_ = job if job is not None else (lambda: None)` — ternary is fine here, but the outer parens around `(lambda: None)` are noise.

---

## 4. CSS

(Skip — no CSS files in scope.)

---

## 5. Dead Code

**`test_ws_helpers.py:25`** — `import anyio` is a lazy import inside `test_anyio_closed_resource_error`. Project rule prohibits lazy imports. This is inside a test method body, not under `TYPE_CHECKING`. Move to top of file.

**`test_direct_status_assignments.py:35`** — `from hassette.resources.mixins import LifecycleMixin` is a lazy import inside `test_harness_status_bypass`. Should be at the module level.

**`test_lifecycle_propagation.py:123`** — `_shutdown_order: list[str] = []` is module-level mutable shared state. Same for `_init_order: list[str] = []` at line 331. Both require manual `.clear()` calls scattered through the tests (lines 162, 187, 330, 378, 400, 409, 450). Each test that forgets to clear first is implicitly coupled to test execution order. These belong as fixtures or local variables.

**`test_lifecycle_transitions.py:308–315`** — `original_setter` / `_capturing_setter` monkey-patch in `test_shutdown_stopping_then_stopped_sequence` modifies `type(resource).status` in place, with a `try/finally` restore. The restore correctly happens, but the approach patches the class descriptor, not the instance — if the test is interrupted before the `finally` block (e.g., by a hard crash), the class is left in a patched state that affects any other test using `_SimpleResource` in the same process. Not dead code, but a fragile pattern worth flagging.

**`resources/conftest.py`** — File exists, contains only a module docstring, has no fixtures. Empty conftest with no content beyond a docstring is noise, especially given that `_ConcreteResource` duplication across two files in this directory is the exact problem a shared conftest is meant to solve.

---

## 6. Naming Inconsistencies

**Underscore-prefixed module-level helpers** — The project rule is no underscore prefixes. Every module-level test helper function and test resource class in scope uses `_` prefixes. Complete list:

- `test_lifecycle_transitions.py`: `_SimpleResource`, `_SimpleService`
- `test_lifecycle_side_effect_free.py`: `_ConcreteResource`
- `test_emit_readiness_event.py`: `_ConcreteResource`, `_make_resource`
- `test_start_children_and_wait.py`: `_Parent`, `_ReadyOnInit`, `_NeverReady`
- `test_serve_wrapper_shutdown.py`: `_ClosedResourceService`
- `test_lifecycle_propagation.py`: `_make_leaf`, `_make_dummy_job`, `_TotalTimeoutRoot`
- `test_mappers.py`: `_make_instance`, `_make_manifest`, `_make_system_status`, `_make_listener_summary`
- `test_telemetry_helpers.py`: `_listener`
- `test_scheduled_job_timeout.py`: `_make_job`, `_noop`, `_error_handler_a`, `_error_handler_b`
- `test_scheduler_error_handler.py`: `_make_scheduler`, `_noop`, `_handler_a`, `_handler_b`
- `test_scheduler_timeout_threading.py`: `_make_scheduler`, `_noop`
- `test_error_context.py`: `_make_scheduler_error_context`
- `test_generate_sync_facade.py`: `_parse_func`, `_rewrite_body`, `_body_as_source`, `_RECORDING_API_PATH`, `_API_PATH`

**`test_scheduler_error_handler.py:36,40` vs `test_scheduled_job_timeout.py:91,95`** — Same concept (pair of named error handler callables for identity tests), inconsistent naming: `_handler_a`/`_handler_b` vs `_error_handler_a`/`_error_handler_b`.

**`test_lifecycle_propagation.py:739–745`** — `HookTrackingParent._on_children_stopped` overrides a framework method that has an underscore prefix. The override must match the framework's name so this is forced — but the companion flag attribute is named `hook_called` (no prefix). This is fine and consistent.

---

## 7. Structural Messiness

**`test_lifecycle_propagation.py`** — 953 lines. Exceeds the 800-line ceiling. The file covers at least four distinct concerns: shutdown propagation, initialization propagation, leaf readiness, and total-timeout behavior. The total-timeout section starting at line 814 introduces a large `_TotalTimeoutRoot` helper class (90 lines) and four test functions — that cluster alone is a natural split point.

**`test_lifecycle_propagation.py:817–863`** — `_TotalTimeoutRoot` is a 47-line test helper class that reimplements the core shutdown logic of `Hassette` itself. It has 8 tracking attributes and a custom `shutdown()` override that mirrors production code. This is the kind of class that belongs in a dedicated file or at minimum warrants a comment explaining why reimplementation is necessary rather than using the real `Hassette`.

**`test_lifecycle_transitions.py:300–326`** — `test_shutdown_stopping_then_stopped_sequence` is a 27-line test that monkey-patches a class-level property descriptor. The complexity here is high relative to what it asserts (that STOPPING precedes STOPPED), and the `type(resource).status = property(...)` mutation approach is not obvious to a reader.

**`test_generate_sync_facade.py`** — Uses numbered section divider comments (`# Test 1:`, `# Test 2:`, etc. via `# ---------------------------------------------------------------------------`). The numbers in the section headers (`Test 1`, `Test 2`, ...) don't correspond to test function names, which don't carry the numbers. If a test is inserted between two existing ones, the numbering drifts.

**`test_scheduler_error_handler.py:96–120`** — `test_convenience_methods_pass_on_error` tests all 7 convenience methods in a single function body with 7 separate `scheduler.*()` calls and 7 assertions. This is a parameterize candidate:
```python
@pytest.mark.parametrize("method,kwargs", [
    ("run_in", {"delay": 60}),
    ("run_every", {"seconds": 30}),
    ...
])
```

**`test_lifecycle_transitions.py`** — All 16 async test functions are decorated with `@pytest.mark.asyncio` (lines 51, 70, 87, etc.), but `pyproject.toml` sets `asyncio_mode = "auto"`. The decorators are redundant on every function. Same issue in:
- `test_emit_readiness_event.py`: 2 redundant `@pytest.mark.asyncio` decorators
- `test_lifecycle_side_effect_free.py`: 2 redundant `@pytest.mark.asyncio` decorators
- `test_start_children_and_wait.py`: 4 redundant `@pytest.mark.asyncio` decorators

Other resource test files (`test_lifecycle_propagation.py`, `test_service_lifecycle.py`, `test_serve_wrapper_shutdown.py`) correctly omit these decorators.

---

## 8. Import Hygiene

**`test_ws_helpers.py:25`** — `import anyio` inside a test method body. Already flagged under Dead Code, repeated here: lazy import violating project rule.

**`test_direct_status_assignments.py:35`** — `from hassette.resources.mixins import LifecycleMixin` inside `test_harness_status_bypass` function body. Lazy import.

**`test_emit_readiness_event.py:3–13`** — Import ordering has `from typing import TYPE_CHECKING` and `from unittest.mock import AsyncMock` before `import pytest`, but then `from hassette.test_utils import make_mock_hassette` appears after the `if TYPE_CHECKING:` block. The `make_mock_hassette` import is a regular runtime import placed after the conditional block, disrupting the conventional top-of-file grouping. Standard pattern would put all unconditional hassette imports together before the `if TYPE_CHECKING:` block.

**`test_generate_sync_facade.py:15–18`** — `sys.path.insert(0, ...)` at module level followed by an `# noqa: E402` on the subsequent import. This is a necessary workaround for the codegen package's location, but the module-level mutation of `sys.path` is a code smell. A comment explaining why this is needed (and why a conftest `sys.path` fixture wasn't used instead) is absent.

---

## 9. Hard-Coded Environment Values

**`test_generate_constraints.py:13–25`** — `SIMPLE_PYPROJECT` hardcodes `version = "0.24.0"` and the same string appears in `PYPROJECT_WITH_EXTRAS`, `PYPROJECT_MULTI_EXTRAS`, `PYPROJECT_NO_DEPS`. If hassette's version changes, test fixture content becomes stale in a confusing way. The version string in these fixtures is used as fake pyproject content — a version-agnostic placeholder like `"0.1.0"` would be less misleading than tracking the real version.

---

## 10. Formatting Inconsistencies

**Section divider comments** — Used inconsistently across the scope. Files that use them: `test_mappers.py` (5 pairs), `test_telemetry_helpers.py` (2 pairs), `test_generate_sync_facade.py` (12 pairs), `test_generate_constraints.py` (3 pairs), `test_registry_validation.py` (1 pair), `test_direct_status_assignments.py` (1 pair). Files that use class-based grouping instead: `test_lifecycle_transitions.py`, `test_service_lifecycle.py`, `test_scheduled_job_timeout.py`, etc. The project coding style says "no section divider comments" — the dividers in the test files are in violation.

**`test_scheduler_error_handler.py:53`** — `async def test_on_error_reset_on_initialize` inside class `TestSchedulerOnErrorMethod`. The class methods mix async and sync test functions (3 sync, 1 async) without a pattern distinction. The async one needs `await scheduler.on_initialize()` while others don't. Fine functionally, but visually inconsistent when scanned.

**`test_lifecycle_propagation.py:814–815`** — `FinalMeta.LOADED_CLASSES.add(...)` appears as a bare module-level statement immediately before `class _TotalTimeoutRoot`. This registration side effect is easy to miss and has no companion cleanup. If the test module is imported more than once (e.g., via pytest-xdist workers), the registration is idempotent, but the pattern is fragile. Same approach is used in `test_service_lifecycle.py` (lines 148, 165) for `_BadSubclass` registrations, but those use `FinalMeta.LOADED_CLASSES.discard(key)` inside each test — inconsistent pattern between files.

---

## Summary

| Category | Count | Files Most Affected |
|---|---|---|
| Magic Numbers and Strings | 4 findings | `test_mappers.py`, `test_generate_constraints.py`, scheduler tests |
| Scattered Constants | 4 findings | scheduler tests, `tests/unit/resources/` (empty conftest) |
| Ternary Abuse | 1 finding | `test_generate_sync_facade.py` |
| Dead Code | 5 findings | `test_ws_helpers.py`, `test_direct_status_assignments.py`, `test_lifecycle_propagation.py` |
| Naming Inconsistencies | 30+ underscore-prefixed helpers | All files |
| Structural Messiness | 6 findings | `test_lifecycle_propagation.py`, `test_lifecycle_transitions.py`, scheduler tests |
| Import Hygiene | 4 findings | `test_ws_helpers.py`, `test_direct_status_assignments.py`, `test_emit_readiness_event.py`, `test_generate_sync_facade.py` |
| Hard-Coded Environment Values | 1 finding | `test_generate_constraints.py` |
| Formatting Inconsistencies | 3 findings | `test_mappers.py`, `test_lifecycle_propagation.py`, multiple |

**Highest-impact single cleanup:** Create `tests/unit/scheduler/conftest.py` with `make_scheduler`, `noop`, and `PATCH_TARGET` — eliminates the duplicated `_make_scheduler` body, three `_noop` definitions, and two `_PATCH_TARGET` definitions across three files in one pass.

**Second highest:** Move the 20 redundant `@pytest.mark.asyncio` decorators out of `test_lifecycle_transitions.py`, `test_emit_readiness_event.py`, `test_lifecycle_side_effect_free.py`, and `test_start_children_and_wait.py` — pure noise given `asyncio_mode = "auto"`.
