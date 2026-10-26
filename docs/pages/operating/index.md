# Operating Hassette

Hassette runs as a long-lived process. The runtime behaviors that matter in production: how it survives a Home Assistant restart, what happens when a handler raises, how timeouts work, and what degraded-database mode looks like.

The defaults cover typical deployments — nothing here is required reading before deploying. This page works best as a reference: jump to the section that matches a symptom rather than reading top to bottom.

## WebSocket Reconnection

Hassette talks to Home Assistant over a WebSocket — a persistent connection that lets HA push events instantly instead of being polled. That connection drops whenever HA restarts, the Supervisor restarts, or the network blips. Hassette never exits because Home Assistant is unreachable. [`WebsocketService`][hassette.core.websocket_service.WebsocketService], the framework component that owns the HA connection, retries in place until HA answers again. Apps never call it directly.

### How fast Hassette reconnects

After a failure, the next attempt comes in about 1 second, then 2, then 4. From then on Hassette tries every 5 seconds until HA answers. Each delay varies randomly by up to 20% (jitter), so many clients restarting together don't all retry at the same instant. A typical HA restart (20–60 seconds) is back within about 5 seconds of HA listening again.

A connection that stays up for 2 minutes resets this sequence. A connection that drops sooner continues it where it left off, so a link that keeps dropping right after connecting settles at one attempt every 5 seconds instead of hammering HA.

These timings are fixed. No `hassette.toml` setting changes them.

### Failures a retry can't fix

Some failures repeat identically until something outside Hassette changes. Hassette retries these every 5 minutes instead of every 5 seconds, and logs an ERROR naming the cause on each attempt:

- **HTTP 401, 403, or 429 during the WebSocket handshake.** These come from a reverse proxy or web application firewall (nginx, Cloudflare, and similar) in front of HA, not from HA itself, so they only apply to proxied setups. A 429 waits for its `Retry-After` header when present, up to 30 minutes. A 404 retries on the normal schedule, because a reverse proxy answers 404 while the HA container behind it restarts.
- **A rejected TLS certificate.** The client refuses an expired certificate, or a self-signed one while `verify_ssl` is on. Other TLS errors, such as a connection reset mid-handshake, retry on the normal schedule. Set `verify_ssl = false` under `[hassette]` in `hassette.toml` to accept a self-signed certificate. See [Authentication](../core-concepts/configuration/index.md#authentication).
- **Oversized messages.** Hassette accepts WebSocket messages up to 16 MiB. A message over that limit closes the connection with close code 1009 (message too big). Three such closes in a row switch to the 5-minute pace. Only very large installs hit this (over roughly 35,000 entities), because the full state list is the largest message HA sends.

The slower pace keeps Hassette under the default ban threshold of fail2ban (a tool that blocks IP addresses after repeated failed requests), and stops a too-large state list from being serialized every few seconds. After the cause is fixed upstream, the next attempt connects. That attempt runs after the current delay: 5 minutes, or the `Retry-After` of a 429 (capped at 30 minutes).

### Rejected access token

When Home Assistant rejects the token, Hassette retries 3 times, 60 seconds apart, then stops connecting and stays up. The retries cover an HA host whose clock is still behind after a reboot, which makes HA reject a valid token briefly. Hassette restarting alongside HA gets the same retries.

While stopped, the Diagnostics page shows the WebSocket service with the reason "Home Assistant rejected the access token", and the log has one CRITICAL line. The service itself stays running and ready. Only its reason changes. Each rejection adds a "Login attempt failed" notification in Home Assistant, up to 4 in total. Create a new long-lived token, update `HASSETTE__TOKEN` (see [Authentication](../core-concepts/configuration/index.md#authentication)), and restart the Hassette process or container.

### Waiting for Home Assistant to finish starting

A freshly restarted HA accepts connections before its integrations finish loading. Hassette does not report itself connected until HA's own startup state, which moves from `STARTING` to `RUNNING`, reaches `RUNNING`. Until then:

- Events from HA are not delivered to apps, so the burst of `unavailable` states during HA's boot never reaches handlers. The one exception is `homeassistant_started`, which the bus delivers right after the connection is up.
- Api calls that go over the WebSocket raise [`ConnectionClosedError`][hassette.exceptions.ConnectionClosedError], the same as during an outage.
- When Hassette itself is starting up, apps don't initialize yet. They start against a fully loaded HA.

HA reaches `RUNNING` within seconds of accepting connections. The Diagnostics page shows the wait as the WebSocket service's reason, "Home Assistant core state is STARTING, waiting for RUNNING". The service itself stays ready.

The `homeassistant_started` event marks an actual HA restart. Hassette delivers it only when it observes HA starting: the event arrives while Hassette waits for `RUNNING`, or while Hassette is already connected. A connection that finds HA already `RUNNING` sees no such event. `hassette.event.websocket_connected` fires on every reconnect, including ones where HA never restarted.

### What the logs show

An outage produces a handful of lines, not one per attempt:

```
WARNING  Lost connection to Home Assistant at ws://homeassistant:8123/api/websocket: ClientConnectorError: ...; reconnecting
WARNING  Home Assistant at ws://homeassistant:8123/api/websocket still unreachable after 5m00s (61 attempts, 0 connections dropped within 120s)
INFO     Reconnected to Home Assistant at ws://homeassistant:8123/api/websocket after 7m12s
```

The "still unreachable" summary repeats every 5 minutes. Individual attempts log at DEBUG. The summary logs at ERROR instead of WARNING when the same unexpected error keeps recurring. Until Hassette has connected at least once, the first failure and each summary also log at ERROR, with a hint to check `base_url`. A mistyped URL shows up this way rather than as an exit.

A link that keeps dropping within 2 minutes of connecting logs its reconnects at DEBUG, and the 5-minute summary counts them ("N connections dropped within 120s"). A drop logs only the "Lost connection" WARNING. There is no separate "Disconnected from Home Assistant" INFO line.

### What apps see during reconnection

The bus, scheduler, and state manager stay active during a disconnect. Subscriptions remain registered. Handlers resume without re-registration when the connection restores.

What each call does while HA is unreachable:

- **`self.states` reads** keep working. [`StateProxy`][hassette.core.state_proxy.StateProxy], Hassette's local cache of HA states, serves the last-known (stale) values. It raises [`ResourceNotReadyError`][hassette.exceptions.ResourceNotReadyError] only if it has never synchronized.
- **[Api][hassette.api.api.Api] calls that go over the WebSocket**, such as `call_service`, raise [`ConnectionClosedError`][hassette.exceptions.ConnectionClosedError].
- **Api calls that go over REST**, such as `self.api.get_state()`, retry and then raise the underlying `aiohttp` client error.

Events during the gap are not replayed. At reconnect, the state cache is replaced with HA's current states, and no state-change events fire for what changed while disconnected. Edge-triggered logic, such as a handler waiting for `light.kitchen` to turn off, misses a transition that happened during the outage. Apps that must reconcile do it in a `hassette.event.websocket_connected` handler by reading current states.

Code that calls HA during a disconnect catches those errors (skip the work, or retry after reconnection), or subscribes to the connection events below and pauses itself while HA is unreachable.

The bus delivers `hassette.event.websocket_disconnected` when the connection drops and `hassette.event.websocket_connected` when it restores. `websocket_connected` marks any reconnect. `homeassistant_started` marks an actual HA restart. The two connection events alternate, starting with connected. A connection that drops while it is being announced still produces both. Apps that need to pause or resume behavior based on HA reachability subscribe to these topics in `on_initialize` via [`on()`](../core-concepts/bus/methods.md), the generic topic subscription:

```python
--8<-- "pages/operating/snippets/ws_reconnect_events.py"
```

Running apps keep reading the last-known states (marked stale) through an outage. Each Api call that fails while HA is down records an error in the telemetry database, so a long outage leaves a trail of failed invocations in the Handlers tab.

!!! warning "`on_initialize` no longer reruns after an HA restart"
    `on_initialize` runs once per Hassette process, and Hassette stays up through an HA restart. Work that HA forgets on restart belongs in a `hassette.event.websocket_connected` handler like the one above. One example is an entity an app creates with `set_state`. That handler runs on every reconnect. Earlier releases exited on an HA restart, so the process restart reran `on_initialize`. Apps that relied on that need the handler. For a signal that HA itself restarted, subscribe to `homeassistant_started`. Events missed during the gap are not replayed. A handler that depends on seeing a transition must re-read state on reconnect.

### Health and supervisors

`/api/health/live` stays 200 through any HA outage or a rejected token, and `/api/health` reports `degraded` (or `starting`, if HA never connected). A supervisor watching the liveness endpoint never restarts Hassette for an HA problem. See [Health Endpoints](../web-ui/health-endpoints.md).

### Per-operation timeouts

`connection_timeout_seconds` under `[hassette.websocket]` (default: 5s) caps how long opening the connection takes. Slow or high-latency HA hosts (remote instances, constrained hardware) are the usual reason to raise it. The other WebSocket timeouts are fixed: 10s for the auth handshake, 15s for a reply to one command, and 30s as the ceiling for one operation.

## Handler Exceptions

When a bus handler or scheduled-job handler raises an unhandled exception, Hassette catches it, logs it at ERROR level, and moves on. The exception does not crash the process, does not affect other handlers running concurrently, and does not prevent future invocations of the same handler.

The telemetry database records the invocation with `status='error'`, including the exception type, message, and traceback. The Handlers tab in the monitoring UI surfaces these records.

The log line for a bus handler failure:

```
Handler error (topic=<topic>, handler=<listener>, exec=<execution_id>)
<traceback>
```

The log line for a scheduler job failure:

```
Job error (job_db_id=<id>, exec=<execution_id>)
<traceback>
```

Registered error handlers on subscriptions or scheduled jobs fire after Hassette logs the exception. They are the right place for alerting integrations, recovery logic, or additional context recording. The error handler itself is subject to a timeout (`lifecycle.error_handler_timeout_seconds`, default 5s) and is not re-raised if it raises.

## Timeouts

Two global timeout defaults apply to all user code:

- **`lifecycle.event_handler_timeout_seconds`** (default: 600s). The maximum wall-clock time for a single bus handler invocation before it is cancelled and recorded as `timed_out`.
- **`scheduler.job_timeout_seconds`** (default: 600s). The maximum wall-clock time for a scheduled job handler.

Both default to 600 seconds. A handler or job that runs longer than its timeout is cancelled; the cancellation is recorded in telemetry and logged at WARNING.

Individual subscriptions and jobs can override the global default:

```python
--8<-- "pages/operating/snippets/timeout_overrides.py:overrides"
```

### Limitations

**Synchronous handlers.** A synchronous (non-`async`) handler runs in a dedicated thread pool. When its timeout fires, the caller unblocks and the invocation is recorded as `timed_out` — but the thread keeps running until it returns naturally. Python cannot forcibly stop a running thread mid-call. The thread holds its pool slot until it completes; if enough threads stall simultaneously, the pool fills and new sync work queues up. At shutdown, Hassette interrupts any threads still alive after the join budget using `SystemExit` — so sync workers do stop at process teardown, within the configured budget.

!!! warning "Shutdown interruption runs `finally` blocks — not proof of clean completion"
    When a sync worker is interrupted at shutdown, Python unwinds its stack normally: every `finally` block and context-manager `__exit__` runs before the thread dies. A `finally` that commits a database write or flushes a file will execute, but the handler did not complete cleanly — only part of its work ran. Do not treat `finally` execution as confirmation that a sync handler finished successfully.

**Pool saturation.** When all workers in the sync-handler pool are blocked, new sync work queues up and no sync handlers or jobs fire until a slot opens. Hassette logs a rate-limited WARNING as the pool approaches its ceiling (default: 75% occupied, at most once every 30s — both configurable). The recourse is to raise `lifecycle.sync_executor_max_workers`, fix the slow handler, or convert it to `async`. See [Sync-handler pool configuration](#sync-handler-pool) below.

**Catching `TimeoutError` internally.** A handler that catches `TimeoutError` before it propagates to Hassette prevents the cancellation from taking effect. The handler continues running; the record shows `status='success'`. Catching `TimeoutError` in handler bodies without re-raising it defeats the timeout mechanism.

**`TimeoutError` raised by your own code.** Only Hassette's own deadline expiring records `timed_out`. A `TimeoutError` that your handler or job raises itself — from `bus.wait_for`, an HTTP client timeout, or `asyncio.timeout()` in your code — is recorded as `error` with a traceback, like any other exception.

**`lifecycle.run_sync_timeout_seconds`** (default: 6s) is a separate timeout that applies to calls made from synchronous (non-async) contexts into Hassette's event loop via `task_bucket.run_sync()`. This timeout is not related to handler execution. It governs blocking calls made from threads outside the event loop.

### Sync-handler pool

Sync handlers, sync jobs, and App sync lifecycle hooks run on a dedicated thread pool owned by Hassette. The pool is separate from the framework's internal thread pool (used by logging and the database), so slow sync handlers cannot starve framework internals.

`[hassette.lifecycle]` fields control the pool and its saturation WARNING:

| Field | Default | Effect |
|---|---|---|
| `sync_executor_max_workers` | `min(32, cpu_count + 4)` | Pool ceiling — the maximum number of sync workers that can run concurrently. |
| `sync_executor_saturation_warn_threshold` | `0.75` | Fraction of the pool that must be occupied before the saturation WARNING fires. |
| `sync_executor_saturation_warn_rate_limit_seconds` | `30.0` | Minimum seconds between repeated saturation WARNINGs. |

When the pool nears its ceiling (≥ `sync_executor_saturation_warn_threshold`, 75% by default), Hassette logs a rate-limited WARNING at most once every `sync_executor_saturation_warn_rate_limit_seconds` (30s by default). The WARNING fires on submission and from a periodic background probe, so it appears even when the pool is fully starved and no new work is being submitted. A lower threshold provides earlier headroom alerts on quiet instances. A higher rate-limit window reduces repeated WARNINGs on busy instances that operate near the ceiling by design.

At shutdown, Hassette joins workers for up to 10 seconds (`SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS`). Threads still alive after the join attempt receive `SystemExit`. That is best-effort: C-blocked threads such as `time.sleep()` or native I/O can't be interrupted at the Python level. A thread that survives the join is logged at ERROR, and Hassette exits without waiting for it (see [How shutdown is bounded](#how-shutdown-is-bounded)).

## Startup and Shutdown Timeouts

Hassette starts its internal components — database, WebSocket connection, bus, scheduler, then apps — in dependency order, so each one is ready before anything that depends on it. Shutdown runs in reverse. Each phase has its own `[hassette.lifecycle]` ceiling:

| Field | Default | Caps |
|---|---|---|
| `startup_timeout_seconds` | 30s | Each startup wave, from starting its services until all have initialized and are ready. Must be ≥ `app_startup_timeout_seconds`, since app readiness is part of a wave. |
| `app_startup_timeout_seconds` | 20s | A single app's `on_initialize`. A slow app times out individually without failing the whole wave budget. |
| `shutdown_timeout_seconds` | 10s | Each shutdown hook: an app's `before_shutdown`, `on_shutdown` and `after_shutdown`, and each framework component's. |
| `total_shutdown_timeout_seconds` | 45s | The entire shutdown. Must be more than the foundation stage's fixed 20 seconds. |
| `task_cancellation_timeout_seconds` | 5s | Waiting for cancelled tasks to finish before they are abandoned. |

Apps that fetch external data or open slow connections in `on_initialize` are the common reason to raise `app_startup_timeout_seconds` — and `startup_timeout_seconds` with it. The shutdown ceilings matter on constrained hardware where cleanup runs slowly; raising them trades slower restarts for cleaner teardown.

### How shutdown is bounded

Shutdown runs in two stages:

1. **Stop stage.** Apps and every framework component except the database and the worker threads stop here. Apps stop concurrently, so a slow app never shortens another app's hooks. The stage gets `total_shutdown_timeout_seconds` minus the foundation stage's budget: 25 seconds by default.
2. **Foundation stage.** The session record is finalized, the database drains and closes, and the worker threads join. This stage has a fixed 20-second budget (`FOUNDATION_SHUTDOWN_BUDGET_SECONDS`) and runs even when the stop stage ran out of time.

Last, Hassette writes the [shutdown snapshot](../getting-started/addon/operating.md#backups), if one is configured. Nothing bounds the snapshot copy.

Each hook gets `shutdown_timeout_seconds`, or less when its stage has less time left. A hook that outlives its bound is cancelled. `AppSync`'s shutdown hooks (`before_shutdown_sync`, `on_shutdown_sync`, `after_shutdown_sync`) share the worker-thread pool, so when more of them run at once than there are workers, the wait for a thread counts against each hook's bound. When a stage runs out of time, Hassette stops waiting: it force-terminates whatever hasn't finished and logs one ERROR naming each component.

Stopping or reloading a single app at runtime gets the same limit as the stop stage. A stop that runs past it ends as a failed, timed-out stop, and the app's listeners and jobs are removed.

When Hassette force-terminated work at any point, or worker threads survived the join, `hassette run` exits as soon as shutdown finishes. It logs one ERROR naming what was left, and doesn't wait for that work. A process supervisor would otherwise have to kill it. An exit whose only problem is abandoned work still exits 0.

!!! warning "Give your supervisor more time than Hassette needs"
    Set your supervisor's stop grace period above `total_shutdown_timeout_seconds` plus time for the snapshot. The Docker compose example uses 60 seconds for the 45-second default. A shorter grace period kills Hassette mid-shutdown, which can skip the session record and leave the previous snapshot in place.

!!! warning "Upgrading from the old shutdown settings"
    `app_shutdown_timeout_seconds`, `resource_shutdown_timeout_seconds` and `sync_executor_shutdown_timeout_seconds` no longer exist. A config that still sets one fails to load, and Hassette won't start until you remove it. Use `shutdown_timeout_seconds` for the per-hook bound.

    `total_shutdown_timeout_seconds` now includes the foundation stage's fixed 20 seconds, so an explicit value leaves 20 seconds less for stopping apps than it used to. A config that set it to 30 gets a 10-second stop stage. A supervisor grace period of 45 seconds, which older versions of the compose example used, can kill Hassette before the shutdown snapshot is written; use 60.

## Scheduler Cadence

The scheduler checks for due jobs on a sleep-wake loop. It sleeps until the next due job, waking at least every 30 seconds to re-check the queue. Adding or removing a job wakes it immediately. The sleep cadence is not configurable.

A job that fires more than `scheduler.behind_schedule_threshold_seconds` (default 5) after its scheduled time logs a "behind schedule" WARNING. That warning means too many handlers are running at once or the host is overloaded.

## Database Degraded Mode

When the telemetry database is unavailable at startup or becomes unreachable at runtime, Hassette continues operating normally. Apps run, handlers fire, and the scheduler works as expected. Telemetry records are silently dropped rather than blocking execution. The monitoring UI shows zero counts for invocations and logs.

For details on retention, migrations, and the telemetry schema, see [Database & Telemetry](../core-concepts/database-telemetry.md).
