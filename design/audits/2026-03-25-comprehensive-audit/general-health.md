# Hassette Codebase Health Audit

**Date:** 2026-03-25
**Scope:** `src/hassette/` (24,797 lines across 126 files), `tests/` (20,903 lines across 93 files), CI/config
**Branch:** audit worktree

## Summary

The codebase is generally well-structured with good separation of concerns, thorough docstrings, proper type hints, and a solid CI pipeline testing across Python 3.11-3.13. The async-first architecture is consistently applied.

Key concerns: two files exceed the 800-line threshold, a major duplication pattern in `command_executor.py`, several core services lack dedicated test files, coverage threshold is not enforced in CI, and production code uses `assert` statements that will be silently disabled under `-O`.

**Findings by severity:** 1 CRITICAL, 5 HIGH, 9 MEDIUM, 6 LOW

---

## CRITICAL

### 1. Coverage threshold not enforced in CI

**Location:** `pyproject.toml:138`

```
# fail_under = 85 # local default; CI can override
```

The coverage threshold is commented out and no CI workflow enforces a minimum. Coverage can silently regress with every merge. Given the number of untested core services (see HIGH #2), this is the mechanism that would catch drift.

**Recommendation:** Uncomment `fail_under = 85` in `pyproject.toml` (or set it in the CI workflow). Add it as a step in the `combine-and-report` job in `.github/workflows/tests.yml`.

---

## HIGH

### 1. `command_executor.py` has near-identical error handling duplicated across two methods (88+83 lines)

**Location:** `src/hassette/core/command_executor.py:112-283`

`_execute_handler()` (88 lines) and `_execute_job()` (83 lines) contain identical exception-handling branches (CancelledError, DependencyError, HassetteError, Exception, success) that differ only in the record type (`HandlerInvocationRecord` vs `JobExecutionRecord`) and the logging message. This is a maintenance hazard -- any change to the error handling contract must be applied in both places.

**Recommendation:** Extract a generic `_execute_with_recording()` method that accepts the callable, a record factory function, and context for log messages. The two public methods become thin wrappers.

### 2. Core services with no dedicated test files

**Location:** Multiple files totaling ~1,477 lines of untested code:

| File | Lines |
|------|-------|
| `core/bus_service.py` | 504 |
| `core/scheduler_service.py` | 527 |
| `core/api_resource.py` | 193 |
| `core/app_handler.py` | 131 |
| `core/web_api_service.py` | 82 |
| `core/commands.py` | 40 |

These are core infrastructure services. While some may be exercised indirectly through integration tests, they have no dedicated unit test files. `bus_service.py` and `scheduler_service.py` are especially concerning at 500+ lines each -- they contain complex async logic (priority dispatch, heap queues, service lifecycle) that warrants focused testing.

**Recommendation:** Add targeted unit tests for `bus_service.py` and `scheduler_service.py` as the highest priority. These services orchestrate the entire event and scheduling pipeline.

### 3. `api.py` exceeds 800-line limit (880 lines, 39 methods)

**Location:** `src/hassette/api/api.py`

The `Api` class has 39 methods and is 880 lines. It serves as both the user-facing API surface and the internal implementation, combining state access, service calls, event firing, history queries, entity management, and WebSocket communication.

**Recommendation:** Group methods into logical submodules (state operations, service calls, history, entity management) or split into mix-in classes. The existing `ApiSyncFacade` pattern shows this is already partially done for the sync interface.

### 4. `bus.py` is the second-largest file (831 lines, 27 methods)

**Location:** `src/hassette/bus/bus.py`

The `Bus` class has 27 methods, most of which are thin convenience wrappers (`on_state_change`, `on_attribute_change`, `on_call_service`, `on_websocket_connected`, etc.) that all delegate to the core `on()` method. While each is short, the sheer count makes the file hard to navigate.

**Recommendation:** Consider generating the convenience methods from a declarative mapping, or splitting them into a mix-in class (e.g., `BusConvenienceMixin`).

### 5. `telemetry_query_service.py` has duplicated SQL query branches (532 lines)

**Location:** `src/hassette/core/telemetry_query_service.py:156-255, 257-335`

`get_all_app_summaries()` and `get_global_summary()` each contain a full if/else branch that duplicates the entire SQL query -- the only difference is whether a `WHERE session_id = ?` clause and parameter are included. This doubles the query surface area that must be maintained.

**Recommendation:** Use conditional query building (e.g., append `AND hi.session_id = ?` only when `session_id is not None`) or a small query builder function that returns `(sql, params)`.

---

## MEDIUM

### 1. Production `assert` statements will be silently disabled under `python -O`

**Location:** 17 occurrences across 9 non-test files, including:
- `src/hassette/api/api.py:289,344,354,364,684` -- API response validation
- `src/hassette/core/websocket_service.py:316,334,341` -- WebSocket preconditions
- `src/hassette/core/scheduler_service.py:287` -- scheduling invariant
- `src/hassette/core/bus_service.py:322-325` -- event routing checks
- `src/hassette/bus/bus.py:133` -- service initialization

If anyone runs with `PYTHONOPTIMIZE=1` or `python -O`, all of these checks disappear. The API response assertions (lines 289, 344, 354, 364) are especially dangerous -- they validate external data.

**Recommendation:** Replace `assert` with explicit `if not ...: raise ValueError(...)` or `TypeError(...)` for runtime-critical checks. Keep `assert` only for internal invariants that truly indicate programming errors (and even then, prefer explicit raises in production code).

### 2. Dead web response models

**Location:** `src/hassette/web/models.py:17-28, 78`

`EntityStateResponse`, `EntityListResponse`, and `EventEntry` are defined but never used anywhere in the codebase (not in routes, tests, or any other file).

**Recommendation:** Remove the dead models or wire them into the appropriate API endpoints.

### 3. Dead exception classes

**Location:** `src/hassette/exceptions.py:174, 219`

`DomainNotFoundError` and `ConvertedTypeDoesNotMatchError` are defined but never raised, caught, or referenced anywhere outside their definition file.

**Recommendation:** Remove unused exceptions. They add conceptual surface area with no functional value.

### 4. Mutable module-level dicts as caches

**Location:** `src/hassette/utils/app_utils.py:30-31`

```python
LOADED_CLASSES: "dict[tuple[str, str], type[App[AppConfig]]]" = {}
FAILED_TO_LOAD_CLASSES: "dict[tuple[str, str], Exception]" = {}
```

These are mutable module-level dictionaries that persist across the process lifetime. They can leak references to classes and exceptions from previous load attempts, and they require the `reset` module in test_utils to clean up between tests.

**Recommendation:** Consider moving these into the `Hassette` instance or a scoped registry that follows the instance lifecycle, rather than module-level globals.

### 5. Duplicated `LOG_LEVELS` dictionary

**Location:** `src/hassette/core/runtime_query_service.py:32` and `src/hassette/web/routes/ws.py:17`

The same `{"DEBUG": 10, "INFO": 20, ...}` dictionary is defined in two separate files. Changes to one will not propagate to the other.

**Recommendation:** Extract to a shared constant (e.g., in `hassette/const/misc.py` or `hassette/logging_.py`) and import from both locations. Or use `logging.getLevelName()` / `logging.getLevelNamesMapping()` from the stdlib.

### 6. `run_apps_pre_check()` is 114 lines with 3 nested helper functions

**Location:** `src/hassette/utils/app_utils.py:36-149`

This function defines 3 nested closures (`_root_cause`, `_find_user_frame`, `_log_compact_load_error`) and then the actual loop logic starting at line 118. The nested closures make it hard to test individual error formatting logic in isolation.

**Recommendation:** Extract the helper functions to module-level (they only need `app_dir` or `app_manifest` as parameters, both already passed explicitly). This would make them independently testable and reduce the function's apparent complexity.

### 7. `app_utils.py` is 518 lines with mixed responsibilities

**Location:** `src/hassette/utils/app_utils.py`

This file contains app pre-checking, manifest cleaning, auto-detection, class loading, and module resolution -- all conceptually related but functionally distinct. The auto-detection logic alone (`autodetect_apps`, 63 lines with 4-deep nesting) is a separate concern from class loading.

**Recommendation:** Split into focused modules: `app_loader.py` (class loading, pre-check), `app_discovery.py` (auto-detection, manifest cleaning).

### 8. Five functions with nesting depth of 5

**Location:**
- `src/hassette/resources/base.py:215` -- `_run_hooks`
- `src/hassette/core/websocket_service.py:135` -- `serve`
- `src/hassette/core/runtime_query_service.py:324` -- `broadcast`
- `src/hassette/core/app_registry.py:256` -- `get_full_snapshot`

These exceed the 4-level nesting limit. Most involve try/except + async with + for + if patterns.

**Recommendation:** Extract inner logic into helper methods to reduce nesting. For example, `get_full_snapshot` (83 lines, 5-deep) could break out the per-app snapshot building.

### 9. `api/sync.py` (503 lines) is auto-generated but checked in

**Location:** `src/hassette/api/sync.py`

Header says "Auto-generated ... Do not edit this file directly. Generated from `api.Api` by `tools/generate_sync.py`." but the file is tracked in git. If the generator and the checked-in file drift, there's no CI check to catch it.

**Recommendation:** Either add a CI step that regenerates `sync.py` and fails if the result differs from the committed version, or generate it at build time and `.gitignore` it.

---

## LOW

### 1. TODOs in production code (3 occurrences)

**Location:**
- `src/hassette/logging_.py:20` -- "TODO: remove coloredlogs and roll our own?"
- `src/hassette/core/app_handler.py:31` -- "TODO: handle stopping/starting individual app instances"
- `src/hassette/test_utils/fixtures.py:107` -- "TODO: see if we can get this to be module scoped"

**Recommendation:** Convert to GitHub issues for tracking. TODOs in code tend to be forgotten.

### 2. Pinned dependencies may block security patches

**Location:** `pyproject.toml:55,58`

```
"typing-extensions==4.15.*",
"whenever==0.9.*",
```

`typing-extensions` is pinned to `4.15.*` and `whenever` to `0.9.*`. While `whenever` is pre-1.0 (API instability justifies pinning), `typing-extensions` is a stable, widely-used package where patch-pinning may delay security or compatibility fixes.

**Recommendation:** Relax `typing-extensions` to `>=4.15` (or at least `>=4.15,<5`). Keep `whenever` pinned until its 1.0 release.

### 3. `_run_error_hooks` is a no-op stub

**Location:** `src/hassette/core/command_executor.py:285-287`

```python
async def _run_error_hooks(self, _exc: Exception, _cmd: InvokeHandler | ExecuteJob) -> None:
    """No-op stub for error hooks. Hook registration wired in #268."""
    pass
```

This stub is called from 6 places in the error handling code but does nothing. Issue #268 is referenced but may be stale.

**Recommendation:** Verify whether issue #268 is still planned. If not, remove the stub and its call sites to reduce noise.

### 4. `app_lifecycle_service.py` references folded-in class in docstring

**Location:** `src/hassette/core/app_lifecycle_service.py:1-5`

The module docstring references "WP02" and "AppLifecycleManager (folded in)" -- artifacts of the refactoring process that are confusing for new readers.

**Recommendation:** Update the docstring to describe the current state, not the migration history.

### 5. `HassetteConfig` allows `extra="allow"` by default

**Location:** `src/hassette/config/config.py:44`

The Pydantic settings model has `extra="allow"`, which means misspelled config keys are silently accepted. For example, `hassette__bse_url` (typo) would be accepted without warning.

**Recommendation:** Consider switching to `extra="ignore"` with a validation warning for unknown keys, or provide a strict validation mode.

### 6. No `py.typed` marker file

**Location:** `src/hassette/` (missing file)

The package declares `Typing :: Typed` in classifiers but does not include a `py.typed` marker file. Tools like Pyright and mypy use this file to determine whether to trust the package's type annotations.

**Recommendation:** Add an empty `src/hassette/py.typed` file and include it in the package distribution.
