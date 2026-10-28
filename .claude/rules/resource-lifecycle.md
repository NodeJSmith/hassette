---
paths:
  - "src/hassette/resources/**"
  - "tests/unit/resources/**"
---

# Resources — Lifecycle Internals

`Resource` (`base.py`) is the base class for app components (Bus, Scheduler, Api, StateManager). `Service` extends it for background services. Both have lifecycle hooks and child resource tracking with priority-based initialization/shutdown.

## Required vs optional services

Nothing restarts a service in-process. Every concrete `Service` declares `required` in its own class body (`__init_subclass__` in `service.py` rejects an undeclared one at class definition; the declaration is not inherited). A required service's failure ends the process and the external supervisor restarts it; an optional one stays dead in place, announced by one ERROR. Only a service whose parent is `Hassette` may be required: `Service._validate_parent()` runs from `add_child` and rejects the rest, so an app-owned service must declare `required = False`.

**Report contract** (spec 134 D8):

- **Report site and order.** `Service._serve_wrapper()` calls `Hassette.report_service_failure()` first at every failure exit after the handoff (raised exception, `FatalError`, `ClosedResourceError` outside shutdown, and a required service's unrequested return or cancellation), before `handle_failed()`/`handle_crash()`. Those await `send_event()` on a bounded channel, so reporting after them would let a stalled bus delay the report meant to work without it. The report never awaits, and nothing on the fatal path may await either. Pre-handoff init failures and swallowed shutdown-hook failures are never reports.
- **Routing.** `report_service_failure()` routes by the declaration: required goes to `escalate_service_failure()` (the one fatal exit route: latch the reason, request shutdown, emit CRASHED as telemetry), optional gets the one ERROR. A failed optional service is left un-shut-down.
- **After shutdown starts.** A report arriving once `Hassette.shutdown_event` (the process-level event, not the service's own) is set, or once a fatal reason is latched, is logged and not escalated, so a clean stop exits 0.
- **Unrequested return.** For a required service, `serve()` returning or being cancelled with no process shutdown requested (`Service.stop_requested()`; only an optional service counts its own shutdown as a stop) is reported as a `ServeEndedError` and leaves the status FAILED, not STOPPED.
- **Dead bus** (spec 134 D9). The bus is the only component that knows whether the channel is drained, so it owns the close: every exit of `BusService.serve()`'s drain loop closes the event streams (its own receive clone included: a sender blocked on a full channel wakes only when every receive stream is closed) before the wrapper reports, and `Hassette._fail_startup()` calls `close_streams_unless_draining()`. Don't key a close on the bus's status or on `stop_requested()`: both guess. Other fatal exits keep their shutdown telemetry for as long as the bus drains. `Hassette.send_event()` drops every send once the streams close, and `Resource._shutdown_body()` still runs `handle_stop()` with them closed, so every resource reaches STOPPED.
- **Harness and mocks.** `HarnessHassette` overrides `report_service_failure()` as a no-op, and `make_mock_hassette` sets a synchronous no-op, so a required-service failure under a test harness never latches a fatal reason or requests shutdown. A test of the routing itself uses a real `Hassette`.

## Lifecycle functions are module-level, not methods

Lifecycle state transitions (`handle_starting`, `handle_running`, `handle_stop`, `handle_failed`, `handle_crash`, `mark_ready`, `mark_not_ready`, `request_shutdown`, `start`, `cancel`, `create_service_status_event`) and structural operations (`start_children_and_wait`, `register_task_bucket_factory`, `run_hooks`, `ordered_children_for_shutdown`) are module-level functions in `lifecycle.py` and `operations.py`. They take the resource as their first argument (e.g. `mark_ready(self, reason="initialized")`). This keeps the names out of `App`'s public surface (see `App.__dir__`), since they are framework plumbing, not app-author API. `is_ready`, `wait_ready`, and `add_child` remain methods on `Resource`.

New `Resource` subclasses must call `mark_ready()` explicitly — `handle_running()` sets status but does not mark readiness.

## When to call `mark_ready()`

Readiness is what `depends_on` auto-wait and the startup waves block on, so mark ready at the point dependents can actually use the resource:

- **No background loop** (plain `Resource`, or a `Service` whose `serve()` only hosts something already usable): call it at the end of `on_initialize()`, or `after_initialize()` when readiness depends on work that finishes after `on_initialize()` returns (children started, bootstrap wired).
- **`Service` with a `serve()` loop**: call it inside `serve()`, once the loop's prerequisites are open and just before it starts consuming work. `_serve_wrapper()` in `service.py` runs `serve()` after `initialize()` completes, so marking ready in `on_initialize()` would unblock dependents before anything is draining their work.
- A `serve()` that returns goes through `handle_stop()`, which calls `mark_not_ready()`. A service that is disabled by config but must stay ready marks ready in `on_initialize()` and parks `serve()` on `self.shutdown_event.wait()` instead of returning.

`MARK_READY_HOOKS` in `tests/unit/resources/test_mark_ready_timing.py` is the canonical per-class list of which hook each resource marks ready from, enforced via `assert_marks_ready_in()` in `tests/support/ready_timing.py`. The test fails when a new class calls `mark_ready(self)` without being listed, or when a new `Resource` subclass has no readiness source at all (its `NOT_SELF_MARKED` map covers classes marked ready by something else). Add new resources there, not here.

Resources that deviate from these rules, and why:

- **`TaskBucket`** — `__init__()`. It defines no `on_initialize()` and has no setup work, so it is usable as soon as it is constructed. Marking ready at construction means nothing that waits on it blocks on a hook it never runs.
- **`WebApiService`** — `on_initialize()`, after auth and trusted proxies resolve. Readiness does not wait for uvicorn to bind the port in `serve()`. When the web API is disabled it marks ready early and parks `serve()`.
- **`WebsocketService`** — `on_initialize()` marks lifecycle-ready unconditionally so an unreachable HA doesn't time out its startup wave and fatally block later waves. Readiness then stays set until shutdown: the HA connection never clears it. The connection's status is shown only through the ready reason, which `report_connection_status()` replaces via `set_ready_reason()`. Use the connected signal, not `is_ready()`, to mean "HA connected".
- **`AppHandler`** — `after_initialize()`. Its `serve()` runs app bootstrap, which waits on Home Assistant, and no boot wave may; readiness means "wired", not "apps started".
- **`WebUiWatcherService`** — `on_initialize()` when hot reload is disabled (then parks `serve()`), `serve()` when enabled.
- **`FileWatcherService`** — `on_initialize()` when `watch_files` is disabled (then parks `serve()` on `shutdown_event`), `serve()` when enabled.

## Start order and who owns a start failure

`Service._initialize_body()` spawns the serve task as its last step, after `after_initialize()` and child initialization, so RUNNING means the whole body completed (spec 134 D1, D7). A Service's children and `after_initialize()` must not wait on that Service's `serve()` or readiness: serve can't start until they return, so the wait hangs the attempt. At boot that surfaces as the wave timing out.

A failure from STARTING belongs to the attempt's caller: at boot, `Hassette._start_wave()`, which joins each member's attempt (the task `start()` returns) and its readiness through `wait_for_wave()` and fails startup on any failure. A failure after the handoff (RUNNING to FAILED) is a report (above).

A wave also settles on an optional Service member whose attempt succeeded and whose serve task has since ended (`member_settled` in `utils/service_utils.py`): an optional watcher marks ready inside `serve()`, so one whose `serve()` ends first would otherwise hold the wave to its timeout. A required member's serve failure is the process-exit path, not the wave's.

## Teardown reports

Every successful `Resource`/`Service` shutdown attempt returns an immutable `TeardownReport` (`teardown.py`), and `resource.teardown_report` exposes the current unconsumed one. When the coordinator itself raises outside the shutdown body (observing a pending initializer, requesting shutdown), it stores that report before re-raising instead of returning it — `await resource.shutdown()` raises in that case, so read `resource.teardown_report` after catching the exception to see the same evidence a normal completion would have returned.

`is_restart_safe` is derived from the report, never stored directly. It means "no work from the attempt may still be running": `False` when `pending_tasks` is non-empty or a cause in `WORK_MAY_RUN_CAUSES` (`resources/teardown.py`) was recorded, and `True` for a report carrying only diagnostic causes (a hook that raised or timed out and has ended). A shutdown body that raised or was cancelled (`SHUTDOWN_BODY_FAILED`) is restart-unsafe: its report replaces whatever its stages observed, so nothing proves the work ended. One predicate, one name: don't add a second "any cause recorded" predicate; read `causes` for that. `ResourceStatus.STOPPED` is unaffected: it still means lifecycle orchestration reached its terminal phase, and a resource can be `STOPPED` with a report whose `is_restart_safe` is `False`. Only the report — never `STOPPED` — decides whether `start()` or a direct `initialize()` may run again; a report with `is_restart_safe` `False` raises `RestartRefusedError` and has no in-process reset path, including from test-reset helpers.

## One attempt per resource

`LifecycleMixin` owns exactly one paired attempt per resource: `_init_task` is authoritative for every initialization path (`start()`'s joiner, and a direct `initialize()` call), and `_shutdown_task` is authoritative for every shutdown call. Concurrent or repeated callers join the existing task through `asyncio.shield()` instead of starting a second attempt; a repeated `shutdown()` after completion returns the stored report without rerunning hooks.

Both tasks are created directly via `asyncio.Task(...)` (bypassing the loop's TaskBucket-attributing task factory — see `create_lifecycle_task()` in `lifecycle.py`), not through `task_bucket.spawn()`: the shutdown body cancels TaskBucket work, so owning the coordinator inside that same bucket would make it cancel itself.

`_skip_own_shutdown_hooks` is per-attempt shutdown state like `_shutdown_deadline`: the attempt's owner sets it (`skip_own_shutdown_hooks()`, used after a failed app init), it resets wherever `_shutdown_deadline` does (`LifecycleMixin.__init__` and `coordinate_initialize`), and only `Resource._shutdown_body` reads it, skipping the resource's own hooks while the post-hook stage still runs. It isn't propagated to children, and `Service._shutdown_body` ignores it; a new `_shutdown_body` override must decide whether to honor it.

`_shutdown_body_task` is a third, non-admission field — it never gates whether a lifecycle operation may start, but keeps a cancellation-resistant shutdown body reachable and exception-observed until it actually completes, even after the coordinator has already returned a report to its callers.

Every public lifecycle front door (`initialize()`, `start()`, `shutdown()`) rejects a call made from its own active `_init_task`, `_shutdown_task`, or `_shutdown_body_task` with `LifecycleReentryError` before joining, cancelling, or creating anything — a hook cannot recursively drive its own owner's lifecycle.

## Shutdown deadlines

A shutdown attempt carries one absolute deadline, `_shutdown_deadline`, set by the operation that owns it: the root for each exit stage (`Hassette._run_stop_stage()`/`_run_foundation_stage()`) and `AppLifecycleService` for a runtime instance stop (its entry deadline). A parent passes its deadline to its children, and a caller joining an attempt in flight can only tighten it. The helpers live in `resources/shutdown_deadline.py`.

- **Leaves bound themselves.** Each shutdown hook, the serve-task wait, task-cancel, `cleanup()`, the database drain and the executor join get their own cap clamped to what is left of the deadline. A hook cut off by its bound records `SHUTDOWN_HOOK_TIMED_OUT`, distinct from a hook that raised.
- **Interior nodes don't.** The shutdown coordinator and `shutdown_batch()` wait without a bound of their own. Don't add one: a second bound on the same work is what the deadline model replaced.
- **Only owners walk away.** When its deadline passes, an owner force-terminates what hasn't finished and records it with `Hassette.record_force_terminated()`, which makes `hassette run` hard-exit instead of waiting on that work. Registry apps aren't the root's children, so `AppHandler._force_terminal()` names and records its unfinished apps itself. The runtime walk-away bounds its listener/job cleanup with the fixed `WALK_AWAY_CLEANUP_TIMEOUT_SECONDS` (`core/app_lifecycle_instances.py`), not a setting.
- **Foundation services** (`SessionManager`, `DatabaseService`, `SyncExecutorService`) set `shutdown_hook_timeout_applies = False` and are listed in `Hassette._foundation_services()`; a new one needs both, and a test in `test_core_coverage.py` fails when they disagree. Their steps carry fixed caps that sum to `FOUNDATION_SHUTDOWN_BUDGET_SECONDS`.

## No implicit task creation at exit

At exit the root's TaskBucket is sealed and is also the loop's task-factory fallback (`make_task_factory`), so a task created through the loop with no bucket in context is rejected with `TaskBucketSealedError`. Shutdown hooks and the root's exit stages run in lifecycle tasks with no bucket in context. In code that runs there, `asyncio.gather()` over coroutines and, on Python 3.11, `asyncio.wait_for()` both create such tasks implicitly. Wrap each coroutine in `create_lifecycle_task()` before gathering it (as `shutdown_batch()` and `gather_all()` do), and bound a wait with `asyncio.timeout()` instead of `wait_for()`. Tests reproduce the arrangement with `sealed_fallback_task_factory()` in `tests/support/task_buckets.py`; a `wait_for` regression only fails on 3.11.
