---
paths:
  - "src/hassette/resources/**"
  - "tests/unit/resources/**"
  - "src/hassette/core/service_watcher.py"
---

# Resources — Lifecycle Internals

`Resource` (`base.py`) is the base class for app components (Bus, Scheduler, Api, StateManager). `Service` extends it for background services. Both have lifecycle hooks and child resource tracking with priority-based initialization/shutdown.

## Supervision

Services declare a `restart_spec` class attribute (`RestartSpec`) that controls supervision behavior: restart type (`PERMANENT`, `TRANSIENT`, or `TEMPORARY`), sliding-window budget (intensity + period), backoff parameters, and error routing (fatal vs. non-retryable error names). The `ServiceWatcher` reads this spec when a service fails.

## Lifecycle functions are module-level, not methods

Lifecycle state transitions (`handle_starting`, `handle_running`, `handle_stop`, `handle_failed`, `handle_crash`, `mark_ready`, `mark_not_ready`, `request_shutdown`, `start`, `cancel`, `create_service_status_event`) and structural operations (`start_children_and_wait`, `restart`, `register_task_bucket_factory`, `run_hooks`, `ordered_children_for_shutdown`) are module-level functions in `lifecycle.py` and `operations.py`. They take the resource as their first argument (e.g. `mark_ready(self, reason="initialized")`). This keeps the names out of `App`'s public surface (see `App.__dir__`), since they are framework plumbing, not app-author API. `is_ready`, `wait_ready`, and `add_child` remain methods on `Resource`.

New `Resource` subclasses must call `mark_ready()` explicitly — `handle_running()` sets status but does not mark readiness.

## When to call `mark_ready()`

Readiness is what `depends_on` auto-wait and the startup waves block on, so mark ready at the point dependents can actually use the resource:

- **No background loop** (plain `Resource`, or a `Service` whose `serve()` only hosts something already usable): call it at the end of `on_initialize()`, or `after_initialize()` when readiness depends on work that finishes after `on_initialize()` returns (children started, bootstrap wired).
- **`Service` with a `serve()` loop**: call it inside `serve()`, once the loop's prerequisites are open and just before it starts consuming work. `_serve_wrapper()` in `service.py` runs `serve()` after `initialize()` completes, so marking ready in `on_initialize()` would unblock dependents before anything is draining their work.
- A `serve()` that returns goes through `handle_stop()`, which calls `mark_not_ready()`. A service that is disabled by config but must stay ready marks ready in `on_initialize()` and parks `serve()` on `self.shutdown_event.wait()` instead of returning.

`tests/unit/resources/test_mark_ready_timing.py` is the canonical, enforced copy of this table (via `assert_marks_ready_in()` in `tests/support/ready_timing.py`) and fails when a new class calls `mark_ready(self)` without being listed, or when a new `Resource` subclass has no readiness source at all (its `NOT_SELF_MARKED` map covers classes marked ready by something else). Update both together.

| Hook | Resources |
|---|---|
| `on_initialize()` | `Api`, `ApiResource`, `ApiSyncFacade`, `AppBootstrapCoordinator`, `AppLifecycleService`, `Bus`, `BusSyncFacade`, `EventStreamService`, `HelperClient`, `HelperClientSyncFacade`, `LoggingService`, `RecordingApi`, `RuntimeQueryService`, `Scheduler`, `SchedulerSyncFacade`, `ServiceWatcher`, `SessionManager`, `StateProxy`, `TelemetryQueryService`, `_ScheduledJobQueue` |
| `after_initialize()` | `AppHandler`, `StateManager` |
| `__init__()` | `TaskBucket` |
| `serve()` | `BusService`, `CommandExecutor`, `DatabaseService`, `SchedulerService`, `SyncExecutorService` |
| `serve()` (deviation) | `FileWatcherService` |
| `on_initialize()` (deviation) | `WebApiService` |
| `on_initialize()`, `serve()` (deviation) | `WebUiWatcherService` |
| `on_initialize()`, `start_recv_and_subscribe()` (deviation) | `WebsocketService` |

Services that deviate from the `serve()` rule, and why:

- **`WebApiService`** — `on_initialize()`, after auth and trusted proxies resolve. Readiness does not wait for uvicorn to bind the port in `serve()`. When the web API is disabled it marks ready early and parks `serve()`.
- **`WebsocketService`** — `on_initialize()` marks lifecycle-ready unconditionally so an unreachable HA doesn't time out its startup wave and fatally block later waves; `start_recv_and_subscribe()` (reached from `serve()`) re-marks ready after each successful connect, since a dropped connection calls `mark_not_ready()`. Use the connected signal, not `is_ready()`, to mean "HA connected".
- **`WebUiWatcherService`** — `on_initialize()` when hot reload is disabled (then parks `serve()`), `serve()` when enabled.
- **`FileWatcherService`** — `serve()` returns without ever marking ready when `watch_files` is disabled.

## Teardown reports

Every successful `Resource`/`Service` shutdown attempt returns an immutable `TeardownReport` (`teardown.py`), and `resource.teardown_report` exposes the current unconsumed one. When the coordinator itself raises outside the shutdown body (observing a pending initializer, requesting shutdown), it stores that report before re-raising instead of returning it — `await resource.shutdown()` raises in that case, so read `resource.teardown_report` after catching the exception to see the same evidence a normal completion would have returned.

`is_restart_safe` is derived from the report's recorded `TeardownCause` values, never stored directly — `True` only when a completed attempt recorded zero causes. `ResourceStatus.STOPPED` is unaffected: it still means lifecycle orchestration reached its terminal phase, and a resource can be `STOPPED` with a report whose `is_restart_safe` is `False`. Only the report — never `STOPPED` — decides whether `restart()`, `start()`, or a direct `initialize()` may run again; a report with `is_restart_safe` `False` raises `RestartRefusedError` and has no in-process reset path, including from test-reset helpers.

## One attempt per resource

`LifecycleMixin` owns exactly one paired attempt per resource: `_init_task` is authoritative for every initialization path (`start()`'s joiner, a direct `initialize()` call, and `restart()`), and `_shutdown_task` is authoritative for every shutdown call. Concurrent or repeated callers join the existing task through `asyncio.shield()` instead of starting a second attempt; a repeated `shutdown()` after completion returns the stored report without rerunning hooks.

Both tasks are created directly via `asyncio.Task(...)` (bypassing the loop's TaskBucket-attributing task factory — see `create_lifecycle_task()` in `lifecycle.py`), not through `task_bucket.spawn()`: the shutdown body cancels TaskBucket work, so owning the coordinator inside that same bucket would make it cancel itself.

`_shutdown_body_task` is a third, non-admission field — it never gates whether a lifecycle operation may start, but keeps a cancellation-resistant shutdown body reachable and exception-observed until it actually completes, even after the coordinator has already returned a report to its callers.

Every public lifecycle front door (`initialize()`, `start()`, `restart()`, `shutdown()`) rejects a call made from its own active `_init_task`, `_shutdown_task`, or `_shutdown_body_task` with `LifecycleReentryError` before joining, cancelling, or creating anything — a hook cannot recursively drive its own owner's lifecycle.
