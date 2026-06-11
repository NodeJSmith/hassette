# Operating Hassette

Hassette runs as a long-lived process. The runtime behaviors that matter in production: how it survives a Home Assistant restart, what happens when a handler raises, how timeouts work, and what degraded-database mode looks like.

## WebSocket Reconnection

The WebSocket connection between Hassette and Home Assistant can drop for many reasons: HA restarts, network blips, clean shutdowns. Hassette recovers automatically using a three-layer retry model. All WebSocket settings live under `[hassette.websocket]` in [`hassette.toml`](../core-concepts/configuration/index.md).

### Layer 1: Initial connection retries

When Hassette first starts (or [`WebsocketService`][hassette.core.websocket_service.WebsocketService] restarts), it tries the WebSocket connection up to `websocket.connect_retry_max_attempts` times (default: 5). Each retry waits longer than the last. Backoff starts at `websocket.connect_retry_initial_wait_seconds` (default: 1s), caps at `websocket.connect_retry_max_wait_seconds` (default: 32s), with jitter added. Tenacity logs a WARNING before each sleep:

```
Retrying hassette.core.websocket_service.WebsocketService._make_connection.<locals>._inner_connect in X.Xs as it raised ...
```

If all five attempts fail, the error reaches layer 3.

### Layer 2: Early-drop retries

A connection is considered "early drop" when it falls within `websocket.early_drop_stable_window_seconds` (default: 30s) of becoming connected. This usually means HA accepted the handshake but then immediately disconnected, which often happens during HA restarts. Hassette retries up to `websocket.early_drop_max_retries` times (default: 5), with backoff starting at `websocket.early_drop_backoff_initial_seconds` (default: 2s) and capping at `websocket.early_drop_backoff_max_seconds` (default: 60s). Each early-drop attempt logs:

```
WebSocket early drop detected (elapsed=X.Xs, attempt=N/5) — retrying
```

Early-drop retries only apply to genuine post-auth disconnects (`ServerDisconnectedError`, [`RetryableConnectionClosedError`][hassette.exceptions.RetryableConnectionClosedError]). Connection-refused errors bypass this layer entirely and go straight to layer 1's retry loop.

### Layer 3: ServiceWatcher restart budget

[`ServiceWatcher`][hassette.core.service_watcher.ServiceWatcher] supervises `WebsocketService` using a sliding-window restart budget: 5 restarts per 300-second window, with 2s–60s exponential backoff between attempts. Once the budget is exhausted, `WebsocketService` enters `EXHAUSTED_COOLING`, a 300-second cooldown, and retries from scratch. The logs show:

```
Service 'WebsocketService' restart budget exhausted (TRANSIENT), entering cooldown for 300.0s (retry_at=1749567890)
```

After the cooldown completes, the budget resets and the full retry sequence starts over. This layer ensures Hassette keeps trying through prolonged HA unavailability without spinning.

### What apps see during reconnection

The bus, scheduler, and state manager stay active during a disconnect. Subscriptions remain registered. Handlers resume without re-registration when the connection restores.

[Api][hassette.api.api.Api] methods (REST calls to HA) and [`StateProxy`][hassette.core.state_proxy.StateProxy] access raise [`ResourceNotReadyError`][hassette.exceptions.ResourceNotReadyError] while the WebSocket is down. Code that calls these during a disconnect must handle that exception or wait for reconnection.

The bus delivers `hassette.event.websocket_disconnected` when the connection drops and `hassette.event.websocket_connected` when it restores. Apps that need to pause or resume behavior based on HA reachability can subscribe to these topics:

```python
--8<-- "pages/operating/snippets/ws_reconnect_events.py:subscribe"
```

### When to tune

**Slow HA restarts.** If HA takes longer than 30s to become responsive after a restart, increase `websocket.early_drop_stable_window_seconds` to cover the typical restart duration. Otherwise early-drop retries expire before HA is ready and fall through to the ServiceWatcher layer.

**Flaky networks.** Increase `websocket.early_drop_max_retries` or `websocket.early_drop_backoff_max_seconds` to give transient network issues more room to recover before escalating.

**Low downtime tolerance.** Reduce `websocket.connect_retry_initial_wait_seconds` to shorten the backoff floor. The jitter is proportional to the initial wait, so a smaller initial value also tightens the jitter band.

**Recovery ceiling.** `websocket.max_recovery_seconds` (default: 300s) caps the total wall-clock time spent across all recovery attempts before the service gives up and the failure escalates to layer 3. Raise it when extended HA outages should be ridden out at this layer instead.

### Per-operation timeouts

Four further `[hassette.websocket]` fields cap individual operations rather than retry behavior: `connection_timeout_seconds` (default: 5s) for establishing the TCP/WebSocket connection, `authentication_timeout_seconds` (default: 10s) for the HA auth handshake, `response_timeout_seconds` (default: 15s) for a reply to a single WebSocket command, and `total_timeout_seconds` (default: 30s) as the aiohttp overall operation ceiling. Slow or high-latency HA hosts (remote instances, constrained hardware) are the usual reason to raise them.

All fields live under `[hassette.websocket]` in `hassette.toml`.

## Handler Exceptions

When a bus handler or scheduler callback raises an unhandled exception, Hassette catches it, logs it at ERROR level, and moves on. The exception does not crash the process, does not affect other handlers running concurrently, and does not prevent future invocations of the same handler.

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
- **`scheduler.job_timeout_seconds`** (default: 600s). The maximum wall-clock time for a scheduled job callback.

Both default to 600 seconds. A handler or job that runs longer than its timeout has its awaitable cancelled; the cancellation is recorded in telemetry and logged at WARNING.

Individual subscriptions and jobs can override the global default:

```python
--8<-- "pages/operating/snippets/timeout_overrides.py:overrides"
```

### Limitations

**Synchronous handlers.** Hassette runs synchronous handlers in a thread executor. `asyncio.timeout` cancels the awaitable wrapping the thread, but it cannot stop the thread itself. A sync handler that ignores cancellation may continue running in the background after the timeout fires. Long-running sync work that needs reliable cancellation requires an `async` implementation.

**Catching `TimeoutError` internally.** A handler that catches `TimeoutError` before it propagates to Hassette prevents the cancellation from taking effect. The handler continues running; the record shows `status='success'`. Catching `TimeoutError` in handler bodies without re-raising it defeats the timeout mechanism.

**`lifecycle.run_sync_timeout_seconds`** (default: 6s) is a separate timeout that applies to calls made from synchronous (non-async) contexts into Hassette's event loop via `task_bucket.run_sync()`. This timeout is not related to handler execution. It governs blocking calls made from threads outside the event loop.

## Startup and Shutdown Timeouts

Hassette starts resources in dependency-ordered waves and shuts them down in reverse. Each phase has its own `[hassette.lifecycle]` ceiling:

| Field | Default | Caps |
|---|---|---|
| `startup_timeout_seconds` | 30s | Each startup wave. Must be ≥ `app_startup_timeout_seconds`, since app readiness is part of a wave. |
| `app_startup_timeout_seconds` | 20s | A single app's `on_initialize`. A slow app times out individually without failing the whole wave budget. |
| `app_shutdown_timeout_seconds` | 10s | A single app's `on_shutdown`. |
| `resource_shutdown_timeout_seconds` | = app shutdown | Each non-app resource's shutdown phase. |
| `total_shutdown_timeout_seconds` | 30s | The entire shutdown, hooks and propagation included. |
| `registration_await_timeout` | 30s | Waiting for pending listener/job database registrations to flush before post-ready reconciliation. |
| `task_cancellation_timeout_seconds` | 5s | Waiting for cancelled tasks to finish before they are abandoned. |

Apps that fetch external data or open slow connections in `on_initialize` are the common reason to raise `app_startup_timeout_seconds` — and `startup_timeout_seconds` with it. The shutdown ceilings matter on constrained hardware where cleanup runs slowly; raising them trades slower restarts for cleaner teardown.

## Scheduler Cadence

The scheduler loop sleeps between runs: until the next due job, clamped between `scheduler.min_delay_seconds` (default 1) and `scheduler.max_delay_seconds` (default 30), or `scheduler.default_delay_seconds` (default 15) when no jobs are queued. A job dispatched more than `scheduler.behind_schedule_threshold_seconds` (default 5) after its scheduled time logs a "behind schedule" WARNING — the signal that handlers are saturating the loop or the host is overloaded. Lower `max_delay_seconds` only when sub-30-second scheduling reactivity to newly added jobs matters; the clamp does not affect job accuracy, only how often the loop re-checks.

## Database Degraded Mode

When the telemetry database is unavailable at startup or becomes unreachable at runtime, Hassette continues operating normally. Apps run, handlers fire, and the scheduler works as expected. Telemetry records are silently dropped rather than blocking execution. The monitoring UI shows zero counts for invocations and logs.

For details on retention, migrations, and the telemetry schema, see [Database & Telemetry](../core-concepts/database-telemetry.md).
