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

## Teardown reports

Every successful `Resource`/`Service` shutdown attempt returns an immutable `TeardownReport` (`teardown.py`), and `resource.teardown_report` exposes the current unconsumed one. When the coordinator itself raises outside the shutdown body (observing a pending initializer, requesting shutdown), it stores that report before re-raising instead of returning it — `await resource.shutdown()` raises in that case, so read `resource.teardown_report` after catching the exception to see the same evidence a normal completion would have returned.

`is_restart_safe` is derived from the report's recorded `TeardownCause` values, never stored directly — `True` only when a completed attempt recorded zero causes. `ResourceStatus.STOPPED` is unaffected: it still means lifecycle orchestration reached its terminal phase, and a resource can be `STOPPED` with a report whose `is_restart_safe` is `False`. Only the report — never `STOPPED` — decides whether `restart()`, `start()`, or a direct `initialize()` may run again; a report with `is_restart_safe` `False` raises `RestartRefusedError` and has no in-process reset path, including from test-reset helpers.

## One attempt per resource

`LifecycleMixin` owns exactly one paired attempt per resource: `_init_task` is authoritative for every initialization path (`start()`'s joiner, a direct `initialize()` call, and `restart()`), and `_shutdown_task` is authoritative for every shutdown call. Concurrent or repeated callers join the existing task through `asyncio.shield()` instead of starting a second attempt; a repeated `shutdown()` after completion returns the stored report without rerunning hooks.

Both tasks are created directly via `asyncio.Task(...)` (bypassing the loop's TaskBucket-attributing task factory — see `create_lifecycle_task()` in `lifecycle.py`), not through `task_bucket.spawn()`: the shutdown body cancels TaskBucket work, so owning the coordinator inside that same bucket would make it cancel itself.

`_shutdown_body_task` is a third, non-admission field — it never gates whether a lifecycle operation may start, but keeps a cancellation-resistant shutdown body reachable and exception-observed until it actually completes, even after the coordinator has already returned a report to its callers.

Every public lifecycle front door (`initialize()`, `start()`, `restart()`, `shutdown()`) rejects a call made from its own active `_init_task`, `_shutdown_task`, or `_shutdown_body_task` with `LifecycleReentryError` before joining, cancelling, or creating anything — a hook cannot recursively drive its own owner's lifecycle.
