# Command Reference

Every command supports `--json` for structured output. See [Configuration & Scripting](configuration.md#output-modes) for details on output modes.

## `hassette status`

System health summary: status, WebSocket connection, uptime, app count, entity count, and version.

```
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

**API endpoint:** `GET /api/health`

---

## `hassette app`

List all loaded apps with their key, display name, status, instance count, and recent invocation counts.

```
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
| `hassette app` | List all apps | `GET /api/apps/manifests` |
| `hassette app health <key>` | Health metrics for one app | `GET /api/telemetry/app/{key}/health` |
| `hassette app activity <key>` | Recent activity feed | `GET /api/telemetry/app/{key}/activity` |
| `hassette app config <key>` | Resolved configuration | `GET /api/apps/{key}/config` |
| `hassette app source <key>` | Source file location | `GET /api/apps/{key}/source` |

### `hassette app health <key>`

Health metrics for a specific app: error rate, average handler/job duration, and overall health status.

```
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

Filter by instance or time window:

```bash
hassette app health my-app --instance office --since 6h
```

### `hassette app activity <key>`

Recent handler invocations and job executions for an app, shown as a unified activity feed.

```bash
hassette app activity my-app --since 30m --limit 20
```

The activity table includes columns for kind (handler or job), status, handler name, duration, timestamp, and error type.

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
| `--instance` | `health`, `activity` | Filter to a specific app instance (index or name) |
| `--since` | `health`, `activity` | Time window for metrics (e.g. `1h`, `7d`) |
| `--limit` | `activity` | Maximum records to return |
| `--json` | all | Output as JSON |

---

## `hassette listener`

List all registered event bus listeners, or view invocation history for a specific listener.

```
$ hassette listener
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━┳━━━━━┳━━━━━━┓
┃ ID ┃ Topic                                     ┃ Handler           ┃ Kind   ┃ Total ┃ OK ┃ Fail ┃ Avg ┃ Last ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━╇━━━━━╇━━━━━━┩
│ 10 │ hass.event.state_changed.light.kitchen_…  │ BusHandlerApp._…  │ state  │ 0     │ 0  │ 0    │ 0ms │      │
│    │                                           │                   │ change │       │    │      │     │      │
└────┴───────────────────────────────────────────┴───────────────────┴────────┴───────┴────┴──────┴─────┴──────┘
```

The table shows each listener's ID, the event topic it subscribes to, the handler method, event kind, invocation counts (total, successful, failed), average duration, and when it was last invoked.

### Viewing invocation history

Pass a listener ID to see its invocation history:

```bash
hassette listener 10 --since 1h --limit 20
```

The invocation table shows status, duration, error details, timestamp, and execution ID for each invocation.

### Flags

| Flag | Description |
|---|---|
| `--app <key>` | Filter to listeners belonging to this app |
| `--instance <n>` | Filter to a specific app instance (requires `--app`) |
| `--since <duration>` | Time window for invocation counts and history |
| `--limit <n>` | Maximum invocation records (when viewing a specific listener) |
| `--source-tier <tier>` | Filter by `app` (user automations) or `framework` (internal). Defaults to `app` |
| `--json` | Output as JSON |

**API endpoints:**

- `hassette listener` → `GET /api/bus/listeners`
- `hassette listener --app <key>` → `GET /api/telemetry/app/{key}/listeners`
- `hassette listener <id>` → `GET /api/telemetry/handler/{id}/invocations`

---

## `hassette job`

List all scheduled jobs, or view execution history for a specific job.

```
$ hassette job
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━┳━━━━━┳━━━━━━━━━━┓
┃ ID ┃ Handler              ┃ Trigger  ┃ Schedule ┃ Total ┃ OK ┃ Fail ┃ Avg ┃ Next Run ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━╇━━━━━╇━━━━━━━━━━┩
│ 1  │ StateProxy.sync_all  │ interval │ every    │ 0     │ 0  │ 0    │ 0ms │ soon     │
└────┴──────────────────────┴──────────┴──────────┴───────┴────┴──────┴─────┴──────────┘
```

The table shows the job ID, handler method, trigger type, schedule label, execution counts, average duration, and when the job will next run.

### Viewing execution history

Pass a job ID to see its execution history:

```bash
hassette job 1 --limit 20
```

The execution table shows status, duration, error details, timestamp, and execution ID.

### Flags

| Flag | Description |
|---|---|
| `--app <key>` | Filter to jobs belonging to this app |
| `--instance <n>` | Filter to a specific app instance (requires `--app`) |
| `--since <duration>` | Time window for execution history |
| `--limit <n>` | Maximum execution records (when viewing a specific job) |
| `--source-tier <tier>` | Filter by `app` or `framework`. Server defaults to `all` for global queries, `app` for per-app queries |
| `--json` | Output as JSON |

**API endpoints:**

- `hassette job` → `GET /api/scheduler/jobs`
- `hassette job --app <key>` → `GET /api/telemetry/app/{key}/jobs`
- `hassette job <id>` → `GET /api/telemetry/job/{id}/executions`

---

## `hassette log`

Recent log entries from the in-memory log buffer.

```
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

### Flags

| Flag | Description |
|---|---|
| `--app <key>` | Filter to log entries from this app |
| `--since <duration>` | Time window filter (e.g. `1h`, `30m`) |
| `--limit <n>` | Maximum number of entries to return |
| `--source-tier <tier>` | Filter by `app` or `framework` |
| `--json` | Output as JSON |

**API endpoint:** `GET /api/logs/recent`

!!! note "Buffer size"
    Logs are kept in a ring buffer (default: 2000 entries). Entries older than the buffer window are not available. For persistent log storage, configure your process manager to capture stdout.

---

## `hassette execution`

Log entries for a specific execution, identified by its UUID. Use this to see exactly what happened during a single handler invocation or job execution.

```bash
hassette execution a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

You'll typically get the execution UUID from the `listener <id>` or `job <id>` invocation/execution tables (the "Execution ID" column), then drill into it here. See [Workflows](workflows.md) for the full drill-down pattern.

### Flags

| Flag | Description |
|---|---|
| `--limit <n>` | Maximum number of log entries to return |
| `--json` | Output as JSON |

**API endpoint:** `GET /api/executions/{execution_id}`

---

## `hassette event`

Recent Home Assistant events received by the WebSocket connection.

```
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

### Flags

| Flag | Description |
|---|---|
| `--limit <n>` | Maximum number of events to return |
| `--json` | Output as JSON |

**API endpoint:** `GET /api/events/recent`

!!! note
    Event data is from the in-memory buffer and reflects the raw HA event stream. The `Entity` column is populated for `state_changed` events; other event types may leave it blank.

---

## `hassette dashboard`

App grid summary as shown on the web UI dashboard: per-app health status, invocation counts, and error rates.

```
$ hassette dashboard
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Invoc ┃ Errs ┃ Avg Dur ┃ Last Active ┃ Health    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ config_app      │ running │ 0     │ 0    │ 0ms     │             │ excellent │
│ trivial_app     │ running │ 0     │ 0    │ 0ms     │             │ excellent │
│ bus_handler_app │ running │ 0     │ 0    │ 0ms     │             │ excellent │
└─────────────────┴─────────┴───────┴──────┴─────────┴─────────────┴───────────┘
```

This gives a quick at-a-glance health overview of all apps — equivalent to the dashboard grid in the web UI.

**API endpoint:** `GET /api/telemetry/dashboard/app-grid`

---

## `hassette config`

The resolved Hassette configuration as loaded from all sources (TOML, env vars, defaults).

```bash
hassette config
```

Renders as a key-value panel showing the full configuration tree, including nested sections like `web_api`, `apps`, `lifecycle`, etc.

**API endpoint:** `GET /api/config`

---

## `hassette service`

Home Assistant services available on the connected instance.

```bash
hassette service
```

**API endpoint:** `GET /api/services`

!!! note
    Service data is proxied directly from Home Assistant and has a variable schema. The output mirrors the HA API response and is not normalized. Use `--json` and `jq` to extract specific services.

---

## `hassette telemetry`

Telemetry database statistics: record counts, drop rates, and error handler failures.

```
$ hassette telemetry
╭──── TelemetryStatusResponse ────╮
│  degraded                False  │
│  dropped_overflow        0      │
│  dropped_exhausted       0      │
│  dropped_no_session      0      │
│  dropped_shutdown        0      │
│  error_handler_failures  0      │
╰─────────────────────────────────╯
```

All counters at zero means the telemetry pipeline is healthy and no records have been lost.

**API endpoint:** `GET /api/telemetry/status`

---

## Shared Flags

These flags are supported across multiple commands:

| Flag | Format | Commands | Description |
|---|---|---|---|
| `--app <key>` | string | `listener`, `job`, `log` | Filter results to a specific app key |
| `--instance <n>` | int or string | `listener`, `job`, `app health`, `app activity` | Filter to a specific app instance. Accepts an integer index (`0`, `1`) or an instance name (`office`). Requires `--app`. |
| `--since <duration>` | relative or absolute | `listener`, `job`, `log`, `event`, `app health`, `app activity` | Time window for filtering. See [formats below](#-since-format). |
| `--limit <n>` | integer | `log`, `event`, `execution`, `app activity`, and per-ID commands | Maximum number of records to return |
| `--source-tier <tier>` | `app` or `framework` | `listener`, `job`, `log`, `app health` | Filter by source tier. `app` returns user automation records; `framework` returns internal Hassette component records. |
| `--json` | — | all commands | Output as JSON. See [Output Modes](configuration.md#output-modes). |

### `--since` format

`--since` accepts two formats:

**Relative durations** — a number followed by a unit suffix:

| Suffix | Unit | Example |
|---|---|---|
| `s` | seconds | `30s` |
| `m` | minutes | `15m` |
| `h` | hours | `1h` |
| `d` | days | `7d` |
| `w` | weeks | `2w` |

Compound durations (`1h30m`) are not supported.

**Absolute timestamps** — ISO 8601 format, interpreted as local time:

- `2026-05-22T14:00:00` — date and time
- `2026-05-22` — date only (midnight local time)

Invalid formats exit non-zero with an error listing accepted formats.

### `--instance` resolution

`--instance` requires `--app`. It accepts:

- **Integer index** — passed directly to the API as `instance_index`. Most apps have a single instance at index `0`.
- **Instance name** — resolved to an index by fetching the app manifest. If no instance matches, the CLI exits non-zero and lists the available instance names.

`--instance` without `--app` exits non-zero with a usage error.
