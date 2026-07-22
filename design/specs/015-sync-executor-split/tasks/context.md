# Context: Split SyncExecutor from SyncExecutorService

## Problem & Motivation

`SyncExecutorService` conflates two concerns: owning a thread pool (passive capability needed by every `TaskBucket`) and participating in the Resource/Service lifecycle (startup, shutdown, supervision). Because `TaskBucket`s are constructed eagerly during `Resource.__init__` — before `wire_services()` runs — two buckets exist before `SyncExecutorService` is available. This forces three workarounds: a `contextlib.suppress(RuntimeError)` in the factory, a post-hoc patching block in `wire_services()`, and a mirrored copy of that patch in the test harness. The test infrastructure also contorts around the conflation — `make_sync_service()` uses `__new__` to bypass `__init__` and manually set only executor-related fields.

## Visual Artifacts

None.

## Key Decisions

1. **SyncExecutor is a plain class, not a Resource** — follows the Router/AppRegistry precedent. This is what makes it constructable before the lifecycle starts.
2. **SyncExecutor built in Hassette.__init__ before super().__init__()** — ensures it exists before any TaskBucket is created.
3. **Hassette's own bucket wired explicitly in __init__** — one line after `super().__init__()`. The factory handles all other buckets. No `getattr` in `TaskBucket.__init__`.
4. **SyncExecutorService stays as a Service for shutdown ordering** — `depends_on` on BusService/SchedulerService/AppHandler remain unchanged.
5. **Saturation monitoring stays co-located with the pool** — `log_saturation_rate_limited()` reads executor private attributes (`_max_workers`, `_work_queue`), so it moves to SyncExecutor. The `serve()` probe loop stays on SyncExecutorService and calls into SyncExecutor.
6. **SyncWorkerHandle and SYNC_WORKER_HANDLE move to sync_executor.py** — they support the capability, not the lifecycle. `command_executor.py`'s import path changes.
7. **rebuild_pool() for restart-in-place** — same SyncExecutor object identity, fresh pool. `restart()` calls `shutdown()` then `initialize()` on the same Service instance; `on_initialize()` calls `rebuild_pool()`.

## Constraints & Anti-Patterns

- Do NOT change `depends_on` declarations on BusService, SchedulerService, or AppHandler.
- Do NOT make SyncExecutor a Resource — the entire point is pre-lifecycle availability.
- Do NOT add `getattr` or any wiring logic to `TaskBucket.__init__` — it stays setting `self._sync_executor = None`. External wiring happens via the factory and one explicit line in `Hassette.__init__`.
- Do NOT create re-exports from `sync_executor_service.py` for moved symbols — update import paths directly.
- The `_sync_service` → `_sync_executor` rename must be complete — no mixed old/new names.

## Design Doc References

- `## Problem` — describes the three workarounds and why they exist
- `## Architecture` — SyncExecutor class design, thinned SyncExecutorService, bootstrap flow, TaskBucket changes
- `## Replacement Targets` — six items being removed or replaced
- `## Test Strategy` — existing tests to adapt, new coverage needed, tests to remove
- `## Impact → Changed Files` — complete file inventory with change verbs
- `## Convention Examples` — Router, AppRegistry, constructor injection, property-with-guard patterns

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

Services receive collaborators as constructor kwargs via `add_child`. `SyncExecutorService` will read `hassette.sync_executor` in its `__init__`.

### Property-with-guard pattern

**Source:** `src/hassette/core/core.py:322-327`

```python
@property
def sync_executor_service(self) -> SyncExecutorService:
    if self._sync_executor_service is None:
        raise _service_not_wired_error("SyncExecutorService")
    return self._sync_executor_service
```

`sync_executor_service` property stays as-is. The new `sync_executor` is a plain attribute set in `__init__`, not a property — no guard needed.
