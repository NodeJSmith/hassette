# Codebase Health Audit

**Date**: 2026-02-17

**Status**: Complete

**Scope**: Full codebase audit — structure, churn, coupling, test coverage, code quality signals

## Context

### What prompted this

Routine health check to identify the highest-impact problems in the codebase before they compound. The project is ~6 months old with 202 commits (44 in the last 3 months), primarily single-contributor. The codebase has grown to ~20,800 lines of source across 153 Python files with 76 test files.

### Methodology

Five parallel analyses were run:

1. **Structure & size** — directory tree, line counts, large files/functions
2. **Git churn & age** — hot spots, cold spots, net growth
3. **Dependency & coupling** — import graph, fan-in/fan-out, circular deps
4. **Test coverage & safety** — pytest --cov, untested paths, broad catches
5. **Code quality signals** — nesting, duplication, hardcoded values, TODOs, inconsistencies

## Findings

### Critical: 67 Broad Exception Catches

**Impact**: Silently masks real bugs in an async framework where correctness of automation execution matters.

67 instances of `except Exception` (or `except Exception as e:`) across 22 source files. Many log-and-continue or silently swallow errors.

**Worst offenders by file:**

| File                                 | Count | Context                                   |
| ------------------------------------ | ----- | ----------------------------------------- |
| `bus/injection.py`                   | 5     | DI resolution — masks injection failures  |
| `core/app_handler.py`                | 5     | App lifecycle — masks start/stop failures |
| `resources/base.py`                  | 5     | Resource lifecycle — init/shutdown        |
| `task_bucket/task_bucket.py`         | 5     | Task execution — masks task failures      |
| `core/app_factory.py`                | 3     | App instantiation                         |
| `core/bus_service.py`                | 3     | Event dispatch                            |
| `core/service_watcher.py`            | 3     | Background service monitoring             |
| `utils/app_utils.py`                 | 5     | App loading/detection                     |
| `web/routes/apps.py`                 | 3     | API endpoints                             |
| `web/routes/ws.py`                   | 2     | WebSocket routes                          |
| `conversion/annotation_converter.py` | 4     | Type annotation conversion                |
| `conversion/type_registry.py`        | 2     | Type registry lookups                     |
| `conversion/state_registry.py`       | 1     | State registry                            |
| `core/websocket_service.py`          | 2     | WebSocket connection                      |
| `core/data_sync_service.py`          | 2     | Status collection — silently returns 0    |
| `core/scheduler_service.py`          | 2     | Job execution cleanup                     |
| `state_manager/state_manager.py`     | 2     | State access                              |
| `core/state_proxy.py`                | 2     | State proxy                               |
| `core/core.py`                       | 1     | Main initialization                       |
| `core/app_lifecycle.py`              | 2     | App lifecycle hooks                       |
| `test_utils/harness.py`              | 3     | Test cleanup (acceptable)                 |
| Others                               | 3     | Various                                   |

**Patterns observed:**

1. **Log-and-continue** (most common): `except Exception as e: self.logger.exception(...)` — the error is logged but execution continues, potentially leaving the system in an inconsistent state.
2. **Silent swallow**: `except Exception: pass` or `except Exception: return default` — error disappears entirely. Seen in `data_sync_service.py` (returns 0 for entity/app counts on error), `scheduler_service.py`, `app_factory.py`.
3. **Cleanup guards**: `except Exception:` in shutdown/cleanup code — more defensible, seen in `resources/base.py` shutdown and `test_utils/harness.py`.

**Recommendation**: Audit each instance and narrow to specific exception types. Priority order:
1. `bus/injection.py` — DI failures should surface, not be swallowed
2. `core/app_handler.py` — app lifecycle errors need specific handling
3. `core/bus_service.py` — event dispatch errors affect automation correctness
4. `conversion/*.py` — type conversion failures mask data issues

---

### Critical: Test Coverage at 79% (target: 80%)

**Impact**: The safety net has holes in exactly the areas that change most.

**Test run summary** (2026-02-17, `pytest -n auto --dist loadscope`):

| Metric   | Value             |
| -------- | ----------------- |
| Passed   | 825               |
| Failed   | 1                 |
| Errors   | 0                 |
| xfailed  | 2                 |
| Coverage | 79% (target: 80%) |
| Duration | 85s               |

**The 1 test failure** is in `tests/integration/test_listeners.py`:
- `TestThrottleLogic::test_throttle_tracks_time_correctly` — flaky timing test, passes in isolation

Note: running with the default `--dist load` strategy produces 43 errors due to test isolation issues (shared env vars, global registries, event loops). Using `--dist loadscope` groups tests by module and eliminates these. Consider updating CI and `CLAUDE.md` to specify `--dist loadscope`.

**Lowest coverage modules** (source files with highest risk):

| Module                           | Coverage | Uncovered lines | Churn (6mo)                | Risk                                     |
| -------------------------------- | -------- | --------------- | -------------------------- | ---------------------------------------- |
| `scheduler/scheduler.py`         | **53%**  | 39              | 10 changes                 | HIGH — active development, half untested |
| `utils/hass_utils.py`            | **66%**  | 10              | —                          | MEDIUM                                   |
| `state_manager/state_manager.py` | **66%**  | 40              | —                          | MEDIUM — foundational module             |
| `utils/func_utils.py`            | **66%**  | 14              | —                          | MEDIUM                                   |
| `utils/request_utils.py`         | **67%**  | 7               | —                          | LOW — cold, small                        |
| `utils/app_utils.py`             | **70%**  | 59              | 12 changes                 | HIGH — high churn + low coverage         |
| `resources/mixins.py`            | **70%**  | 34              | —                          | MEDIUM — used by all resources           |
| `utils/type_utils.py`            | **70%**  | 63              | 15 changes (recent growth) | HIGH — complex type introspection        |
| `utils/glob_utils.py`            | **70%**  | 3               | —                          | LOW — small file                         |
| `task_bucket/task_bucket.py`     | **70%**  | 46              | —                          | MEDIUM                                   |

The coverage numbers above are unchanged between `--dist load` and `--dist loadscope`.

---

### Concerning: Config Module Is the #1 Hotspot

**Impact**: Most frequently changed file drives framework behavior; bidirectional coupling with app module.

**Churn data (last 6 months):**

| File                     | Changes | Role                 |
| ------------------------ | ------- | -------------------- |
| `config/core_config.py`  | **30**  | #1 most-changed file |
| `core/core.py`           | **28**  | Main coordinator     |
| `test_utils/harness.py`  | **22**  | Test harness         |
| `__init__.py`            | **24**  | Public API exports   |
| `test_utils/fixtures.py` | **17**  | Test fixtures        |
| `models/states/base.py`  | **16**  | State model base     |
| `core/api.py`            | **15**  | API resource         |

`core_config.py` at 30 changes is the single highest-churn source file. Every feature addition, behavior tweak, or default change touches this file. It also has coupling to `utils/app_utils.py` (for app detection/validation) and `config/classes.py` (for `AppManifest`), while the app module imports back from config.

**Net growth leaders (last 3 months):**

| Net lines | Added | Deleted | File                                              |
| --------- | ----- | ------- | ------------------------------------------------- |
| +1,158    | 1,767 | 609     | `tests/integration/test_web_ui.py`                |
| +970      | 991   | 21      | `tests/integration/test_dependencies.py`          |
| +526      | 580   | 54      | `tests/integration/test_state_proxy.py`           |
| +505      | 505   | 0       | `tests/integration/test_app_factory_lifecycle.py` |
| +498      | 516   | 18      | `tests/unit/core/test_data_sync_service.py`       |
| +491      | 491   | 0       | `tests/unit/core/test_app_registry.py`            |
| +460      | 486   | 26      | `src/hassette/core/data_sync_service.py`          |
| +415      | 495   | 80      | `src/hassette/utils/type_utils.py`                |
| +409      | 534   | 125     | `tests/integration/test_web_api.py`               |
| +365      | 365   | 0       | `src/hassette/core/app_registry.py`               |

Growth is primarily in tests (healthy) and new core services (`data_sync_service.py`, `app_registry.py`, `type_utils.py`).

---

### Concerning: Large Files Approaching Complexity Limits

**Impact**: Larger files are harder to navigate, review, and modify safely.

**Files exceeding 400 lines:**

| File                           | Lines   | Churn (6mo) | Concern                                                   |
| ------------------------------ | ------- | ----------- | --------------------------------------------------------- |
| `api/api.py`                   | **882** | 15          | All REST/WebSocket methods in one file                    |
| `bus/bus.py`                   | **809** | 11          | 6 subscription methods with duplicated predicate assembly |
| `utils/app_utils.py`           | **518** | 12          | Mixed concerns: detection, loading, validation            |
| `scheduler/scheduler.py`       | **505** | 10          | 53% coverage                                              |
| `api/sync.py`                  | **505** | —           | Auto-generated sync facade                                |
| `core/scheduler_service.py`    | **503** | —           | Job execution coordinator                                 |
| `event_handling/predicates.py` | **498** | —           | 30+ predicate dataclasses                                 |
| `core/bus_service.py`          | **494** | —           | Bus service coordination                                  |
| `core/data_sync_service.py`    | **460** | new         | Data aggregation for frontend                             |
| `config/config.py`             | **459** | 13          | Configuration parsing                                     |
| `resources/base.py`            | **451** | —           | Resource base class, 21 dependents                        |
| `test_utils/harness.py`        | **438** | 22          | Test harness                                              |
| `event_handling/conditions.py` | **433** | —           | 17+ condition dataclasses                                 |
| `core/websocket_service.py`    | **420** | 10          | WebSocket management                                      |
| `utils/type_utils.py`          | **415** | new         | Type introspection (70% coverage)                         |

**Repetitive patterns in bus.py** — the 6 subscription methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on_component_loaded`, `on_service_registered`, `on_event`) each:
1. Log the subscription
2. Build a `preds: list[Predicate]` with entity/domain/service matching
3. Handle `changed_from`/`changed_to` variants
4. Handle `where` clause
5. Delegate to `self.on()`

This is ~400 lines of highly similar code that could be consolidated with a builder or factory.

---

### Concerning: Cold Spots Still In Active Use

**Impact**: Code written months ago that hasn't been reviewed or tested against current patterns.

**Files not touched since Oct 2025 or earlier (still actively imported):**

| Last touched | File                       | Used by                       |
| ------------ | -------------------------- | ----------------------------- |
| 2025-09-04   | `const/sensor.py`          | State models                  |
| 2025-10-07   | `models/services.py`       | API, state manager            |
| 2025-10-16   | `utils/request_utils.py`   | API module (67% coverage)     |
| 2025-10-20   | `const/colors.py`          | Light state model             |
| 2025-10-27   | `events/hass/raw.py`       | Event system                  |
| 2025-10-31   | `api/__init__.py`          | Public API                    |
| 2025-10-31   | `events/hass/__init__.py`  | Event exports                 |
| 2025-10-31   | `resources/__init__.py`    | Resource exports              |
| 2025-10-31   | `scheduler/__init__.py`    | Scheduler exports             |
| 2025-11-02   | `models/states/simple.py`  | State registry                |
| 2025-11-02   | `utils/glob_utils.py`      | Bus predicates (70% coverage) |
| 2025-11-02   | `utils/service_utils.py`   | Core services                 |
| 2025-11-07   | `utils/exception_utils.py` | 8+ modules                    |

Most state model files (`models/states/*.py`) are also cold but are simple Pydantic models that rarely need changes — these are low risk.

---

### Positive: Clean Dependency Structure

**No circular imports found.** The codebase uses `TYPE_CHECKING` guards strategically to prevent runtime cycles.

**Dependency layering is sound:**

```
Infrastructure (const, types, exceptions, resources/base)  ← used by everything
    ↑
Utilities (utils/*, conversion/*)                           ← used by ~15 modules
    ↑
Domain (events, event_handling, models)                     ← well-isolated
    ↑
User APIs (app, bus, scheduler, api, state_manager)         ← moderate fan-out
    ↑
Core Orchestration (core/*)                                 ← high fan-out (expected)
    ↑
Web Layer (web/*)                                           ← isolated, only reads from core
```

**Top fan-in modules** (most depended upon — changes here cascade widely):

| Module           | Dependents |
| ---------------- | ---------- |
| `types`          | 25+        |
| `exceptions`     | 22+        |
| `resources/base` | 21+        |
| `events`         | 16+        |
| `const`          | 12+        |

**God module**: `core/core.py` imports 15+ modules, but this is expected and acceptable for the main orchestrator. It delegates to child services rather than implementing logic directly.

---

### Worth Noting

1. **Only 3 TODOs in the entire codebase**, all well-documented:
   - Fixture scope limitation (test isolation)
   - App reload optimization (restart granularity)
   - Unmaintained `coloredlogs` dependency (broken on Python >3.13)

2. **Minimal hardcoded values** — retry backoff (1s initial, 32s max, 5 attempts) in `websocket_service.py` and a 1s timeout in test harness. Otherwise config-driven.

3. **Strong type coverage** — all functions have type hints, extensive use of `@dataclass(frozen=True)` for immutability, Protocol-based duck typing.

4. **Well-isolated web layer** — imports only within `web.*` and from core dependencies. Changes don't cascade.

## Recommended Actions

Ordered by impact (highest first):

| Priority | Finding                                               | Recommended action                                                      | Tool                               |
| -------- | ----------------------------------------------------- | ----------------------------------------------------------------------- | ---------------------------------- |
| **1**    | 67 broad `except Exception`                           | Audit each instance, narrow to specific types                           | `/mine.refactor` or dedicated task |
| **2**    | Scheduler at 53% coverage                             | Add test coverage for uncovered paths                                   | tdd-guide agent                    |
| **3**    | `app_utils.py` — 70% coverage, 12 changes             | Add tests, then consider splitting (discovery, loading, validation)     | tdd-guide, then `/mine.refactor`   |
| **4**    | `type_utils.py` — 70% coverage, +415 lines net growth | Stabilize with tests before it grows further                            | tdd-guide agent                    |
| **5**    | xdist test isolation                                  | Switch to `--dist loadscope` in CI and docs; fix the 1 throttle failure | tdd-guide agent                    |
| **6**    | `bus.py` — 809 lines, repetitive subscription methods | Extract predicate assembly to builder/factory                           | `/mine.refactor`                   |
| **7**    | `api.py` — 882 lines                                  | Split by concern (state ops, service calls, data retrieval, WS)         | `/mine.refactor`                   |
| **8**    | Config hotspot coupling                               | Consider extracting shared models to reduce bidirectional coupling      | `/mine.adrs`                       |

## Appendix: Raw Data

### Commit Activity

- Total commits: 202
- Last 3 months: 44
- Last 6 months: 202
- Contributors: 1 primary (Jessica Smith), 2 minor

### Source File Count

- `src/hassette/`: 153 Python files, ~20,800 lines
- `tests/`: 76 Python files
- Largest test file: `tests/integration/test_web_ui.py` (48 KB, +1,158 net lines in 3 months)
