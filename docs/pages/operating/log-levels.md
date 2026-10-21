# Log Level Tuning

Hassette lets you set log verbosity independently for each internal service. Start from the symptom, narrow to the service, and turn up only what you need.

## Symptom Lookup

Find your symptom and set the field it maps to. Leave everything else at `INFO`.

| Symptom | Field to set |
|---------|--------------|
| Events not firing or wrong handlers triggering | `logging.bus_service` |
| Jobs not running or firing at the wrong time | `logging.scheduler_service` |
| App not loading, crashing on start, or not reloading | `logging.app_handler` |
| Unexpected state values or stale cached state | `logging.state_proxy` or `logging.api` |
| WebSocket errors, HA connection drops, reconnection loops | `logging.websocket` |
| High API call latency or HTTP errors from Home Assistant | `logging.api` |
| Noisy file-change messages during development | `logging.file_watcher` |
| Web UI not responding or showing errors | `logging.web_api` |

At `DEBUG`, `logging.web_api` also logs one line per HTTP request (uvicorn's access log). At any other level, those lines are off.

## How It Works

All log level settings live under `[hassette.logging]` in `hassette.toml`. Each service has a dedicated field. Set it to a Python log level string: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` (case-insensitive).

Fields you leave unset inherit the global `log_level`. The global `log_level` defaults to `INFO` when not set.

```toml
--8<-- "pages/operating/snippets/basic_example.toml"
```

Setting `log_level = "DEBUG"` at the top level raises verbosity for every service at once. Per-service fields let you override specific services up or down without touching the rest.

## Debug Flags

Two boolean flags in `[hassette.logging]` control event bus debug output. The bus processes every state change and service call from Home Assistant — hundreds of events per minute in an active home — which is why its debug output is gated separately from log levels.

| Field | Default | Effect |
|-------|---------|--------|
| `all_hass_events` | `false` | Log every event received from Home Assistant |
| `all_hassette_events` | `false` | Log every event that didn't come from Home Assistant: framework events and topics your apps publish with `bus.emit` |

Set both to `true` to log every event the bus processes. The bus logs these events at `DEBUG`, so they only appear when `bus_service` is set to `DEBUG` (or `log_level` is, and `bus_service` is left unset).

`log_format` controls the output structure:

| Value | Effect |
|-------|--------|
| `"auto"` | Console format when running in a terminal, JSON when running as a service or in a container (default) |
| `"console"` | Human-readable format with colors and alignment |
| `"json"` | Structured JSON, one object per line |

`log_persistence_level` sets the minimum level for log entries written to the [telemetry database](../core-concepts/database-telemetry.md) — the local store the `hassette log` CLI command and the web dashboard's log view both read from. Defaults to `log_level`. `DEBUG` makes debug output queryable via `hassette log` and visible on the dashboard.

Persistence can never be stricter than what's actually being logged. Setting `log_persistence_level` above `log_level` (e.g. `WARNING` while `log_level` stays `INFO`) is a configuration error, because records shown in the console would be missing from the log view. Left unset, it follows `log_level`, so raising `log_level` to `DEBUG` lowers the persistence floor with it.

`log_persistence_level` is only useful for persisting *more* than the default. A per-service override that logs at `DEBUG` while the global `log_level` stays `INFO` requires `log_persistence_level` to be `DEBUG` as well. There's no setting that makes storage quieter than whatever is currently being logged.

`log_retention_days` (default 30) sets how long persisted records live before the hourly retention pass deletes them. It must be ≤ `retention_days` under `[hassette.database]` (see [Database & Telemetry](../core-concepts/database-telemetry.md)).

`log_queue_max` (default 2000) caps how many records can wait for persistence at once. When the queue is full, new records are dropped rather than blocking the app. Raise it only if sustained `DEBUG` persistence reports drops.

## Attaching Loggers Outside the `hassette.` Tree

Python loggers nest by name — `hassette.scheduler` sits under `hassette`, and Hassette's pipeline only wires up that `hassette.*` tree, plus `py.warnings`. A logger created elsewhere — `logging.getLogger("my_app.notify")` in an app's own module, or a third-party library's own logger — inherits Python's default `WARNING` threshold and prints unformatted to stderr instead. Its `INFO` calls never fire, and even its `WARNING`/`ERROR` calls skip console formatting and the telemetry database.

`extra_loggers` attaches additional logger names to the exact same pipeline as `hassette` — same handlers, same level, same formatter:

```toml
--8<-- "pages/operating/snippets/extra_loggers.toml"
```

No renaming required. A logger named in `extra_loggers` keeps its own name in every log line; it just stops being invisible.

## Dropped Log Records

Log records pass through two bounded queues on their way to the database, and each drops records independently when it fills. The Diagnostics page reports them separately, as does `GET /api/health`:

| Counter | Field | Raise this |
|---------|-------|------------|
| Log queue full | `log_queue_drops` | `log_queue_max` under `[hassette.logging]` |
| DB write queue full | `db_write_queue_drops` | `write_queue_max` under `[hassette.database]` |

The log pipeline drops records at two independent queue boundaries. `log_queue_drops` counts records dropped before any handler receives them. These records are absent from console output and the database. `db_write_queue_drops` counts records dropped after the persistence handler receives them. These records can remain visible in configured console output, but are absent from the database and dashboard log view.

Both counters are cumulative since process start. Neither affects app behavior — dropping is what keeps a burst of logging from blocking your automations.

## Per-App Log Levels

Each app sets its own log level with `log_level` in that app's config section.

```toml
--8<-- "pages/operating/snippets/per_app_log_level.toml"
```

The per-app `log_level` lives under `[hassette.apps.<key>]` — `<key>` is the app's section name in `hassette.toml`, the same key `hassette app` lists. Apps without an explicit `log_level` inherit `logging.apps`, which in turn defaults to the global `log_level`.

An app's `log_level` covers the lines its own code writes: `self.logger` and any logger you create under it with `self.logger.getChild(...)`. Lines Hassette writes about the app come from framework loggers and follow framework levels:

| Lines about your app | Logger | Level field |
|----------------------|--------|-------------|
| Starting, stopping, hook failures, readiness | `hassette.apps.<instance_name>.Lifecycle` | `logging.app_handler` |
| Listener and job activity | the app's `Bus` and `Scheduler` children | `logging.bus_service`, `logging.scheduler_service` |

These lines still carry your app's name and instance, so the app's own log view and `hassette log --app <key>` show them. They are marked `framework`, not `app`, so `--source-tier app` leaves them out. To see an app's lifecycle detail, set `logging.app_handler = "DEBUG"`.

!!! note "Upgrading from 0.59 or earlier"
    Lifecycle lines about an app used to be written on the app's own logger, so they followed the app's `log_level` and were marked `app`. They now follow `logging.app_handler` and are marked `framework`. An app at `DEBUG` no longer shows Hassette's lifecycle detail unless `app_handler` is also `DEBUG`, and an app at `ERROR` now shows lifecycle warnings, such as cleanup timeouts, at the default `app_handler` level.

## Runtime Log Level Changes

`PUT /api/logs/level` changes a logger's effective level on a running instance — no restart, no `hassette.toml` edit. The change applies immediately to both structlog and stdlib callers on that logger:

```bash
curl -X PUT http://127.0.0.1:8126/api/logs/level \
  -H "Content-Type: application/json" \
  -d '{"logger": "hassette.scheduler", "level": "DEBUG"}'
```

The response reports the logger's new effective level: `{"logger": "hassette.scheduler", "effective_level": "DEBUG"}`. Unknown levels and empty logger names return `422` with code `validation_failed` (see [API Error Responses](../web-ui/api-errors.md)).

The change lives in process memory only — a restart reverts to the configured levels. Use it to capture debug output from a live issue, then turn the level back down the same way.

## Examples

### Debugging the Scheduler

```toml
--8<-- "pages/operating/snippets/debug_scheduler.toml"
```

With `scheduler_service = "DEBUG"`, Hassette logs trigger evaluation, next-run calculations, and job execution timing. Other services stay at `INFO`.

### Quieting the File Watcher

```toml
--8<-- "pages/operating/snippets/quiet_file_watcher.toml"
```

The file watcher logs every detected change at `INFO`. In active development this creates noise. `WARNING` suppresses routine detection messages and only surfaces errors.

### Debugging HA Communication

```toml
--8<-- "pages/operating/snippets/debug_ha_comms.toml"
```

`websocket = "DEBUG"` shows raw WebSocket message traffic. `api = "DEBUG"` shows each REST call and response. Use both together when troubleshooting connectivity issues or unexpected state values coming from Home Assistant.

## Full Field Reference

All fields, their types, and defaults are in the [`LoggingConfig`][hassette.config.models.LoggingConfig] API reference.
