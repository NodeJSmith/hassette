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

## How It Works

All log level settings live under `[hassette.logging]` in `hassette.toml`. Each service has a dedicated field. Set it to a Python log level string: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` (case-insensitive).

Fields you leave unset inherit the global `log_level`. The global `log_level` defaults to `INFO` when not set.

```toml
--8<-- "pages/operating/snippets/basic_example.toml"
```

Setting `log_level = "DEBUG"` at the top level raises verbosity for every service at once. Per-service fields let you override specific services up or down without touching the rest.

## Debug Flags

Three boolean flags in `[hassette.logging]` control event bus debug output. The bus processes every state change and service call from Home Assistant — hundreds of events per minute in an active home — which is why its debug output is gated separately from log levels.

| Field | Default | Effect |
|-------|---------|--------|
| `all_events` | `false` | Log every event the bus processes, both HA and Hassette |
| `all_hass_events` | inherits `all_events` | Log every event received from Home Assistant |
| `all_hassette_events` | inherits `all_events` | Log every internal Hassette framework event |

Set `all_events = true` to enable both at once. Set `all_hass_events` or `all_hassette_events` individually to target one side.

`log_format` controls the output structure:

| Value | Effect |
|-------|--------|
| `"auto"` | Console format when running in a terminal, JSON when running as a service or in a container (default) |
| `"console"` | Human-readable format with colors and alignment |
| `"json"` | Structured JSON, one object per line |

`log_persistence_level` sets the minimum level for log entries written to the [telemetry database](../core-concepts/database-telemetry.md) — the local store the `hassette log` CLI command queries. Defaults to `INFO`. Set to `DEBUG` if you want debug output queryable via `hassette log`.

## Per-App Log Levels

`logging.apps` sets the default log level for all your automation apps. Override it for a specific app in that app's config section.

```toml
--8<-- "pages/operating/snippets/per_app_log_level.toml"
```

The per-app `log_level` under `[hassette.apps.<key>]` takes precedence over `logging.apps` — `<key>` is the app's section name in `hassette.toml`, the same key `hassette app` lists. Apps without an explicit `log_level` fall back to `logging.apps`, which falls back to the global `log_level`.

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
