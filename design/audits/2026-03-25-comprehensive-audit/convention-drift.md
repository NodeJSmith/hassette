# Hassette Codebase Convention Drift Audit

**Date:** 2026-03-25
**Scope:** `src/hassette/` and `tests/`
**Files analyzed:** ~140 source files, ~90 test files

## Executive Summary

The codebase is architecturally sound with a clean Resource/Service hierarchy and well-separated layers. However, incremental growth has introduced several categories of convention drift that compound into maintenance burden. The most significant issues are **module-level logger naming inconsistency** (split across three conventions), **`config_log_level` return type annotation drift** (half annotated, half not), and a **signature deviation in `ApiResource.on_shutdown`** that breaks the lifecycle hook contract. No critical duplication was found, but there are several medium-severity pattern inconsistencies that should be addressed in a single cleanup pass.

**Finding count:** 2 HIGH, 8 MEDIUM, 3 LOW

---

## HIGH Severity

### H1. `ApiResource.on_shutdown` signature deviates from lifecycle hook contract

**Location:** `src/hassette/core/api_resource.py:69`

```python
async def on_shutdown(self, *args, **kwargs) -> None:
```

Every other `on_shutdown` override in the codebase (11 total) uses the canonical signature `async def on_shutdown(self) -> None:`. The `*args, **kwargs` on `ApiResource` is dead code -- the caller (`Resource._run_hooks`) never passes positional or keyword arguments. This breaks the documented lifecycle contract and would silently swallow signature errors from callers.

Similarly, `on_initialize` at line 58 is missing its `-> None` return type annotation, unlike every other override.

**Recommendation:** Change to `async def on_shutdown(self) -> None:` and add `-> None` to `on_initialize`.

---

### H2. Module-level logger naming convention is split three ways

**Location:** Every file in `src/hassette/` that creates a module-level logger

The codebase uses three different patterns for module-level loggers:

| Pattern | Convention | Files using it |
|---|---|---|
| `LOGGER = getLogger(__name__)` | `from logging import getLogger` | 20 files (core/, app/, conversion/, state_manager/, etc.) |
| `logger = logging.getLogger(__name__)` | `import logging` | 7 files (web/routes/, web/utils.py, web/telemetry_helpers.py) |
| `LOGGER = logging.getLogger(__name__)` | `import logging` | 4 files (events/hass/, scheduler/classes.py, bus/injection.py, event_handling/accessors.py) |

The dominant convention (20 files) is `LOGGER = getLogger(__name__)` with `from logging import getLogger`. The web layer consistently uses `logger` (lowercase). But the mixed-import pattern (`LOGGER = logging.getLogger(...)`) appears in scattered files with no clear rationale.

**Recommendation:** Standardize on:
- **Core/domain code:** `LOGGER = getLogger(__name__)` with `from logging import getLogger`
- **Web layer:** `logger = logging.getLogger(__name__)` (lowercase, per web convention)

The 4 hybrid files (`events/hass/hass.py`, `scheduler/classes.py`, `bus/injection.py`, `event_handling/accessors.py`) should be migrated to the core convention.

---

## MEDIUM Severity

### M1. `config_log_level` return type annotation inconsistency

**Location:** All Resource/Service subclasses that override `config_log_level`

12 overrides include `-> str:` return type annotation; 11 overrides omit it. The base class in `resources/base.py:194` omits it.

**With annotation (12 files):**
- `core/bus_service.py`, `core/scheduler_service.py` (x2), `core/command_executor.py`, `core/runtime_query_service.py`, `core/app_handler.py`, `core/app_lifecycle_service.py`, `core/database_service.py`, `core/telemetry_query_service.py`

**Without annotation (11 files):**
- `resources/base.py`, `app/app.py`, `bus/bus.py`, `scheduler/scheduler.py`, `api/api.py`, `task_bucket/task_bucket.py`, `core/service_watcher.py`, `core/file_watcher.py`, `core/web_api_service.py`, `core/state_proxy.py`, `core/api_resource.py`, `core/websocket_service.py`

**Recommendation:** Add `-> str` to the base class and all overrides. This is a mechanical fix.

---

### M2. `TYPE_CHECKING` import guard inconsistency

**Location:** Across all `src/hassette/` files

The codebase uses two different patterns:
- `if typing.TYPE_CHECKING:` — 42 files (dominant)
- `if TYPE_CHECKING:` — 15 files

The majority import `typing` and use `typing.TYPE_CHECKING`. The 15 files that use `from typing import TYPE_CHECKING` are scattered across `web/`, `core/`, `events/`, and `types/` with no layer-based rationale.

**Recommendation:** Standardize on `if typing.TYPE_CHECKING:` (the dominant convention) across all files.

---

### M3. `mark_ready()` usage inconsistency

**Location:** All Resource/Service subclasses

The convention established by 30+ callsites is `self.mark_ready(reason="descriptive string")`. Three callsites deviate:

1. **`state_manager/state_manager.py:227`** — `self.mark_ready()` with no reason at all
2. **`core/app_handler.py:84`** — `self.mark_ready("initialized")` using positional arg instead of `reason=`
3. **`core/app_lifecycle_service.py:141`** — `inst.mark_ready(reason="initialized")` (correct, but the nearby `app_handler` uses the wrong form)

**Recommendation:** Fix the two outliers to use `self.mark_ready(reason="...")`.

---

### M4. Three Resource subclasses missing `config_log_level` override

**Location:**
- `src/hassette/core/event_stream_service.py` (`EventStreamService`)
- `src/hassette/core/session_manager.py` (`SessionManager`)
- `src/hassette/core/web_ui_watcher.py` (`WebUiWatcherService`)

Every other service and resource in `core/` overrides `config_log_level` to point at a specific config key. These three fall through to the base class default (`self.hassette.config.log_level`), meaning they cannot be independently configured for log verbosity. For `WebUiWatcherService` this is particularly noteworthy since file watchers and the similar `FileWatcherService` do have their own config key.

**Recommendation:** Add dedicated config keys (or at minimum, explicit overrides that document the intentional fallback).

---

### M5. Duplicate execution-tracking boilerplate in `CommandExecutor`

**Location:** `src/hassette/core/command_executor.py:112-283`

`_execute_handler` (lines 112-199) and `_execute_job` (lines 201-283) share identical timing/error-capture/record-queueing logic. Each has 4 exception branches (`CancelledError`, `DependencyError`, `HassetteError`, generic `Exception`) plus a success branch, all with the same pattern of:
1. Compute `duration_ms`
2. Build a record dataclass
3. Queue it via `put_nowait`
4. Optionally run error hooks

The only differences are the record type (`HandlerInvocationRecord` vs `JobExecutionRecord`) and the invocation (`cmd.listener.invoke(cmd.event)` vs `cmd.callable()`).

Note: `utils/execution.py` already provides a `track_execution()` async context manager that captures timing, status, and error details -- it is purpose-built for exactly this pattern, but `CommandExecutor` does not use it.

**Recommendation:** Refactor both methods to use `track_execution()`, which would reduce the 170 lines of duplicated branching to ~40 lines. Build the record from the `ExecutionResult` after the context manager exits.

---

### M6. `Api.config_log_level` returns global log level instead of API-specific level

**Location:** `src/hassette/api/api.py:205-207`

```python
@property
def config_log_level(self):
    return self.hassette.config.log_level
```

This is identical to `ApiResource.config_log_level` (line 73-75), which also returns `self.hassette.config.log_level`. But `Api` is the user-facing resource that wraps `ApiResource`. Sibling user-facing resources like `Bus` and `Scheduler` override to return their domain-specific log level (`bus_service_log_level`, `scheduler_service_log_level`). The `Api` resource is the only user-facing resource that falls back to the global log level.

**Recommendation:** Either create an `api_log_level` config key, or explicitly document that the API shares the global log level. The current state looks like an oversight rather than an intentional decision.

---

### M7. `CoroLikeT` TypeVar defined identically in two files

**Location:**
- `src/hassette/resources/base.py:22` — `CoroLikeT = Coroutine[Any, Any, T]`
- `src/hassette/resources/mixins.py:14` — `CoroLikeT = Coroutine[Any, Any, T]`

These are the same alias defined independently in two related files. `base.py` imports `LifecycleMixin` from `mixins.py`, so they are directly coupled. The `CoroLikeT` in `mixins.py` is used by `_TaskBucketP`, while the one in `base.py` is unused (it was likely left behind after a refactor).

**Recommendation:** Remove `CoroLikeT` from `base.py` (verify it is truly unused there) and import from `mixins.py` if needed.

---

### M8. Web route error handling pattern drift

**Location:** `src/hassette/web/routes/`

The route files handle errors differently:

| File | Pattern |
|---|---|
| `apps.py` | `except Exception as exc: raise HTTPException(status_code=500, ...)` |
| `services.py` | `except Exception as exc: raise HTTPException(status_code=502, ...)` |
| `health.py` | No error handling (lets exceptions propagate) |
| `bus.py` | No error handling |
| `scheduler.py` | No error handling |

The `apps.py` routes consistently use try/except with `logger.warning(..., exc_info=True)` + `HTTPException`. But `bus.py`, `scheduler.py`, and `health.py` have no error handling at all -- any exception becomes a raw 500 Internal Server Error. `services.py` uses 502, which is semantically correct for HA proxy calls but inconsistent with `apps.py` using 500 for all app operations.

**Recommendation:** Establish a consistent pattern -- either wrap all routes with error handling or use a FastAPI exception handler middleware. At minimum, routes that proxy to Home Assistant should use 502.

---

## LOW Severity

### L1. `T = TypeVar("T")` redefined in 10 files

**Location:** `resources/base.py`, `resources/mixins.py`, `conversion/type_registry.py`, `context.py`, `scheduler/classes.py`, `core/scheduler_service.py`, `bus/bus.py`, `event_handling/dependencies.py`, `task_bucket/task_bucket.py`, `core/core.py`

Each file defines its own `T = TypeVar("T")` (or a constrained/covariant variant). The generic `T = TypeVar("T")` instances are not reusable across files in Python's type system (each is a distinct TypeVar), so this is technically correct. However, it creates visual noise, and several of these could share a module-level definition from `types/types.py` (which does not currently export a generic `T`).

**Recommendation:** Low priority. Consider adding `T = TypeVar("T")` to `hassette/types/types.py` and importing it where appropriate, but only if it improves readability without breaking type inference.

---

### L2. `docstring` inconsistency on `config_log_level` overrides

**Location:** All `config_log_level` property overrides

Most overrides include the docstring `"""Return the log level from the config for this resource."""`. Several omit it:
- `core/runtime_query_service.py:69`
- `core/telemetry_query_service.py:40`
- `core/web_api_service.py:30` (also missing the docstring entirely)

Since the property is inherited and the docstring is identical across all sites, it is pure boilerplate. Either all overrides should have it (current majority convention) or none should.

**Recommendation:** Remove the docstring from all overrides -- the base class docstring is sufficient, and identical docstrings on 20+ properties is just noise.

---

### L3. `tests/` directory has test files outside the standard hierarchy

**Location:**
- `tests/test_docker_integration.py`
- `tests/test_docker_requirements_discovery.py`

All other tests are organized under `tests/unit/`, `tests/integration/`, `tests/e2e/`, or `tests/smoke/`. These two Docker-related test files sit at the `tests/` root with no subdirectory, breaking the organizational pattern.

**Recommendation:** Move to `tests/integration/` or create `tests/docker/` if they need separate CI configuration.

---

## Summary Table

| # | Finding | Severity | Category |
|---|---|---|---|
| H1 | `ApiResource.on_shutdown` signature deviation | HIGH | Interface inconsistency |
| H2 | Module-level logger naming split 3 ways | HIGH | Naming drift |
| M1 | `config_log_level` return type annotation drift | MEDIUM | Interface inconsistency |
| M2 | `TYPE_CHECKING` import guard inconsistency | MEDIUM | Naming drift |
| M3 | `mark_ready()` usage inconsistency | MEDIUM | Interface inconsistency |
| M4 | Three Resources missing `config_log_level` override | MEDIUM | Pattern drift |
| M5 | Duplicate execution-tracking boilerplate | MEDIUM | Duplication |
| M6 | `Api.config_log_level` returns global level | MEDIUM | Pattern drift |
| M7 | `CoroLikeT` TypeVar defined in two related files | MEDIUM | Duplication |
| M8 | Web route error handling pattern drift | MEDIUM | Pattern drift |
| L1 | `T = TypeVar("T")` redefined in 10 files | LOW | Duplication |
| L2 | `config_log_level` docstring inconsistency | LOW | Naming drift |
| L3 | Docker tests outside standard test hierarchy | LOW | Misplacement |

## Positive Observations

- **Resource/Service hierarchy** is clean and consistently applied. The `FinalMeta` metaclass enforcement is a strong safeguard.
- **Lifecycle hooks** (`before_initialize`, `on_initialize`, `after_initialize`, and shutdown equivalents) are used consistently with only the one signature deviation noted.
- **Dependency injection** via `web/dependencies.py` is well-centralized. All routes use the shared type aliases (`RuntimeDep`, `HassetteDep`, etc.).
- **Exception hierarchy** in `exceptions.py` is well-organized with clear inheritance chains.
- **Event handling** module (predicates, conditions, accessors, dependencies) is internally consistent.
- **State models** in `models/states/` follow a uniform pattern with no drift.
- **Test infrastructure** (`HassetteHarness`, `create_hassette_stub`, fixtures) is well-documented and consistently used.
