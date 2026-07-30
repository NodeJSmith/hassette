---
task_id: "T03"
title: "Add bootstrap coordinator and admission"
status: "planned"
depends_on: ["T02"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#7", "FR#25", "FR#29", "FR#30", "FR#32", "FR#33", "AC#1", "AC#3", "AC#4", "AC#17", "AC#20", "AC#21", "AC#23", "AC#24"]
---

## Summary
Introduce the one authoritative app-bootstrap release owner and move every app-creation path behind it. This task rewires the resource graph, narrows `AppHandler`'s dependency model, adds explicit admission modes to the shared creation boundary, and makes manual start/reload plus file/config reconciliation obey the new pre-release policy without leaking waiters. The result should be that no app instance can exist before release, while delayed Home Assistant recovery still bootstraps apps exactly once.

## Target Files
- create: `src/hassette/core/app_bootstrap_coordinator.py`
- modify: `src/hassette/core/core.py`
- modify: `src/hassette/core/app_handler.py`
- modify: `src/hassette/core/app_lifecycle_service.py`
- modify: `src/hassette/web/routes/apps.py`
- modify: `src/hassette/test_utils/reset.py`
- modify: `tests/unit/core/test_app_handler_readiness.py`
- modify: `tests/unit/core/test_app_lifecycle_service.py`
- modify: `tests/unit/core/test_app_lifecycle_service_operations.py`
- modify: `tests/unit/core/test_app_lifecycle_service_coverage.py`
- modify: `tests/integration/test_apps.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- read: `src/hassette/core/api_resource.py`
- read: `src/hassette/core/file_watcher.py`
- read: `src/hassette/core/state_proxy.py`

## Prompt
Implement the `## Architecture -> AppBootstrapCoordinator Resource` section from the design doc.

Create `src/hassette/core/app_bootstrap_coordinator.py` as a narrow `Resource` that depends on `ApiResource`, `BusService`, `SchedulerService`, `StateProxy`, and `SyncExecutorService`. It should mark itself lifecycle-ready once wiring is complete, then wait in coordinator-owned background work for StateProxy's initial-capability API. Publish a separate process-latched release capability (for example `wait_released()`) that opens once, never recloses on runtime disconnect, and is canceled on shutdown.

In `src/hassette/core/core.py`, construct and expose the coordinator in the resource graph. In `src/hassette/core/app_handler.py`, reduce `depends_on` to the coordinator and stop duplicating app-facing readiness composition. In `src/hassette/core/app_lifecycle_service.py`, move all creation enforcement to `start_app()` with explicit internal admission modes: bootstrap may wait, manual start/reload must fail fast with a typed unreleased error, and pre-release config/file reconciliation must coalesce to one latest desired state instead of stacking waiters. Update `src/hassette/web/routes/apps.py` to map the typed unreleased error to an explicit retryable HTTP response for manual start/reload.

Preserve the non-goals: no per-app capability declarations, no re-blocking after runtime disconnect, no generic orchestration platform, and no second unchecked app-creation path for tests or helpers.

## Focus
- `src/hassette/core/app_handler.py` currently waits for `ApiResource`, `BusService`, `SchedulerService`, `StateProxy`, and `SyncExecutorService` directly, then blocks the startup wave inside `after_initialize()`; this task must replace that composition with the coordinator rather than layering on top.
- `src/hassette/core/app_lifecycle_service.py` is the lowest shared mutation boundary for bootstrap, manual start/reload, and file/config change handling; admission enforcement belongs here, not in route handlers or facades.
- `src/hassette/test_utils/reset.py` directly calls `bootstrap_apps()` and must select the explicit bootstrap admission path rather than bypassing the release contract.
- Reverse-dependency gaps to include here: `src/hassette/web/routes/apps.py` and `tests/integration/web_api/test_endpoints.py` cover manual start/reload semantics; `tests/integration/test_apps.py` and the `handle_change_event()` paths in `AppLifecycleService` are the file/config reconciliation callers; `src/hassette/core/file_watcher.py` remains the event source and should stay simple.
- Preserve `AppLifecycleService`'s existing manifest persistence, blocked-app reconciliation, and once-lifecycle bootstrap flow; only change the admission boundary and pre-release scheduling behavior needed by the design.
- Shutdown semantics matter: the coordinator's wait must cancel cleanly so framework teardown never blocks on Home Assistant recovery.

## Verify
- [ ] FR#1: There is exactly one process-latched bootstrap release capability that authoritatively answers whether apps may start.
- [ ] FR#2: The release decision stays closed until API, bus, scheduler, sync execution, and StateProxy initial capability are all available.
- [ ] FR#3: App bootstrap remains blocked while Home Assistant has not reached external websocket readiness.
- [ ] FR#4: App bootstrap remains blocked until the initial state snapshot succeeds.
- [ ] FR#5: App bootstrap remains blocked until snapshot plus synchronization-local journal commit complete in order.
- [ ] FR#7: Delayed Home Assistant recovery releases bootstrap without restarting the process.
- [ ] FR#25: Once the release latch opens, a later disconnect neither closes it nor stops, suspends, or re-blocks existing and subsequent app lifecycle operations.
- [ ] FR#29: Shutdown cancels bootstrap waits instead of waiting for Home Assistant to recover.
- [ ] FR#30: No app instance is created before the coordinator release opens.
- [ ] FR#32: Manual start/reload before release fails immediately with an explicit retryable response path.
- [ ] FR#33: Pre-release config/file changes coalesce to one latest desired reconciliation instead of accumulating waiters.
- [ ] AC#1: `AppHandler` depends on one bootstrap prerequisite representing the full app-bootstrap decision.
- [ ] AC#3: Delayed connectivity plus successful snapshot/journal commit bootstraps apps exactly once.
- [ ] AC#4: Recoverable initial connection/snapshot/journal failures keep apps blocked while normal recovery continues.
- [ ] AC#17: A runtime disconnect after release leaves running apps registered and does not re-enable admission blocking.
- [ ] AC#20: Framework shutdown cancels an indefinitely waiting bootstrap coordinator without delaying teardown.
- [ ] AC#21: Every app-creation path is fenced by the shared admission boundary before release and stays allowed after later disconnects.
- [ ] AC#23: Manual HTTP start/reload before release returns an explicit retryable response and retains no waiting task.
- [ ] AC#24: Repeated config and file-watcher changes before release retain only the latest desired reconciliation and run once after release.
