# Design: Split SyncExecutor capability from SyncExecutorService lifecycle wrapper

**Date:** 2026-07-21
**Status:** approved
**Scope-mode:** hold
**Research:** /tmp/claude-mine-define-research-8TPzNu/brief.md

## Problem

`SyncExecutorService` conflates two concerns: owning a thread pool (passive capability) and participating in the Resource/Service lifecycle. `TaskBucket`s are constructed eagerly during `Resource.__init__` — every Resource gets one — but `SyncExecutorService` doesn't exist until `wire_services()` runs. This timing mismatch forces three workarounds:

1. `contextlib.suppress(RuntimeError)` in `_create_task_bucket` (`task_bucket.py:380-386`) — tries to read `hassette.sync_executor_service`, swallows the pre-wiring error, leaves `_sync_service = None`.
2. Post-hoc patching in `wire_services()` (`core.py:192-193`) — manually patches Hassette's own TaskBucket and SyncExecutorService's own TaskBucket after the fact, with an ordering constraint ("MUST be the first `add_child`").
3. Mirrored patching in the test harness (`harness.py:701-704`) — byte-for-byte duplicate of the `wire_services()` patch, because the harness reimplements startup.

These workarounds are load-bearing — removing any one without the structural fix breaks bootstrap. The test infrastructure also contorts around the conflation: `make_sync_service()` (`factories.py:353-374`) uses `__new__` to bypass `__init__` entirely and manually sets only the executor-related fields, effectively constructing the proposed `SyncExecutor` class without the formalization.

## Goals

- All three workarounds eliminated — no `contextlib.suppress`, no post-hoc patching, no harness mirroring.
- Shutdown-wave ordering preserved — BusService, SchedulerService, and AppHandler still tear down before the thread pool.
- Restart-in-place works — `ServiceWatcher` can restart `SyncExecutorService` and the pool rebuilds cleanly, with all `TaskBucket` references remaining valid.
- Test infrastructure simplified — `make_sync_service()`'s `__new__` bypass hack replaced by a direct `SyncExecutor(max_workers=N)` constructor call.

## User Scenarios

### Framework developer: Contributor modifying bootstrap or lifecycle code

- **Goal:** Understand and safely modify the sync executor initialization path
- **Context:** During development or debugging of service startup

#### Adding a new service that uses sync execution

1. **Declares `depends_on = [SyncExecutorService]`**
   - Sees: `SyncExecutorService` in the depends_on list of existing services
   - Decides: Whether their service needs shutdown ordering relative to the pool
   - Then: Wave-based startup/shutdown handles the ordering automatically

2. **Calls `self.task_bucket.run_in_thread(fn)` from a lifecycle hook**
   - Sees: `run_in_thread` available on any Resource's task_bucket
   - Decides: N/A — the API is the same regardless of the split
   - Then: Work executes on the dedicated `hassette-sync` thread pool

### Test author: Developer writing tests for sync execution behavior

- **Goal:** Construct a sync executor for unit tests without lifecycle overhead
- **Context:** Writing or maintaining tests in `tests/unit/`

#### Creating a test executor

1. **Calls `SyncExecutor(max_workers=2)`**
   - Sees: A plain constructor with no Resource/Service ceremony
   - Decides: How many workers the test needs
   - Then: Gets a fully functional executor ready for `submit()` calls

## Functional Requirements

- **FR#1** `SyncExecutor` is a plain class (no `Resource`/`Service` base) that owns a thread pool and exposes `submit(fn, *args, **kwargs) -> asyncio.Future` with context propagation and `SyncWorkerHandle` attribution.
- **FR#2** `SyncExecutor` is constructed during `Hassette.__init__()` before `super().__init__()`, making it available to every `TaskBucket` from birth via the factory.
- **FR#3** `SyncExecutorService` remains a `Service` subclass that wraps `SyncExecutor` for lifecycle concerns: `on_initialize()` (pool rebuild), `serve()` (saturation monitoring), `on_shutdown()` (pool teardown).
- **FR#4** `TaskBucket.run_in_thread()` delegates to `SyncExecutor.submit()` instead of `SyncExecutorService.submit()`.
- **FR#5** `SyncExecutorService.on_initialize()` calls `SyncExecutor.rebuild_pool()` to rebuild the thread pool for restart-in-place, preserving `SyncExecutor` object identity.
- **FR#6** Every `TaskBucket` has `_sync_executor` set from birth — no exception suppression, no post-hoc patching, no conditional. This includes TaskBuckets created via the factory and TaskBuckets constructed explicitly (e.g., Hassette's own).
- **FR#7** `depends_on` declarations on `BusService`, `SchedulerService`, and `AppHandler` remain unchanged — they reference `SyncExecutorService` for shutdown-wave ordering.

## Edge Cases

- **Restart-in-place**: When `ServiceWatcher` restarts `SyncExecutorService`, `on_initialize()` calls `rebuild_pool()` on the same `SyncExecutor` instance. All `TaskBucket._sync_executor` references remain valid (same object identity, fresh pool).
- **Shutdown race**: A sync handler submitting work after `SyncExecutorService.on_shutdown()` fires — the existing shutdown-ordering test (`test_sync_executor_service_wiring.py`) covers this scenario and must continue passing.
- **Saturation during restart**: Between `shutdown_pool()` and `rebuild_pool()`, `_active_workers` is reset to 0 and the old pool's threads are drained. The probe loop in `serve()` reads stale-safe counters.

## Acceptance Criteria

- **AC#1** `grep -rn 'contextlib.suppress(RuntimeError)' src/hassette/task_bucket/task_bucket.py` returns no hits — the factory's RuntimeError suppression is gone (FR#6)
- **AC#2** `sed -n '/def wire_services/,/^    def /p' src/hassette/core/core.py | grep -c 'task_bucket._sync'` returns `0` — no post-hoc patching in `wire_services()`. The one `task_bucket._sync_executor` line in `__init__` is expected (FR#2, FR#6).
- **AC#3** `grep -n 'task_bucket._sync' src/hassette/test_utils/harness.py` returns no hits — no mirrored patching (FR#2, FR#6)
- **AC#4** `prek -a && prek pyright -a --stage pre-push` passes with no errors (all FRs)
- **AC#5** `ptest dev` (unit + integration tests) passes with no failures (all FRs)
- **AC#6** `grep -rn 'class SyncExecutor' src/hassette/core/sync_executor.py` confirms `SyncExecutor` exists as a plain class without `Resource`/`Service` base (FR#1)
- **AC#7** `grep -l 'SyncExecutorService' src/hassette/core/bus_service.py src/hassette/core/scheduler_service.py src/hassette/core/app_handler.py` returns all three files — `depends_on` declarations preserved (FR#7)

## Key Constraints

- Do not change `depends_on` declarations on downstream services — these are the shutdown ordering mechanism.
- `SyncWorkerHandle` and `SYNC_WORKER_HANDLE` move to `sync_executor.py` (alongside the capability they support). `command_executor.py`'s import changes from `hassette.core.sync_executor_service` to `hassette.core.sync_executor`. A re-export from `sync_executor_service.py` is not needed — update the import directly.
- Do not make `SyncExecutor` a `Resource` — the entire point is that it's available before the Resource lifecycle starts.

## Dependencies and Assumptions

- `InterruptibleThreadPoolExecutor` creates no threads until first `submit()` — constructing the pool in `Hassette.__init__` is safe because no work is submitted until `run_forever()` starts services.
- `ServiceWatcher.restart()` preserves object identity — it calls `shutdown()` then `initialize()` on the same instance.
- `config.lifecycle.sync_executor_max_workers` and `config.lifecycle.sync_executor_shutdown_timeout_seconds` are available during `Hassette.__init__` (config is parsed before construction).

## Architecture

### New class: `SyncExecutor`

A plain capability class in `src/hassette/core/sync_executor.py`, following the `Router` (`bus/router.py`) and `AppRegistry` (`core/app_registry.py`) precedent.

**Owns:**
- `executor: InterruptibleThreadPoolExecutor` — built in `__init__`
- `submit(fn, *args, **kwargs) -> asyncio.Future` — context-propagating submit with `SyncWorkerHandle` attribution (moved from `SyncExecutorService`)
- `track_submission(future)` — active worker counting (moved from `SyncExecutorService`)
- `log_saturation_rate_limited()` — rate-limited saturation warning (moved from `SyncExecutorService`; reads `executor._max_workers` and `executor._work_queue` — must stay co-located with the pool)
- `_active_workers: int`, `_last_saturation_warn_ts: float` — saturation state
- `rebuild_pool(max_workers, thread_name_prefix)` — creates a fresh pool (replacing the current one if present); called by `SyncExecutorService.on_initialize()` for restart-in-place. The caller (`restart()` in `operations.py`) always calls `shutdown()` before `initialize()`, so the old pool is already shut down when `rebuild_pool()` runs.
- `shutdown_pool(timeout)` — shuts down the pool; called by `SyncExecutorService.on_shutdown()`

**Constructor:** `SyncExecutor(max_workers: int, thread_name_prefix: str = SYNC_EXECUTOR_THREAD_NAME_PREFIX)` — builds the pool immediately.

**Module-level (stays in `sync_executor.py`):**
- `SyncWorkerHandle` dataclass
- `SYNC_WORKER_HANDLE` contextvar
- `SYNC_EXECUTOR_THREAD_NAME_PREFIX` constant
- Saturation constants (`_SATURATION_WARN_THRESHOLD`, `_SATURATION_WARN_RATE_LIMIT_SECS`, `_SATURATION_PROBE_INTERVAL_SECS`)

### Thinned `SyncExecutorService`

Stays in `src/hassette/core/sync_executor_service.py`. Becomes a thin lifecycle wrapper:

- `__init__(self, hassette, *, parent=None)` — reads `hassette.sync_executor` (the pre-built capability)
- `on_initialize()` — calls `self.sync_executor.rebuild_pool(config.max_workers, prefix)` and resets counters
- `serve()` — `mark_ready()`, then saturation probe loop calling `self.sync_executor.log_saturation_rate_limited()`
- `on_shutdown()` — computes shutdown budget, calls `asyncio.to_thread(self.sync_executor.shutdown_pool, budget)`
- `depends_on = []`, `restart_spec = CORE_PERMANENT_RESTART` — unchanged

### Bootstrap flow (after)

1. `Hassette.__init__` constructs `self._sync_executor = SyncExecutor(config.lifecycle.sync_executor_max_workers)`
2. `Hassette.__init__` calls `super().__init__()` — Hassette's own TaskBucket is constructed explicitly (`task_bucket=TaskBucket(self, parent=self)`, bypassing the factory). Its `_sync_executor` is `None` at this point.
3. `Hassette.__init__` wires its own bucket: `self.task_bucket._sync_executor = self._sync_executor` — one line, at the point of construction, not deferred to `wire_services()`.
4. `wire_services()` calls `self.add_child(SyncExecutorService)` — SyncExecutorService's own TaskBucket is created by the factory during `Resource.__init__`. The factory sets `bucket._sync_executor = hassette._sync_executor` (no `contextlib.suppress` — `_sync_executor` is always available).
5. All subsequent `add_child(...)` calls produce correctly-wired TaskBuckets via the factory.
6. No post-hoc patching in `wire_services()` — Hassette's own bucket is wired in `__init__`, all others are wired by the factory.

### Hassette-level accessors

- `hassette.sync_executor` — new plain attribute (not a property), set in `__init__`, always available. Type: `SyncExecutor`.
- `hassette.sync_executor_service` — existing property with `_service_not_wired_error` guard, unchanged. Type: `SyncExecutorService`.

### TaskBucket changes

- `_sync_service: SyncExecutorService | None` renamed to `_sync_executor: SyncExecutor | None`
- `TaskBucket.__init__` keeps `self._sync_executor = None` (same pattern as today's `self._sync_service = None`)
- Wiring happens externally via two paths: the factory (for factory-created buckets) and one line in `Hassette.__init__` (for Hassette's own explicitly-constructed bucket)
- `run_in_thread()` calls `self._sync_executor.submit(...)` instead of `self._sync_service.submit(...)`
- The RuntimeError guard for `_sync_executor is None` stays
- `_create_task_bucket` factory simplifies to: construct bucket, set `bucket._sync_executor = hassette._sync_executor` — no `contextlib.suppress`, no conditional

## Implementation Preferences

No specific implementation preferences — follow codebase conventions. The Router/AppRegistry pattern is the guiding precedent.

## Replacement Targets

| Target | File | Replaced by | Action |
|---|---|---|---|
| `contextlib.suppress(RuntimeError)` in factory | `task_bucket.py:380-386` | Direct `hassette.sync_executor` assignment | Remove suppression |
| Post-hoc patching block | `core.py:192-193` | N/A — wiring happens from birth | Delete 2 lines + ordering comment |
| Mirrored patching in harness | `harness.py:701-704` | N/A — wiring happens from birth | Delete 3 lines |
| `make_sync_service()` `__new__` bypass | `factories.py:353-374` | `make_sync_executor()` with direct constructor | Replace factory |
| `make_service()` conftest helper | `tests/unit/conftest.py:69-76` | Direct `SyncExecutor(max_workers=N)` | Replace helper |
| Capability methods on `SyncExecutorService` | `sync_executor_service.py` | Methods on `SyncExecutor` | Move to new class |

## Convention Examples

### Plain capability class (Router pattern)

**Source:** `src/hassette/bus/router.py`

```python
class Router:
    def __init__(self) -> None:
        self._routes: dict[str, list[Listener]] = defaultdict(list)
        self._glob_patterns: dict[str, list[Listener]] = {}
```

Plain class, no Resource/Service base. Constructed inside `BusService.__init__`: `self.router = Router()`.

### Plain capability class (AppRegistry pattern)

**Source:** `src/hassette/core/app_registry.py`

```python
class AppRegistry:
    def __init__(self) -> None:
        self._apps: dict[str, AppManifest] = {}
```

Same pattern — no `hassette` parameter, no lifecycle hooks. Constructed in `AppHandler.__init__`.

### Constructor injection in wire_services()

**Source:** `src/hassette/core/core.py:200-203`

```python
self._bus_service = self.add_child(
    BusService, stream=self._event_stream_service.receive_stream.clone(), executor=self._command_executor
)
self._scheduler_service = self.add_child(SchedulerService, executor=self._command_executor)
```

Services receive collaborators as constructor kwargs via `add_child`. `SyncExecutorService` will receive `hassette.sync_executor` the same way (read from `hassette` in its `__init__`).

### Property-with-guard pattern

**Source:** `src/hassette/core/core.py:322-327`

```python
@property
def sync_executor_service(self) -> SyncExecutorService:
    if self._sync_executor_service is None:
        raise _service_not_wired_error("SyncExecutorService")
    return self._sync_executor_service
```

`sync_executor_service` property stays as-is. The new `sync_executor` is a plain attribute set in `__init__`, not a property — it never needs a guard because it's always available.

## Alternatives Considered

### Keep everything in SyncExecutorService, fix the timing differently

Approach: Make `SyncExecutorService` available earlier in the lifecycle (e.g., construct it in `Hassette.__init__` before `super().__init__()`).

Rejected: `SyncExecutorService` is a `Service` subclass, and `Service.__init__` requires a fully constructed `hassette` with a `task_bucket` — creating a circular dependency. The issue isn't that the service is created too late; it's that the capability shouldn't be a service at all.

### Make TaskBucket lazily wire the sync executor

Approach: Instead of wiring at construction, have `TaskBucket.run_in_thread()` lazily look up `hassette.sync_executor_service` on first call.

Rejected: Adds runtime cost to every `run_in_thread` call (property lookup + None check on a hot path). Also doesn't eliminate the factory workaround — it just moves the suppression from construction to first use. The root cause (capability conflated with lifecycle) remains.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/test_sync_executor_service_wiring.py` — Update type references from `SyncExecutorService` to `SyncExecutor` for capability tests (submit, executor construction). Lifecycle tests (restart, shutdown ordering, dependency graph) stay on `SyncExecutorService`. The "both post-hoc-patched TaskBuckets point at the same service" assertion changes to "all TaskBuckets have `_sync_executor` set from birth" — a simpler, stronger assertion.
- `tests/unit/test_sync_executor_service_saturation.py` — Update to construct `SyncExecutor` directly instead of using the `make_service()` conftest helper. Saturation methods move to `SyncExecutor`.
- `tests/unit/conftest.py` — Replace `make_sync_executor_config`, `make_sync_executor_hassette`, `make_service` with direct `SyncExecutor(max_workers=N)` construction.
- `src/hassette/test_utils/factories.py` — Replace `make_sync_service()` with `make_sync_executor()` — a direct constructor call, no `__new__` bypass.
- `src/hassette/test_utils/fixtures.py` — Rename `sync_service` fixture to `sync_executor`, return `SyncExecutor`.
- `src/hassette/test_utils/mock_hassette.py` — Add `hassette.sync_executor = None` alongside existing `_sync_executor_service`/`sync_executor_service` stubs.
- `tests/unit/task_bucket/test_run_in_thread_*.py` — Update `_sync_service` references to `_sync_executor`, type hints from `SyncExecutorService` to `SyncExecutor`.
- `tests/unit/resources/test_task_bucket_ownership.py` — May need minor import updates.
- `tests/unit/test_service_restart_specs.py` — `SyncExecutorService` stays a service; parametrized assertions unchanged.
- `tests/unit/core/test_hassette_lifecycle.py` — Update mapping entries if they reference `SyncExecutorService` by attribute name.

### New Test Coverage

- **TC#1** (FR#2) — Unit test: `hassette.sync_executor` is a `SyncExecutor` instance immediately after `Hassette.__init__()`, before `wire_services()`.
- **TC#2** (FR#6) — Unit test: Every `TaskBucket` created by the factory has `_sync_executor` set (non-None) from birth — no post-hoc patching.
- **TC#3** (FR#5) — Unit test: After `SyncExecutorService` restart (`on_initialize` called again), `SyncExecutor` object identity is preserved but the pool is fresh.

### Tests to Remove

- Any assertions specifically testing the post-hoc patching behavior (e.g., "both patched TaskBuckets point at the same service instance") — these test workaround mechanics that no longer exist.

## Documentation Updates

- Update `CLAUDE.md` Architecture section — `SyncExecutorService` description should note the `SyncExecutor` capability class it wraps. Mention that `SyncExecutor` is a plain capability class following the Router/AppRegistry pattern.
- No docs-site changes — `SyncExecutorService` is internal framework plumbing not documented in `docs/pages/`.

## Impact

### Changed Files

- **create** `src/hassette/core/sync_executor.py` — New `SyncExecutor` class (capability: thread pool + submit + saturation state)
- **modify** `src/hassette/core/sync_executor_service.py` — Thin lifecycle wrapper; remove capability methods, delegate to `SyncExecutor`; update imports
- **modify** `src/hassette/core/core.py` — Construct `SyncExecutor` in `__init__`; remove post-hoc patching from `wire_services()`; add `sync_executor` attribute
- **modify** `src/hassette/core/command_executor.py` — Update import of `SYNC_WORKER_HANDLE` from `sync_executor_service` to `sync_executor`
- **modify** `src/hassette/task_bucket/task_bucket.py` — Rename `_sync_service` to `_sync_executor`; simplify `_create_task_bucket` factory (direct assignment, no suppress)
- **modify** `src/hassette/test_utils/harness.py` — Remove mirrored patching from `_start_sync_executor`
- **modify** `src/hassette/test_utils/factories.py` — Replace `make_sync_service()` with `make_sync_executor()`
- **modify** `src/hassette/test_utils/fixtures.py` — Rename `sync_service` fixture to `sync_executor`
- **modify** `src/hassette/test_utils/mock_hassette.py` — Add `sync_executor` attribute stub
- **modify** `src/hassette/test_utils/__init__.py` — Update re-exports: `make_sync_service` → `make_sync_executor`, `sync_service` → `sync_executor`
- **modify** `tests/unit/test_sync_executor_service_wiring.py` — Split tests: capability tests use `SyncExecutor`, lifecycle tests use `SyncExecutorService`
- **modify** `tests/unit/test_sync_executor_service_saturation.py` — Construct `SyncExecutor` directly; update method references
- **modify** `tests/unit/conftest.py` — Replace `make_service()`/`make_sync_executor_hassette()` with direct `SyncExecutor` construction
- **modify** `tests/unit/task_bucket/test_run_in_thread_context_propagation.py` — Update `_sync_service` → `_sync_executor`, type hints
- **modify** `tests/unit/task_bucket/test_run_in_thread_executor_routing.py` — Update `_sync_service` → `_sync_executor`, type hints
- **modify** `tests/unit/resources/test_task_bucket_ownership.py` — Minor import updates if needed
- **modify** `tests/unit/core/test_hassette_lifecycle.py` — Update attribute mapping if it references `sync_executor_service` by name
- **modify** `tests/unit/test_make_async_adapter_timeout.py` — Update `_sync_service` → `_sync_executor`
- **modify** `tests/integration/test_thread_leaked_observability.py` — Update `_sync_service` → `_sync_executor`, `.executor` access
- **modify** `tests/integration/conftest.py` — Update fixture assignment from `SyncExecutorService` to `SyncExecutor` type
- **modify** `tests/unit/app/test_app_cache.py` — Update `make_sync_service` → `make_sync_executor` import, `_sync_executor_service`/`sync_executor_service` → `_sync_executor`/`sync_executor` attributes
- **modify** `CLAUDE.md` — Update Architecture section for `SyncExecutorService` description
<!-- Gap check 2026-07-21: 1 gap included — test_app_cache.py:21,156-158 (imports make_sync_service, wires hassette._sync_executor_service) → test update task -->

### Behavioral Invariants

- `TaskBucket.run_in_thread()` API unchanged — callers submit sync work the same way.
- Shutdown-wave ordering: BusService/SchedulerService/AppHandler tear down before the thread pool. Enforced by `depends_on` declarations that remain unchanged.
- `SyncWorkerHandle`/`SYNC_WORKER_HANDLE` contextvar behavior unchanged — `command_executor.py` reads the same contextvar (import path changes from `sync_executor_service` to `sync_executor`).
- Restart-in-place: `ServiceWatcher` can restart `SyncExecutorService` and all `TaskBucket` references remain valid.

### Blast Radius

- **Internal only** — `SyncExecutorService` is framework plumbing, not user-facing API. App authors never import or reference it directly.
- **Test infrastructure** — `make_sync_service()` and `sync_service` fixture consumers need updating (mechanical rename).
- **No downstream consumers** outside this repo — hassette is a framework, but the sync executor is internal plumbing that apps interact with only through `TaskBucket.run_in_thread()`, which is unchanged.

## Open Questions

None — all questions resolved during discovery and blind-spot investigation.
