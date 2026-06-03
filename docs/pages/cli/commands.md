# Command Reference

All commands support `--json` for structured output and `--debug` for verbose error details. [Configuration & Scripting](configuration.md#output-modes) covers output modes in detail.

## `hassette run`

Starts the Hassette framework server, connects to Home Assistant, loads apps, and starts the web API.

```bash
hassette run
```

### Flags

| Flag | Description |
|---|---|
| `--token`, `-t` | Home Assistant access token. Overrides config file and environment. |
| `--base-url`, `-u`, `--url` | Base URL of the Home Assistant instance. |
| `--verify-ssl` | Whether to verify SSL certificates. |
| `--dev-mode` | Enables developer mode. |

All flags are optional. Values resolve from the TOML config file and environment variables when not provided on the command line.

## `hassette status`

Reports system health: connection state, uptime, app count, entity count, and version.

```console
$ hassette status
╭──────────────────── SystemStatusResponse ────────────────────╮
│  status               ok                                     │
│  websocket_connected  True                                   │
│  uptime_seconds       16.57                                  │
│  entity_count         103                                    │
│  app_count            3                                      │
│  services_running     ["EventStreamService", ...]            │
│  version              0.32.0                                 │
│  boot_issues          []                                     │
╰──────────────────────────────────────────────────────────────╯
```

`boot_issues` lists apps that failed to initialize. An empty list means all apps started cleanly.

**API endpoint:** `GET /api/health`

## `hassette app`

Lists all loaded apps with key, display name, status, instance count, and recent invocation counts.

```console
$ hassette app
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ App Key         ┃ Status  ┃ Display     ┃ Instances ┃ Invoc/1h ┃ Enabled ┃ File              ┃
┃                 ┃         ┃ Name        ┃           ┃          ┃         ┃                   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ config_app      │ running │ ConfigApp   │ 1         │ 0        │ True    │ config_app.py     │
│ trivial_app     │ running │ TrivialApp  │ 1         │ 0        │ True    │ trivial_app.py    │
│ bus_handler_app │ running │ BusHandler… │ 1         │ 0        │ True    │ bus_handler_app.py│
└─────────────────┴─────────┴─────────────┴───────────┴──────────┴─────────┴───────────────────┘
```

### Subcommands

| Subcommand | Description | API endpoint |
|---|---|---|
| `hassette app` | Lists all apps. | `GET /api/apps/manifests` |
| `hassette app health <key>` | Health metrics for one app. | `GET /api/telemetry/app/{key}/health` |
| `hassette app activity <key>` | Recent activity feed. | `GET /api/telemetry/app/{key}/activity` |
| `hassette app config <key>` | Resolved configuration. | `GET /api/apps/{key}/config` |
| `hassette app source <key>` | Source file path. | `GET /api/apps/{key}/source` |

### `hassette app health <key>`

Reports health metrics for an app: error rate, average handler and job duration, and overall health status.

```console
$ hassette app health bus_handler_app
╭──────── AppHealthResponse ────────╮
│  error_rate            0.0        │
│  error_rate_class      good       │
│  handler_avg_duration  0.0        │
│  job_avg_duration      0.0        │
│  last_activity_ts                 │
│  health_status         excellent  │
╰───────────────────────────────────╯
```

`--instance` and `--since` scope the metrics window:

```bash
hassette app health my-app --instance office --since 6h
```

### `hassette app activity <key>`

Recent handler invocations and job executions for an app, as a unified activity feed. Columns: ID, kind (`handler` or `job`), status, app key, handler name, duration, timestamp, and error type.

```bash
hassette app activity my-app --since 30m --limit 20
```

### `hassette app config <key>`

The resolved configuration for an app, as loaded from all sources (TOML, env vars, defaults).

```bash
hassette app config my-app
```

### `hassette app source <key>`

The source file path for an app.

```bash
hassette app source my-app
```

### Flags

| Flag | Applies to | Description |
|---|---|---|
| `--instance` | `health`, `activity` | Filters to a specific app instance (index or name). |
| `--since` | `health`, `activity` | Time window for metrics. See [formats](#--since-format). |
| `--source-tier` | `health` | Filters by source tier: `app`, `framework`, or `all`. |
| `--limit` | `activity` | Maximum records to return. |
| `--json` | all | Outputs as JSON. |

## `hassette listener`

Lists all registered event bus listeners, or shows invocation history for a specific listener.

```console
$ hassette listener
┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━┳━━━━━┳━━━━━━┓
┃ ID ┃ App              ┃ Target                    ┃ Kind       ┃ Handler              ┃ Total ┃ OK ┃ Fail ┃ Avg ┃ Last ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━╇━━━━━╇━━━━━━┩
│ 10 │ bus_handler_app  │ light.kitchen_main        │ state_cha… │ on_light_change      │ 0     │ 0  │ 0    │ 0ms │      │
└────┴──────────────────┴───────────────────────────┴────────────┴──────────────────────┴───────┴────┴──────┴─────┴──────┘
```

Each row shows the listener ID, app key, target entity, listener kind, handler method, invocation counts (total, successful, failed), average duration, and last invocation time.

Passing a listener ID shows its invocation history:

```bash
hassette listener 10 --since 1h --limit 20
```

The invocation table shows status, duration, error type, error message, timestamp, and execution ID for each invocation.

### Flags

| Flag | Description |
|---|---|
| `--app <key>` | Filters to listeners belonging to this app. |
| `--instance <n>` | Filters to a specific app instance. Requires `--app`. |
| `--since <duration>` | Time window for invocation counts and history. |
| `--source-tier <tier>` | Filters by `app`, `framework`, or `all`. |
| `--limit <n>` | Maximum invocation records (when viewing a specific listener). |
| `--json` | Outputs as JSON. |

**API endpoints:**

- `hassette listener` hits `GET /api/bus/listeners`
- `hassette listener --app <key>` hits `GET /api/telemetry/app/{key}/listeners`
- `hassette listener <id>` hits `GET /api/telemetry/listener/{id}/executions`

## `hassette job`

Lists all scheduled jobs, or shows execution history for a specific job.

```console
$ hassette job
┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━┳━━━━━┳━━━━━━━━━━┓
┃ ID ┃ App              ┃ Handler              ┃ Trigger  ┃ Schedule ┃ Total ┃ OK ┃ Fail ┃ Avg ┃ Next Run ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━╇━━━━━╇━━━━━━━━━━┩
│ 1  │ config_app       │ StateProxy.sync_all  │ interval │ every    │ 0     │ 0  │ 0    │ 0ms │ soon     │
└────┴──────────────────┴──────────────────────┴──────────┴──────────┴───────┴────┴──────┴─────┴──────────┘
```

Each row shows the job ID, app key, handler method, trigger type, schedule label, execution counts, average duration, and next scheduled run time.

Passing a job ID shows its execution history:

```bash
hassette job 1 --limit 20
```

The execution table shows status, duration, error type, error message, timestamp, and execution ID for each run.

### Flags

| Flag | Description |
|---|---|
| `--app <key>` | Filters to jobs belonging to this app. |
| `--instance <n>` | Filters to a specific app instance. Requires `--app`. |
| `--since <duration>` | Time window for execution history. |
| `--source-tier <tier>` | Filters by `app`, `framework`, or `all`. |
| `--limit <n>` | Maximum execution records (when viewing a specific job). |
| `--json` | Outputs as JSON. |

**API endpoints:**

- `hassette job` hits `GET /api/scheduler/jobs`
- `hassette job --app <key>` hits `GET /api/telemetry/app/{key}/jobs`
- `hassette job <id>` hits `GET /api/telemetry/job/{id}/executions`

## `hassette log`

Recent log entries from the in-memory log buffer.

```console
$ hassette log --limit 5
┏━━━━━━━━━┳━━━━━━━┳━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ When    ┃ Level ┃ App ┃ Instance ┃ Function            ┃ Message                    ┃
┡━━━━━━━━━╇━━━━━━━╇━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 31s ago │ INFO  │     │          │ run_forever         │ Hassette is running.       │
│ 31s ago │ INFO  │     │          │ run_forever         │ All services started       │
│         │       │     │          │                     │ successfully.              │
│ 32s ago │ INFO  │     │          │ serve               │ Web API server starting    │
│         │       │     │          │                     │ on 0.0.0.0:8126            │
│ 32s ago │ INFO  │     │          │ _auto_wait_depend…  │ Waiting for dependencies:  │
│         │       │     │          │                     │ [RuntimeQueryService, …]   │
│ 32s ago │ INFO  │     │          │ _auto_wait_depend…  │ Waiting for dependencies:  │
│         │       │     │          │                     │ [BusService, StateProxy, …]│
└─────────┴───────┴─────┴──────────┴─────────────────────┴────────────────────────────┘
```

`--instance` is not supported on this command; the CLI exits with a usage error if provided. `--app` filters by app key.

### Flags

| Flag | Description |
|---|---|
| `--app <key>` | Filters to log entries from this app. |
| `--since <duration>` | Time window filter. |
| `--limit <n>` | Maximum number of entries to return. |
| `--source-tier <tier>` | Filters by `app`, `framework`, or `all`. |
| `--json` | Outputs as JSON. |

**API endpoint:** `GET /api/logs/recent`

## `hassette execution`

Log entries for a specific execution, identified by its UUID.

```bash
hassette execution a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

The execution UUID appears in the Execution ID column of `hassette listener <id>` and `hassette job <id>` output. [Workflows](workflows.md) covers the full drill-down pattern.

The table shows timestamp, level, function name, line number, and message for each log entry captured during that execution.

### Flags

| Flag | Description |
|---|---|
| `--limit <n>` | Maximum number of log entries to return. |
| `--json` | Outputs as JSON. |

**API endpoint:** `GET /api/executions/{execution_id}`

## `hassette event`

Recent Home Assistant events received by the WebSocket connection.

```console
$ hassette event --limit 5
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ Event Type     ┃ Entity ┃ When    ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│ service_status │        │ 35s ago │
│ service_status │        │ 35s ago │
│ service_status │        │ 35s ago │
│ service_status │        │ 35s ago │
│ service_status │        │ 35s ago │
└────────────────┴────────┴─────────┘
```

The Entity column is populated for `state_changed` events. Other event types leave it blank.

### Flags

| Flag | Description |
|---|---|
| `--limit <n>` | Maximum number of events to return. |
| `--json` | Outputs as JSON. |

**API endpoint:** `GET /api/events/recent`

## `hassette dashboard`

Per-app health status, invocation counts, error counts, average duration, and last activity. Mirrors the dashboard grid in the web UI.

```console
$ hassette dashboard
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Invoc ┃ Errs ┃ Avg Dur ┃ Last Active ┃ Health    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ config_app      │ running │ 0     │ 0    │ 0ms     │             │ excellent │
│ trivial_app     │ running │ 0     │ 0    │ 0ms     │             │ excellent │
│ bus_handler_app │ running │ 0     │ 0    │ 0ms     │             │ excellent │
└─────────────────┴─────────┴───────┴──────┴─────────┴─────────────┴───────────┘
```

**API endpoint:** `GET /api/telemetry/dashboard/app-grid`

## `hassette config`

The resolved Hassette configuration, as loaded from all sources (TOML, env vars, defaults). Renders as a key-value panel showing the full configuration tree, including nested sections like `web_api`, `apps`, and `lifecycle`.

```bash
hassette config
```

**API endpoint:** `GET /api/config`

## `hassette telemetry`

Telemetry database statistics: record counts, drop rates, and error handler failures.

```console
$ hassette telemetry
╭──── TelemetryStatusResponse ────╮
│  degraded                False  │
│  dropped_overflow        0      │
│  dropped_exhausted       0      │
│  dropped_shutdown        0      │
│  error_handler_failures  0      │
╰─────────────────────────────────╯
```

All-zero counters indicate the telemetry pipeline is healthy and no records have been lost.

**API endpoint:** `GET /api/telemetry/status`

## Shared Flags

These flags appear across multiple commands.

| Flag | Format | Commands | Description |
|---|---|---|---|
| `--app <key>` | string | `listener`, `job`, `log` | Filters results to a specific app key. |
| `--instance <n>` | int or string | `listener`, `job`, `app health`, `app activity` | Filters to a specific app instance. Requires `--app` or a positional `<key>` argument. |
| `--since <duration>` | relative or absolute | `listener`, `job`, `log`, `app health`, `app activity` | Time window for filtering. See [`--since` format](#--since-format). |
| `--limit <n>` | integer | `log`, `event`, `execution`, `app activity`, per-ID commands | Maximum number of records to return. |
| `--source-tier <tier>` | `app`, `framework`, or `all` | `listener`, `job`, `log`, `app health` | Filters by source tier. `app` returns user automation records. `framework` returns internal Hassette component records. `all` returns both. |
| `--json` | n/a | all commands | Outputs as JSON. See [Output Modes](configuration.md#output-modes). |

### Global flags

These flags apply to every command and are placed before the subcommand name.

| Flag | Aliases | Description |
|---|---|---|
| `--config-file` | `-c` | Path to the TOML configuration file. |
| `--env-file` | `-e`, `--env` | Path to the `.env` file. |
| `--json` | n/a | Outputs results as JSON. |
| `--debug` | n/a | Shows the full HTTP response on CLI errors. |

### --since format

`--since` accepts relative durations and absolute timestamps.

**Relative durations** use a number followed by a unit suffix:

| Suffix | Unit | Example |
|---|---|---|
| `s` | seconds | `30s` |
| `m` | minutes | `15m` |
| `h` | hours | `1h` |
| `d` | days | `7d` |
| `w` | weeks | `2w` |

Compound durations such as `1h30m` are not supported. Month and year units are not supported.

**Absolute timestamps** use ISO 8601 format:

| Format | Example | Interpretation |
|---|---|---|
| Date only | `2026-05-22` | Midnight in local time. |
| Date and time (naive) | `2026-05-22T14:00:00` | Local time. |
| Date and time (UTC) | `2026-05-22T18:00:00Z` | UTC. |
| Date and time (offset) | `2026-05-22T14:00:00-04:00` | Explicit offset. |

Invalid values cause a non-zero exit with an error listing accepted formats.

### `--instance` resolution

`--instance` requires `--app` (or a positional `<key>` argument on `app health` and `app activity`). It accepts:

- **Integer index**, passed directly to the API as `instance_index`. Most apps have a single instance at index `0`.
- **Instance name**, resolved to an index by fetching the app manifest. If no instance matches the name, the CLI exits non-zero and lists available instance names.

`--instance` without an app context exits non-zero with a usage error.
