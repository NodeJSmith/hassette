# Resource Lifecycle & Supervision

A [`Resource`][hassette.resources.base.Resource] is any component with a managed lifecycle — Hassette initializes and shuts it down in dependency order. A [`Service`][hassette.resources.service.Service] is a long-running background Resource whose `serve()` loop runs for the life of the process. Hassette never restarts a service in-process. Each service declares whether it is required, and that decides whether its failure ends the process or leaves the service dead in place. This page covers that model, the [service state machine](#resource-state-machine), and readiness signaling.

This page belongs to the [internals section](index.md), written for contributors and advanced users such as authors of custom `Service` subclasses. App authors do not need it to build automations. [Apps — Lifecycle](../apps/lifecycle.md) covers the hooks an app implements.

## Required and Optional Services

Every concrete `Service` subclass declares `required` in its own class body. A class that leaves it out fails with a `TypeError` at class definition.

```python
--8<-- "pages/core-concepts/snippets/internals_service_required.py"
```

**Required** means Hassette cannot usefully run without the service. A required service fails when its `serve()` raises after startup, or returns or is cancelled without anyone asking it to stop. The service ends `FAILED` (`CRASHED` for a [`FatalError`][hassette.exceptions.FatalError]), and Hassette records the reason and shuts down. Hassette also emits a `CRASHED` status event for the service to mark the fatal exit, even when the service's own status is `FAILED`. The process exits with a non-zero code and logs `Hassette terminated due to a fatal error: <reason>` at CRITICAL, for example `service 'BusService' crashed: RuntimeError` or `service 'BusService' serve() ended without shutdown`.

**Optional** means Hassette keeps working without the service. If its `serve()` fails, the service stays `FAILED` (`CRASHED` for a [`FatalError`][hassette.exceptions.FatalError]) — dead in place. Nothing shuts it down or restarts it. Hassette logs one ERROR. For a framework service, the message says a Hassette restart brings it back. For a service an app owns, it says reloading the app does. A `serve()` that simply returns is not a failure: an optional service that returns ends as `STOPPED`.

Only a service whose parent is [`Hassette`][hassette.core.core.Hassette] itself can be required. A service is created by its parent's `add_child()`: `Hassette` adds the framework services, and an app adds its own with `self.add_child(MyWatcher)`. `add_child()` rejects a required service under any other parent, so a service an app owns must declare `required = False`. `Service` itself defaults to `required = True`, which is why a subclass must say which one it means.

| Service | `required` | Notes |
|---|---|---|
| [`BusService`][hassette.core.bus_service.BusService] | `True` | Core event dispatch |
| [`SchedulerService`][hassette.core.scheduler_service.SchedulerService] | `True` | Core job execution |
| `SyncExecutorService` | `True` | Thread pool behind synchronous handlers |
| [`WebsocketService`][hassette.core.websocket_service.WebsocketService] | `True` | Home Assistant outages never reach this, since `serve()` [reconnects in place](../../operating/index.md#websocket-reconnection). The flag covers failures inside Hassette, such as a crash in message handling |
| [`DatabaseService`][hassette.core.database_service.DatabaseService] | `True` | Telemetry and session storage |
| [`CommandExecutor`][hassette.core.command_executor.CommandExecutor] | `True` | Persists handler and job execution records |
| [`WebApiService`][hassette.core.web_api_service.WebApiService] | `True` | HTTP API and UI. It also serves the CLI and `/api/health/live`, so a live process with a dead API would leave automations running with no way to observe them |
| `AppHandler` | `True` | Runs app bootstrap; a failed bootstrap would leave Hassette with no apps |
| `FileWatcherService` | `False` | Config hot-reload |
| `WebUiWatcherService` | `False` | Web UI live-reload |

A failed start at boot is fatal for any service, required or not. Hassette exits and names each failed service with its error. A startup wave doesn't wait on an optional service whose `serve()` has already ended.

!!! warning
    Nothing restarts a crashed service inside the process, so a fatal exit leaves Hassette down unless a restart policy supervises it: the Home Assistant add-on Watchdog, a Docker `restart:` policy, or a systemd `Restart=on-failure` unit. See [Fatal exit](../../web-ui/health-endpoints.md#fatal-exit) for policy examples.

### Where the fatal reason goes

The fatal reason is logged and lands in the supervisor's log: `docker logs`, the add-on log, or `journalctl`. Hassette doesn't read it back at startup, so after a crash loop that log holds the cause. The telemetry session record keeps the reason as `error_message` only; the traceback stays in the log.

### When the event bus dies

`BusService` is required, so its failure takes the same fatal exit as any other required service. Its death also means nothing drains the event channel any more. Before the failure is reported, the bus closes that channel and logs `Event bus stopped unexpectedly; event sends are dropped from now on` at WARNING. From then on, every event sent is dropped instead of waiting for room, including a send that was already waiting when the bus died. The shutdown's own status events are dropped too and never reach a listener, but every resource still moves to `STOPPED`, so shutdown finishes instead of hanging.

The bus closes the channel whenever it stops draining, a clean shutdown included, since nothing could deliver a later event. At boot, a failed startup has the bus close the channel before teardown unless the bus is already draining it.

## Resource State Machine

Every [Resource][hassette.resources.base.Resource] and `Service` tracks its status as a [`ResourceStatus`][hassette.ResourceStatus] value.

```mermaid
stateDiagram-v2
    [*] --> NOT_STARTED
    NOT_STARTED --> STARTING : initialize()
    STARTING --> RUNNING : handle_running()
    RUNNING --> STOPPING : shutdown()
    RUNNING --> FAILED : unhandled exception
    STOPPING --> STOPPED : clean exit
    RUNNING --> CRASHED : FatalError raised from serve()
    CRASHED --> [*]
    FAILED --> [*]
    STOPPED --> [*]
```

The diagram's `CRASHED` state is a resource status, and only a `FatalError` escaping `serve()` sets it. When a required service fails any other way, Hassette still emits a `CRASHED` status event, meaning the failure took the process down, but the service's own status stays `FAILED`.

`NOT_STARTED` is the initial state. `STARTING` covers the period from `initialize()` entry through lifecycle hook execution and child initialization. `RUNNING` is the normal operating state. For services, it persists for the lifetime of the `serve()` loop. `STOPPING` and `STOPPED` represent clean shutdown. `FAILED` means `serve()` ended in failure. A required service in `FAILED` ends the process; an optional one stays `FAILED` until shutdown. `CRASHED` is set when a `FatalError` escapes `serve()`, and for a required service Hassette shuts down. Neither state is ever left by a restart.

## Readiness vs Running

`RUNNING` status and readiness are separate signals. `handle_running()` sets `status = ResourceStatus.RUNNING` and emits a status event. `mark_ready()` sets a readiness `asyncio.Event` that dependents wait on. The framework runs that wait itself, before a dependent's lifecycle hooks fire. App and service code never starts the wait.

A service enters `RUNNING` just before its `serve()` loop begins. Hassette starts that loop only after `after_initialize()` and every child's initialization have finished. A failure before that point fails the initialization attempt. A failure inside `serve()` never does. `initialize()` returns while the service is still `STARTING`. A framework-spawned task then calls `handle_running()` and invokes `serve()` immediately after. A service's children and its `after_initialize()` must not wait on the service's own readiness or `serve()`: the loop starts only after they return. At startup, such a wait times out the startup wave. A service signals readiness by calling `mark_ready()` at whatever internal point it is prepared to serve requests. `WebsocketService` calls `mark_ready()` unconditionally during `on_initialize()`, before it attempts a connection. Lifecycle readiness is decoupled from HA connectivity on purpose. Dependents are never blocked when Home Assistant is unreachable. Connection events never clear readiness. The ready reason (`ready_phase`) carries the connection status instead, such as "Not connected to Home Assistant" or "Home Assistant rejected the access token". `BusService` calls it after the internal event stream is open.

`depends_on` lists the resource types a service waits for before running its own `on_initialize()`. The wait is on readiness, not on `RUNNING` status. A dependent service does not proceed until all declared dependencies have called `mark_ready()`.

| Signal | Set by | Waited on by |
|---|---|---|
| `status = RUNNING` | `handle_running()`, just before `serve()` begins | Nothing (informational only) |
| `ready_event` | `mark_ready()` at service-defined readiness point | Dependents via `depends_on` auto-wait |

## Wave Startup and Shutdown

Hassette starts services in dependency order. `DatabaseService` starts first, on its own, so session tracking exists before anything else runs. Services with no `depends_on` start next. Services that declare `depends_on` start after all their dependencies have signaled readiness. Services at the same dependency depth start concurrently as one wave.

A wave finishes when every member has completed initialization and signaled readiness. Readiness alone isn't enough. `WebApiService` owns a `Scheduler` child that runs the web layer's periodic jobs. It signals readiness inside `on_initialize()`, before that child finishes initializing.

A failed initialization fails startup immediately. Hassette exits and names each failed service with its error. Startup never retries a failed initialization in-process; the process supervisor restarts Hassette instead.

[`startup_timeout_seconds`](../../operating/index.md#startup-and-shutdown-timeouts) in `[hassette.lifecycle]` bounds each whole wave. The `DatabaseService` wave also gets `migration_timeout_seconds` in `[hassette.database]` on top, so a slow migration isn't cut off. A wave that runs past the timeout fails startup the same way. The log lists each unfinished service, its children's statuses, and the line its initialization is waiting on.

Shutdown runs in reverse order. Services that depended on others stop first. A service in `STOPPING` waits for its children to reach terminal states before completing.

For the full dependency graph and startup wave diagram, see [Architecture & Data Flow](index.md).

## Teardown Safety and Restart Refusal

This section is for authors of custom `Service` subclasses. Their shutdown hooks and background
tasks produce the teardown evidence this section describes.

`STOPPED` describes lifecycle *phase*, not proof that a resource's work has actually stopped. A
shutdown hook can fail, a child can time out, a background task can ignore cancellation — and the
resource still reaches `STOPPED`, because `STOPPED` only means lifecycle orchestration finished
running. Restarting an object that reached `STOPPED` without that positive proof risks running old
and new work in the same process at once.

Every completed `shutdown()` call returns a [`TeardownReport`][hassette.resources.teardown.TeardownReport] — an
immutable record of what shutdown actually observed. A report carries zero or more
[`TeardownCause`][hassette.resources.teardown.TeardownCause] values (a failed hook, a timed-out child, tasks still
pending, and so on) and the names of any tasks still pending. Its `is_restart_safe` property derives from
those pending tasks and causes:

```python
--8<-- "pages/core-concepts/snippets/internals_teardown_report.py"
```

`is_restart_safe` answers one question: may work from this attempt still be running? It's `False`
when a tracked task or the `serve()` task was still pending, when an initializer didn't finish
being cancelled, when a child's teardown failed, timed out, or was itself restart-unsafe, or when
the evidence is incomplete (the attempt was force-terminated, its coordinator failed, or its
shutdown body raised or was cancelled before its later steps ran). A hook
that raised or timed out and has since ended is still recorded in `causes`, but it leaves the
report restart-safe: nothing from it is still running. Read `causes` for what went wrong and
`is_restart_safe` for whether anything may still run. The property is computed from those fields,
never stored, so the two can't disagree.

An exception raised outside the shutdown body itself — while observing a pending initializer or
requesting shutdown, for example — also counts as negative evidence. The shutdown coordinator (the
single shared task that runs one shutdown attempt for the resource) stores it on
`teardown_report` before re-raising, so `await resource.shutdown()` raises in this case instead of
returning a report. `teardown_report` retains the same restart-unsafe evidence a normal completion
would have returned.

### Inspecting a report

Python callers read the report two ways. The
[`TeardownReport`][hassette.resources.teardown.TeardownReport] reference lists its fields, such as
`causes` and `pending_tasks`, and [`TeardownCause`][hassette.resources.teardown.TeardownCause] lists
every cause value.

- The **return value** of `await resource.shutdown()` — the exact report from that call.
- The **`teardown_report` property** — the current unconsumed report, or `None`. A report is
  *consumed* when the resource initializes again: a restart-safe report is cleared at that point.
  The property is also `None` before any shutdown attempt completes. Prefer the return value when
  history matters; `teardown_report` only reflects the current state.

```python
--8<-- "pages/core-concepts/snippets/internals_teardown_report_inspect.py"
```

The report itself has no WebSocket, REST, or dashboard surface; it is a Python-only inspection
point for framework code and embedding hosts. For app instances, a restart-unsafe teardown is what
sets the [needs-restart flag](../../operating/index.md#instances-that-need-a-restart) in the API,
CLI, and web UI.

### Concurrent lifecycle calls join, they don't race

Each resource owns exactly one initialization task and one shutdown task at a time. Every caller
joins that same task through `asyncio.shield()` instead of starting a second attempt; such a caller
is called a *joiner*. Joiners include the background task `start()` spawns to run `initialize()`,
a direct `await resource.initialize()`, and a second concurrent `shutdown()` call.
Cancelling one caller's *wait* (for example, the caller's own task is cancelled) does not cancel
the underlying attempt; the shared task keeps running for every other joiner. A repeated
`shutdown()` call after the attempt has already completed returns the stored report without
rerunning any hooks.

If `initialize()` is called while a shutdown is in progress, it waits for that shutdown's outcome
before deciding whether a new attempt may start. If `shutdown()` is called while initialization is
still pending, it cancels and observes that initializer first, then runs shutdown hooks — a
resistant initializer that doesn't finish in time makes the resulting teardown restart-unsafe.

### Restart refusal

`start()` and a direct `initialize()` call both check the stored report before doing
anything else. A report with `is_restart_safe` `True` authorizes exactly one new attempt and is
then cleared. A report with `is_restart_safe` `False` raises
[`RestartRefusedError`][hassette.exceptions.RestartRefusedError], which carries the resource's name and the
full report, and no initialization work starts. There is no in-process way to clear a
restart-unsafe report on the same object, not even a test-reset helper.
Once shutdown fails to prove safety, that object is done recovering on its own.

!!! warning
    Restart refusal cannot stop a coroutine or thread that ignores cancellation — Python
    cancellation is cooperative. Refusal prevents the *same object* from starting a second
    incarnation in the *same process*; it does not, and cannot, guarantee that the process itself
    exits. Process replacement after refusal is the embedding host or supervisor's responsibility
    (systemd, Docker, or equivalent), not something Hassette enforces on its own.

### Lifecycle re-entry

A shutdown hook or initialization hook must not call `initialize()`, `start()`, or
`shutdown()` on the same resource — the hook is running *inside* the very coordinator or body task
those calls would try to join or cancel. Every lifecycle front door checks for this before doing
anything else and raises [`LifecycleReentryError`][hassette.exceptions.LifecycleReentryError] immediately. A
hook that cannot continue should raise or return; it cannot recursively drive its own owner's
lifecycle.

## Next Steps

- [Architecture & Data Flow](index.md): event pipeline, service dependency graph, and component ownership
- [Per-Service Internals](service-details.md): bus routing, scheduler dispatch, database schema, state cache, and web layer
- [Apps — Lifecycle](../apps/lifecycle.md): the initialization and shutdown hooks an app implements
- [Operating Hassette](../../operating/index.md#websocket-reconnection): how the WebSocket reconnects through Home Assistant restarts
