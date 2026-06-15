---
task_id: "T03"
title: "Add SyncExecutorService and wire it into the lifecycle graph"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#5"]
---

## Summary
Introduce `SyncExecutorService`, a `Service` that owns the `InterruptibleThreadPoolExecutor` from T01 (constructed in `__init__`, sized from the T02 config), exposes it as `hassette.sync_executor`, and tears it down in its shutdown hook within the configured budget. Register it as a Hassette child and add `depends_on=[SyncExecutorService]` to the services that submit sync user work, so wave-based shutdown guarantees the executor outlives every component that could submit to it. This is the lifecycle skeleton; the saturation probe and end-to-end interruption behavior land in T05, and routing lands in T04.

## Prompt
1. **Create `src/hassette/core/sync_executor_service.py`** defining `SyncExecutorService(Service)` (follow the `BusService` template in `context.md` and `src/hassette/core/bus_service.py`):
   - `depends_on: ClassVar[list[type[Resource]]] = []` (it needs no DB or other service).
   - Declare a `restart_spec: ClassVar[RestartSpec]` (use `RestartType.PERMANENT` like the other services; mirror `bus_service.py`).
   - In `__init__`, construct `self.executor = InterruptibleThreadPoolExecutor(max_workers=hassette.config.lifecycle.sync_executor_max_workers, thread_name_prefix="hassette-sync")`. Construct it here (not in a startup hook) so there is no `None` window before the run loop starts.
   - Implement `serve()` to `mark_ready(...)` and then loop until `shutdown_event.is_set()` (the saturation probe body is added in T05 — for now a minimal sleep/shutdown-event loop is fine; leave a clearly-marked extension point).
   - Implement the shutdown hook (`on_shutdown` or `after_shutdown` per the `Service` lifecycle in `src/hassette/resources/service.py`) to call `self.executor.shutdown(timeout=<remaining budget>)`. Compute the budget as `hassette.config.lifecycle.sync_executor_shutdown_timeout_seconds`, but cap it at the *remaining* total shutdown budget if that is tracked by the lifecycle (check how `total_shutdown_timeout_seconds` is enforced; if no running clock is available, pass the configured value — the T02 validator guarantees it is under the total).

2. **Register in `src/hassette/core/core.py`** `wire_services()` (`:149-225`): add `self._sync_executor_service = self.add_child(SyncExecutorService)` early (it has no dependencies — place it before `DatabaseService` at `:164`; note `:163` is `EventStreamService`). Registration *order* in `wire_services()` does not determine start/stop sequencing — the `depends_on` graph does (validated at `:197-222`); place it early only for readability, and add a brief code comment saying so to avoid implying order-significance. Expose `sync_executor` as a property on `Hassette` returning `self._sync_executor_service.executor` so `TaskBucket` (T04) can reach it via `self.hassette.sync_executor`.

3. **Add dependency edges** so the executor shuts down after its consumers:
   - `src/hassette/core/bus_service.py:43` — add `SyncExecutorService` to `depends_on`.
   - `src/hassette/core/scheduler_service.py:35` — add `SyncExecutorService` to `depends_on`.
   - `src/hassette/core/app_handler.py:39-45` — add `SyncExecutorService` to `depends_on` (its App sync lifecycle hooks at `app.py:152-177` submit through `run_in_thread`).
   - Judgment call: `CommandExecutor` (`command_executor.py:77`) orchestrates handler execution but the sync submission happens via the TaskBucket inside the awaited handler, driven by Bus/Scheduler — adding the edge there is optional. Only add it if reconnaissance shows `CommandExecutor` itself submits sync work directly; otherwise note why it was omitted.

Add/extend unit or integration tests asserting the service constructs the executor at init and is registered in the dependency graph such that it shuts down after Bus/Scheduler/AppHandler. Verify graph validity still passes (`core.py:197-222`). Run the affected test files with `uv run pytest <files> -v` (never `-n auto`).

## Focus
- `Service` base and lifecycle hooks are in `src/hassette/resources/service.py`; `depends_on` is declared as a `ClassVar` on the base at `resources/base.py:102`. Each concrete `Service` should declare `restart_spec` or a warning is emitted.
- Services are registered via `self.add_child(...)` in `core.py:wire_services()` (`:163-171`). The dependency graph is validated at `:197-222` — adding a node with `depends_on=[]` and new edges pointing at it must keep the graph acyclic (it will; the executor is a leaf dependency).
- Wave-based shutdown tears down dependents before dependencies. With Bus/Scheduler/AppHandler depending on `SyncExecutorService`, the executor's shutdown hook runs only after those services have finished — closing the "submit to a dead pool → RuntimeError" race.
- Do NOT route `run_in_thread` here — that is T04. Do NOT add the saturation probe body or the interruption integration tests here — that is T05. Keep this task to lifecycle + wiring.
- `restart_spec` semantics: a `ThreadPoolExecutor` that fails is unusual; PERMANENT matches the other long-lived services. Confirm against `bus_service.py`.

## Verify
- [ ] FR#5: `SyncExecutorService` constructs its `InterruptibleThreadPoolExecutor` in `__init__` (no `None` window), is registered as a Hassette child and reachable via `hassette.sync_executor`, declares `depends_on=[]`, and `BusService`/`SchedulerService`/`AppHandler` declare `depends_on=[SyncExecutorService]` so the dependency graph orders the executor's teardown after them; graph validation still passes, and a regression test confirms an AppSync shutdown hook submitting sync work during shutdown completes without `RuntimeError: cannot schedule new futures after shutdown`.
