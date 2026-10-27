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
| Saved edits not triggering an app reload | `logging.file_watcher` |
| Web UI not responding or showing errors | `logging.web_api` |

At `DEBUG`, `logging.web_api` also logs one line per HTTP request (uvicorn's access log). At any other level, those lines are off.

## How It Works

All log level settings live under `[hassette.logging]` in `hassette.toml`. Each service has a dedicated field. Set it to a Python log level string: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` (case-insensitive).

Fields you leave unset inherit the global `log_level`. The global `log_level` defaults to `INFO` when not set.

Hassette applies `[hassette.logging]` once, at startup, so an edit there takes effect on the next restart. After the restart, the service's `DEBUG` lines appear under its logger name, such as `hassette.SchedulerService`. [Runtime Log Level Changes](#runtime-log-level-changes) changes a level without a restart.

```toml
--8<-- "pages/operating/snippets/basic_example.toml"
```

Setting the global `log_level = "DEBUG"` in `[hassette.logging]` raises verbosity for every service at once. Per-service fields let you override specific services up or down without touching the rest.

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
| `"compact"` | Console format trimmed for narrow screens: time-only timestamp, no level padding. The add-on's default; `"auto"` never picks it. |
| `"json"` | Structured JSON, one object per line |

Console and compact lines name what each line is about in one bracketed column before the message:

```
14:44:54 [info] [garage_door] Door opened
14:44:55 [error] [hassette:garage_door @41c09e7b] Handler failed
14:44:56 [info] [WebsocketService] Connected to Home Assistant
```

- `[garage_door]` marks a line the `garage_door` app instance wrote.
- `[hassette:garage_door]` marks a line Hassette wrote about that instance, such as an error from one of its handlers.
- `@41c09e7b` is the end of the execution ID of the handler or job run that wrote the line. Every line from one run carries the same ID.
- A line about no app shows its logger name, without the `hassette.` prefix.

Console lines carry nothing else. App key, listener and job IDs, and the full execution ID are in JSON output and in the telemetry database.

A JSON line logged with `stack_info=True` carries the call stack under `stack`. A JSON line logged with an exception carries the formatted traceback under `exception`. Both keys work the same for `logging` loggers (such as `self.logger`) and structlog loggers.

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

Each app sets its own log level with `log_level` in that app's `config`.

```toml
--8<-- "pages/operating/snippets/per_app_log_level.toml"
```

`<key>` in `[hassette.apps.<key>]` is the app's section name in `hassette.toml`, the same key `hassette app` lists. Apps without an explicit `log_level` inherit `logging.apps`, which in turn defaults to the global `log_level`. Setting `apps = "WARNING"` under `[hassette.logging]` makes `WARNING` the default for every app.

An app's `log_level` covers the lines its own code writes: `self.logger` and any logger created under it with `self.logger.getChild(...)`. Lines Hassette writes about the app come from framework loggers, which follow framework levels by default:

| Lines about the app | Logger | Default level field |
|---------------------|--------|---------------------|
| Starting, stopping, hook failures, readiness | `hassette.apps.<instance_name>.Lifecycle` | `logging.app_handler` |
| Listener and job activity | the app's `Bus` and `Scheduler` children | `logging.bus_service`, `logging.scheduler_service` |
| API calls and state reads | the app's `Api` and `StateManager` children | `logging.api`, `logging.state_proxy` |
| Task spawning and cleanup | the app's `TaskBucket` | `logging.task_bucket` |

These lines still carry the app's name and instance, so the app's own log view and `hassette log --app <key>` show them. They are marked `framework`, not `app`. Below ERROR, the web UI hides them until **all framework lines** is on, and `hassette log` hides them until `--author all` is passed. `--author app` leaves them out entirely.

[Where an App's Logs Go](log-identity.md) explains how each line's author, subject and execution are set, and how to tell Hassette's problems from an app's.

### Hassette's Lines About One App

`framework_log_level` in an app's `config` sets the level of every logger in the table above, for that instance only. The app's own `log_level` is unaffected, so an app can stay at `INFO` while Hassette's detail about it runs at `DEBUG`:

```toml
--8<-- "pages/operating/snippets/per_app_framework_log_level.toml"
```

With `framework_log_level` unset, those loggers follow the `logging.*` fields in the table. `logging.app_handler = "DEBUG"` shows lifecycle detail for every app at once.

Shared services, such as the command executor that runs handlers and jobs, also write lines about apps. Their loggers serve every app, so `framework_log_level` doesn't reach them. Their warnings and errors about an app still show at default levels; raise their own `logging.*` field (`logging.command_executor`) for their debug detail.

!!! note "Upgrading from 0.59 or earlier"
    Lifecycle lines about an app used to be written on the app's own logger, so they followed the app's `log_level` and were marked `app`. They now follow the app's `framework_log_level`, else `logging.app_handler`, and are marked `framework`. An app at `DEBUG` no longer shows Hassette's lifecycle detail unless its `framework_log_level` is also `DEBUG`. An app at `ERROR` now shows lifecycle warnings, such as cleanup timeouts, at the default `app_handler` level.

## Runtime Log Level Changes

`PUT /api/logs/level` changes a logger's effective level on a running instance — no restart, no `hassette.toml` edit. The change applies immediately to both structlog and stdlib callers on that logger:

```bash
--8<-- "pages/operating/snippets/set_log_level.sh"
```

`8126` is the default `port` under `[hassette.web_api]`. For a container, use the host port the container publishes. For a remote instance, use that server's address. The snippet reads the web API token from a `HASSETTE_TOKEN` shell variable you set first. [Enabling and Accessing](../web-ui/index.md#enabling-and-accessing) on the Web UI page covers where that token comes from and which requests don't need one.

The response reports the logger's new effective level: `{"logger": "hassette.SchedulerService", "effective_level": "DEBUG"}`. Unknown levels and empty logger names return `422` with code `validation_failed` (see [API Error Responses](../web-ui/api-errors.md)).

The change lives in process memory only — a restart reverts to the configured levels. Use it to capture debug output from a live issue, then turn the level back down the same way.

### Logger Names

A `[hassette.logging]` field can set the level of several loggers. Each Hassette service logger is named `hassette.<ClassName>`, and a service's own helpers add their class name under it:

| Field | Loggers |
|-------|---------|
| `database_service` | `hassette.DatabaseService`, `hassette.SessionManager` |
| `bus_service` | `hassette.BusService`, `hassette.EventStreamService`, `hassette.Bus` |
| `scheduler_service` | `hassette.SchedulerService`, `hassette.SchedulerService._ScheduledJobQueue`, `hassette.Scheduler` |
| `app_handler` | `hassette.AppHandler`, `hassette.AppHandler.AppLifecycleService`, `hassette.AppBootstrapCoordinator` |
| `web_api` | `hassette.WebApiService`, `hassette.RuntimeQueryService`, `hassette.TelemetryQueryService` |
| `websocket` | `hassette.WebsocketService` |
| `file_watcher` | `hassette.FileWatcherService`, `hassette.WebUiWatcherService` |
| `command_executor` | `hassette.CommandExecutor` |
| `state_proxy` | `hassette.StateProxy`, `hassette.StateManager` |
| `api` | `hassette.ApiResource`, `hassette.Api`, `hassette.Api.HelperClient` |
| `task_bucket` | `<owner>.TaskBucket` for every logger above, as in `hassette.SchedulerService.TaskBucket` |

Some services also own a `Bus` or `Scheduler`, and `Bus`, `Scheduler`, and `Api` each own a sync facade. These loggers add their class name under their owner, as in `hassette.StateProxy.Bus` or `hassette.Bus.BusSyncFacade`. They follow the field for their own class (`bus_service`, `scheduler_service`, or `api`), not the field for their owner.

To match what a field does at runtime, send one `PUT` for each logger in its row. Most of the time you only need the first one, which writes the service's main activity. The `web_api` access log is the exception: Hassette turns it on or off from `logging.web_api` when the web server starts, so a `PUT` doesn't change it. Edit `logging.web_api` and restart instead.

An app's own logger is `hassette.apps.<instance_name>`, using the app's [instance name](../core-concepts/apps/configuration.md#instance-names). [Per-App Log Levels](#per-app-log-levels) lists the loggers for Hassette's lines about an app.

Every one of these loggers carries its own level, so a change reaches only the logger it names. Setting `hassette` leaves `hassette.SchedulerService` at its configured level. An app restart also reapplies the configured levels to that app's loggers.

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

The file watcher logs each detected change at `DEBUG`. A global `log_level = "DEBUG"` adds a line per saved file. Setting `file_watcher = "INFO"` drops those lines while every other service stays at `DEBUG`. At the default `INFO`, the watcher writes nothing per change. The reload lines after an edit come from `logging.app_handler`.

### Debugging HA Communication

```toml
--8<-- "pages/operating/snippets/debug_ha_comms.toml"
```

`websocket = "DEBUG"` shows raw WebSocket message traffic. `api = "DEBUG"` shows each REST call and response. Use both together when troubleshooting connectivity issues or unexpected state values coming from Home Assistant.

## Full Field Reference

All fields, their types, and defaults are in the [`LoggingConfig`][hassette.config.models.LoggingConfig] API reference.
