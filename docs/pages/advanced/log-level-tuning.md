# Log Level Tuning

Hassette lets you set log verbosity independently for each internal service. This is useful when you need to debug a specific area (e.g. the scheduler) without flooding your logs with noise from everything else.

## When to Use This

If something isn't working as expected, narrow the noise before enabling global `DEBUG`. Start from the symptom:

| Symptom | Service to tune |
|---------|----------------|
| Events not firing, wrong filters | `bus_service_log_level` |
| Jobs not running, wrong timing | `scheduler_service_log_level` |
| App not loading or crashing on start | `app_handler_log_level` |
| Unexpected state values, stale data | `state_proxy_log_level` or `api_log_level` |
| HA connection drops, WebSocket errors | `websocket_log_level` |
| High API call latency, HTTP errors | `api_log_level` |
| Noisy file-change messages in development | `file_watcher_log_level` |
| Web UI not responding, dashboard errors | `web_api_log_level` |

## How It Works

Every service in Hassette has a dedicated `*_log_level` configuration field. When set, that service uses the specified level instead of the global `log_level`. When not set, the service inherits the global `log_level` (which defaults to `INFO`).

```toml
--8<-- "pages/advanced/snippets/log-level-tuning/basic_example.toml"
```

## Available Fields

Hassette provides 13 per-service log level fields:

| TOML Field | Controls |
|------------|----------|
| `database_service_log_level` | Database service (telemetry storage, retention, heartbeats) |
| `bus_service_log_level` | Event bus service (event dispatch, listener management) |
| `scheduler_service_log_level` | Scheduler service (job scheduling, trigger evaluation) |
| `app_handler_log_level` | App handler (app lifecycle, loading, starting, stopping) |
| `web_api_log_level` | Web API service (HTTP endpoints, dashboard) |
| `websocket_log_level` | WebSocket service (Home Assistant connection) |
| `service_watcher_log_level` | Service watcher (monitors service health, restarts) |
| `file_watcher_log_level` | File watcher (detects code changes for hot reload) |
| `task_bucket_log_level` | Task buckets (async task execution pools) |
| `command_executor_log_level` | Command executor (app action dispatch) |
| `apps_log_level` | Default level for all apps (can be overridden per-app) |
| `state_proxy_log_level` | State proxy (Home Assistant state cache) |
| `api_log_level` | API client (REST and WebSocket calls to Home Assistant) |

All fields accept standard Python log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (case-insensitive).

## Fallback Behavior

Each `*_log_level` field follows this precedence:

1. **Explicit value** — if you set the field in `hassette.toml`, that value is used.
2. **Global `log_level`** — if the field is not set, it inherits the global `log_level`.
3. **Default** — if neither is set, the level is `INFO`.

This means setting `log_level = "DEBUG"` raises the verbosity of every service at once, while individual fields let you override specific services up or down.

## Per-App Log Levels

The `apps_log_level` field sets the default log level for all your automation apps. You can also override the log level for a specific app in its configuration:

```toml
--8<-- "pages/advanced/snippets/log-level-tuning/per_app_log_level.toml"
```

See [App Configuration](../core-concepts/apps/configuration.md) for details on per-app settings.

## Examples

### Debugging the Scheduler

```toml
--8<-- "pages/advanced/snippets/log-level-tuning/debug_scheduler.toml"
```

This produces detailed output about job trigger evaluation, next-run calculations, and execution timing without affecting other services.

### Quieting the File Watcher

```toml
--8<-- "pages/advanced/snippets/log-level-tuning/quiet_file_watcher.toml"
```

The file watcher logs every detected file change at `INFO` level. In development with frequent saves, this can be noisy. Setting it to `WARNING` suppresses routine change detection messages.

### Debugging Home Assistant Communication

```toml
--8<-- "pages/advanced/snippets/log-level-tuning/debug_ha_comms.toml"
```

This shows detailed WebSocket message traffic and REST API call/response details. Useful when troubleshooting connectivity issues or unexpected state values.

## See Also

- [Global Configuration](../core-concepts/configuration/global.md) — all configuration fields including `log_level`
- [App Configuration](../core-concepts/apps/configuration.md) — per-app log level overrides
