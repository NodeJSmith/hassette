# Command Reference

All commands support `--json` for structured output and `--debug` for verbose error details. `hassette --version` (or `-v`) prints the installed version. [Configuration & Scripting](configuration.md#output-modes) covers output modes in detail.

Every command except `run` queries a running instance — start the server with `hassette run` first. Each command wraps a REST endpoint, noted per command for scripting and direct HTTP access.

Several commands take `--app <key>`. The app key is the `[hassette.apps.<key>]` section name from `hassette.toml`, and an instance is one running copy of an app class — [`hassette app`](#hassette-app) lists both.

## `hassette run`

Starts the Hassette framework server, connects to Home Assistant, loads apps, and starts the web API. The process runs in the foreground — keep the terminal open, or use a process manager like systemd or Docker. Press `Ctrl+C` to stop.

```bash
hassette run
```

### Flags

| Flag              | Description                                                            |
| ----------------- | ----------------------------------------------------------------------- |
| `--token`, `-t`   | Home Assistant access token. Overrides config file and environment.   |
| `--ha-url`, `-u`  | URL of the Home Assistant instance to connect to.                     |
| `--ha-verify-ssl` | Whether to verify SSL certificates for the Home Assistant connection. |
| `--dev-mode`      | Enables developer mode.                                               |
| `--app`, `-a`     | Run only this app key, excluding all others. Repeatable.              |
| `--check`         | Validates the configuration, prints the resolved locations, and exits without starting. See [Checking the Resolved Locations](../core-concepts/configuration/index.md#check-config). |

All flags are optional. Values resolve from `hassette.toml` (see [Configuration](../core-concepts/configuration/index.md)) and environment variables when not provided on the command line.

`--app` isolates one app during development without editing `hassette.toml` or the app's source. Every other enabled app is excluded and reports status `blocked` in [`hassette app`](#hassette-app) — that is the expected result of the flag, not a failure. Disabled apps remain `disabled`. `app start` and `app reload` reject a blocked app outright rather than silently doing nothing — the isolation holds even if you target it directly. Repeat the flag or pass a comma-separated list to keep more than one app running:

```bash
hassette run --app kitchen_lights --app porch_motion
hassette run --app kitchen_lights,porch_motion
```

See [Restricting Which Apps Run](../core-concepts/apps/index.md#restricting-which-apps-run) for details.

`run` exits with one of these codes:

| Code | Meaning | Examples and what to do |
|---|---|---|
| 78 | The configuration must be edited before a restart can succeed. | Invalid values, unknown keys, invalid app keys, or `config_dir` set in a file (Hassette needs `config_dir` to find the files, so a value inside them is read too late). Also an app failing its precheck, the import-and-validate pass over every app module before startup (`AppPrecheckFailedError`). Fix the config or app code, then restart. |
| 1 | A runtime failure. | A fatal error such as a bad token or unreachable Home Assistant (see [Troubleshooting](../troubleshooting.md)), the web API port already taken (`Port 8126 is already in use — is another hassette instance running?`), or an unexpected exception. |

Under systemd, `RestartPreventExitStatus=78` keeps a config error from restart-looping. See [Exit Codes](../core-concepts/configuration/index.md#exit-codes).

## `hassette status`

Reports system health: connection state, uptime, app instance count, entity count, and version. The instance count covers every tracked instance (starting, running, or failed), so stopped and disabled apps, which have no instance, are left out. [`hassette app`](#hassette-app) lists every configured app.

```console
$ hassette status
╭────────────────────── System Status ─────────────────────────╮
│  status                  ok                                  │
│  websocket_connected     true                                │
│  bootstrap_released      true                                │
│  uptime_seconds          16.57                               │
│  entity_count            103                                 │
│  app_count               3 tracked instances                 │
│  services                EventStreamService, BusService, ... │
│  version                 0.32.0                              │
│  boot_issues             []                                  │
│  log_queue_drops         0                                   │
│  db_write_queue_drops    0                                   │
│  log_persistence_active  true                                │
╰──────────────────────────────────────────────────────────────╯
```

`boot_issues` lists apps that failed to initialize. An empty list means all apps started cleanly. When an app appears here, check `hassette log --app <key>` for the error.

`db_write_queue_drops` counts records that persistence could not hand off to the database.
The queue was full, or the database was not accepting writes.
Read this value with `log_persistence_active`; the counter changes only while persistence runs.

- `log_persistence_active: true` with `db_write_queue_drops: 0` — healthy. Every log record is reaching the database.
- `log_persistence_active: true` with a non-zero count — persistence is running but shedding records under load. Check the console logs for `DB write queue full`.
- `log_persistence_active: false` — persistence is not running at all. Nothing is being written and the drop count is frozen, so a `0` here says nothing about how many records were lost. This happens when the persistence handler failed to start (check the console logs for `Failed to create persistence handler`) or when the instance is shutting down.

**API endpoint:** `GET /api/health`

## `hassette app`

Lists all loaded apps with key, status, display name, instance count, handler invocations over the last hour, enabled state, autostart setting, and source file. The app key is the `[hassette.apps.<key>]` section name from `hassette.toml`, and it is the identifier every `--app` flag takes. An instance is one running copy of an app class; most apps run a single instance at index 0, but the same class can run multiple times with different configs.

```console
$ hassette app
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Display     ┃ Instances ┃ Invocations/1h ┃ Enabled ┃ Autostart ┃ File              ┃
┃                 ┃         ┃ Name        ┃           ┃                ┃         ┃           ┃                   ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ config_app      │ running │ ConfigApp   │ 1         │ 0              │ True    │ True      │ config_app.py     │
│ trivial_app     │ running │ TrivialApp  │ 1         │ 0              │ True    │ True      │ trivial_app.py    │
│ bus_handler_app │ running │ BusHandler… │ 1         │ 0              │ True    │ True      │ bus_handler_app.py│
└─────────────────┴─────────┴─────────────┴───────────┴────────────────┴─────────┴───────────┴───────────────────┘
```

`--json` prints one object per app with two keys: `app` (the app's identity, status and instances) and `activity` (what it did over the last hour). `activity` has four parts:

- `stats`: run and error counts, plus the health rating.
- `activity_buckets`: run and error counts per time slice, as drawn in the web UI's sparkline.
- `last_error`: the most recent error, if any.
- `blocking_event_count`: how many times the app's code [blocked the event loop](#hassette-blocking).

A part is `null` when the server couldn't compute it. The table shows that as a blank cell rather than `0`, and a one-line warning on stderr names the missing parts.

### Subcommands

| Subcommand                    | Description                 | API endpoint                                    |
| ----------------------------- | --------------------------- | ----------------------------------------------- |
| `hassette app`                | Lists all apps.             | `GET /api/telemetry/app-grid` (last hour)       |
| `hassette app health <key>`   | Health metrics for one app. | `GET /api/telemetry/app/{key}/health`           |
| `hassette app activity <key>` | Recent activity feed.       | `GET /api/telemetry/app/{key}/activity`         |
| `hassette app config <key>`   | Resolved configuration.     | `GET /api/apps/{key}/config`                    |
| `hassette app source <key>`   | Source file contents.       | `GET /api/apps/{key}/source`                    |
| `hassette app start <key>`    | Starts an app or instance.  | `POST /api/apps/{key}/start`                    |
| `hassette app stop <key>`     | Stops an app or instance.   | `POST /api/apps/{key}/stop`                     |
| `hassette app reload <key>`   | Reloads an app or instance. | `POST /api/apps/{key}/reload`                   |

The CLI routes `start`/`stop`/`reload` with `--instance` to a different endpoint: `POST /api/apps/{key}/instances/{index}/{start,stop,reload}` instead of the app-level path shown above.

### `hassette app start <key>`

Starts a stopped app, or a specific instance with `--instance`.

```bash
hassette app start my-app
hassette app start my-app --instance office
```

### `hassette app stop <key>`

Stops a running app, or a specific instance with `--instance`. Prompts for confirmation unless `--yes` is passed.

```bash
hassette app stop my-app
hassette app stop my-app --yes
```

### `hassette app reload <key>`

Reloads an app from disk, or a specific instance with `--instance`. Prompts for confirmation unless `--yes` is passed.

```bash
hassette app reload my-app --yes
hassette app reload my-app --instance office --yes
```

!!! warning
    `stop` and `reload` prompt for confirmation by default. In non-interactive
    contexts (scripts, cron, CI) pass `--yes`, or the command exits 0 without
    performing the action.

### `hassette app health <key>`

Reports health metrics for an app: error rate, overall health status, last activity, and average handler and job duration. An average shows `—` when nothing of that kind ran in the window. The job average leaves out skipped runs, so it also shows `—` when every job run was skipped.

```console
$ hassette app health bus_handler_app
╭───────────── App Health ─────────────╮
│  error_rate               0.0        │
│  error_rate_class         good       │
│  health_status            excellent  │
│  last_activity_ts         —          │
│  handler_avg_duration_ms  —          │
│  job_avg_duration_ms      —          │
╰──────────────────────────────────────╯
```

Health counts every run in the window, including runs of handlers and jobs removed since. `hassette dashboard` uses the same rule across all of an app's instances, so the two agree whenever only one instance ran in the window.

??? note "Runs that drop out of health"
    Health reads stored executions. Retention deletes old ones, and a restart deletes the previous session's `once=True` listeners along with their executions, so those runs stop counting.

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

The source of an app: its filename, line count, and full file contents.

```bash
hassette app source my-app
```

### Flags

| Flag            | Applies to                        | Description                                              |
| --------------- | ---------------------------------- | -------------------------------------------------------- |
| `--instance`    | `health`, `activity`, `start`, `stop`, `reload` | Filters to (read commands) or targets (action commands) a specific app instance (index or name). |
| `--since`       | `health`, `activity`               | Time window for metrics. See [formats](#--since-format). |
| `--source-tier` | `health`                           | Filters by source tier — `app` is your code, `framework` is Hassette internals. See [Shared Flags](#shared-flags). |
| `--limit`       | `activity`                         | Maximum records to return.                               |
| `--yes`         | `stop`, `reload`                   | Skip confirmation prompt.                                 |
| `--json`        | all                                 | Outputs as JSON.                                         |

## `hassette listener`

Lists all registered event bus listeners, or shows invocation history for a specific listener. A listener is the registered subscription that connects a handler (a function in your app) to an event — see [Bus](../core-concepts/bus/index.md).

```console
$ hassette listener
┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━┳━━━━━┳━━━━━━┓
┃ ID ┃ App              ┃ Target                    ┃ Kind       ┃ Handler              ┃ Total ┃ OK ┃ Fail ┃ Avg ┃ Last ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━╇━━━━━╇━━━━━━┩
│ 10 │ bus_handler_app  │ light.kitchen_main        │ state_cha… │ on_light_change      │ 0     │ 0  │ 0    │ 0ms │      │
└────┴──────────────────┴───────────────────────────┴────────────┴──────────────────────┴───────┴────┴──────┴─────┴──────┘
```

Each row shows the listener ID, app key, target, listener kind, handler, counts, duration, and last invocation time. State and attribute listeners use the entity ID as target; event listeners use the event name.

Passing a listener ID shows its invocation history:

```bash
hassette listener 10 --since 1h --limit 20
```

The invocation table shows status, duration, error type, error message, timestamp, and execution ID for each invocation.

### Flags

| Flag                   | Description                                                    |
| ---------------------- | -------------------------------------------------------------- |
| `--app <key>`          | Filters to listeners belonging to this app.                    |
| `--instance <n>`       | Filters to a specific app instance. Requires `--app`.          |
| `--since <duration>`   | Time window for invocation counts and history.                 |
| `--source-tier <tier>` | Filters by `app`, `framework`, or `all`.                       |
| `--limit <n>`          | Maximum invocation records (when viewing a specific listener). |
| `--json`               | Outputs as JSON.                                               |

**API endpoints:**

- `hassette listener` hits `GET /api/bus/listeners`
- `hassette listener --app <key>` hits `GET /api/telemetry/app/{key}/listeners`
- `hassette listener <id>` hits `GET /api/telemetry/listener/{id}/executions`

## `hassette job`

Lists all scheduled jobs, or shows execution history for a specific job. A job is a function registered with the [Scheduler](../core-concepts/scheduler/index.md) to run at a time or interval.

```console
$ hassette job
┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ ID ┃ App              ┃ Handler              ┃ Trigger  ┃ Status    ┃ Mode    ┃ Total ┃ OK ┃ Fail ┃ Skipped ┃ Avg ┃ Next Run           ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ 1  │ config_app       │ StateProxy.sync_all  │ interval │ Scheduled │ single  │ 0     │ 0  │ 0    │ 0       │ 0ms │ soon               │
└────┴──────────────────┴──────────────────────┴──────────┴───────────┴─────────┴───────┴────┴──────┴─────────┴─────┴────────────────────┘
```

Each row shows the job ID, app key, handler method, trigger type, schedule status (`scheduled`, `waiting`, `completed`, or `manual`), mode, execution counts, average duration, and next run time. `Skipped` counts runs where the job's predicate returned `False` and the handler never ran. Those runs still count toward `Total`, so a job showing `Total 68 / OK 0 / Fail 0 / Skipped 68` is being filtered out entirely rather than failing. The Next Run column shows a relative time when one is scheduled, or status-aware placeholder text otherwise — `Timing unavailable.`, `Waiting for entity time.`, `Schedule completed.`, or `Manual only.` — rather than a blank cell.

Passing a job ID shows its execution history:

```bash
hassette job 1 --limit 20
```

The execution table shows status, duration, error type, error message, timestamp, and execution ID for each run.

### Flags

| Flag                   | Description                                              |
| ---------------------- | -------------------------------------------------------- |
| `--app <key>`          | Filters to jobs belonging to this app.                   |
| `--instance <n>`       | Filters to a specific app instance. Requires `--app`.    |
| `--since <duration>`   | Time window for execution history.                       |
| `--source-tier <tier>` | Filters by `app`, `framework`, or `all`.                 |
| `--limit <n>`          | Maximum execution records (when viewing a specific job). |
| `--json`               | Outputs as JSON.                                         |

**API endpoints:**

- `hassette job` hits `GET /api/scheduler/jobs`
- `hassette job --app <key>` hits `GET /api/telemetry/app/{key}/jobs`
- `hassette job <id>` hits `GET /api/telemetry/job/{id}/executions`

## `hassette log`

Recent log entries from the telemetry database (requires log persistence).

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

| Flag                   | Description                              |
| ---------------------- | ---------------------------------------- |
| `--app <key>`          | Filters to log entries from this app.    |
| `--since <duration>`   | Time window filter.                      |
| `--limit <n>`          | Maximum number of entries to return.     |
| `--source-tier <tier>` | Filters by `app`, `framework`, or `all`. |
| `--json`               | Outputs as JSON.                         |

**API endpoint:** `GET /api/logs/recent`

## `hassette execution`

Log entries for a specific execution — a single run of a handler or job, identified by its UUID. Get the UUID from the `Execution ID` column of `hassette listener <id>` or `hassette job <id>` output.

```bash
hassette execution a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

The execution UUID appears in the Execution ID column of `hassette listener <id>` and `hassette job <id>` output. [Workflows](workflows.md) covers the full drill-down pattern.

The table shows timestamp, level, function name, line number, and message for each log entry captured during that execution.

### Flags

| Flag          | Description                              |
| ------------- | ---------------------------------------- |
| `--limit <n>` | Maximum number of log entries to return. |
| `--json`      | Outputs as JSON.                         |

**API endpoint:** `GET /api/executions/{execution_id}`

## `hassette blocking`

Blocking calls that stalled the event loop, grouped by the line of app code to fix. Without `--app`, it lists findings for every app, then the recent stalls that no app is credited with. Those are split by reason: `displaced` means an app execution was in flight but another task held the loop, and `framework` means no app execution was running. [Blocking-Call Detection](../core-concepts/blocking-io-detection.md#finding-blocking-calls) explains what each column means.

```console
$ hassette blocking --since 7d
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┓
┃ App              ┃ Instances         ┃ Call site                    ┃ Calls into                   ┃ Count ┃ Max   ┃ Last seen ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━┩
│ presence         │ bedroom, office   │ presence.py:44 in refresh    │ requests/api.py get          │ 4     │ 5.0s  │ 30m ago   │
│ car_climate      │ CarClimate.0      │ calendar_service.py:98 in    │ gcsa/_services/events_servi… │ 9     │ 534ms │ 2h ago    │
│                  │                   │ get_calendar_events          │ get_events                   │       │       │           │
│ garage_proximity │ GarageProximity.0 │ call site not captured       │                              │ 1     │ 212ms │ 2d ago    │
│                  │                   │ (on_phone_arrive)            │                              │       │       │           │
└──────────────────┴───────────────────┴──────────────────────────────┴──────────────────────────────┴───────┴───────┴───────────┘

Loop stalls credited to no app: 3 (1 displaced, 2 framework)
┏━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ When    ┃ Reason    ┃ Stall      ┃ App code in stack         ┃
┡━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 30m ago │ displaced │ 5.0s       │ presence.py:44 in refresh │
│ 5h ago  │ framework │ 140ms      │                           │
│ 2d ago  │ framework │ time.sleep │                           │
└─────────┴───────────┴────────────┴───────────────────────────┘
```

With `--app`, only that app's findings are shown, across all its instances unless `--instance` names one. A call site that several instances hit is one row, and the Instances column names them. `--instance` without `--app` exits with a usage error. Counts are exact. When a window holds more call sites than one response returns, a note on stderr says the least recently seen call sites are omitted; narrow `--since` to see them.

The Stall column shows how long the loop was held. A [Tier 2](../core-concepts/blocking-io-detection.md) row records no duration, so it names the intercepted call instead, such as `time.sleep`.

### Flags

| Flag                   | Description                                         |
| ---------------------- | --------------------------------------------------- |
| `--app <key>`          | Shows only this app's findings.                     |
| `--instance <name\|n>` | With `--app`, selects the instance.                 |
| `--since <duration>`   | Time window filter. Without it, covers all retained events. |
| `--json`               | Outputs as JSON. Without `--app`, one document with `findings` and `unattributed` keys. With `--app`, the findings response: a `findings` array and a `truncated` flag. |

**API endpoints:** `GET /api/telemetry/blocking/findings` and `GET /api/telemetry/blocking/unattributed`; with `--app`, `GET /api/telemetry/app/{app_key}/blocking`

## `hassette dashboard`

Per-app health status, invocation counts, error counts, average handler and job duration, and last activity, across all of an app's instances. Mirrors the app grid on the web UI's Apps page, with counts over all retained history. Use it for the long view; `hassette app` covers the last hour, and `hassette app health` breaks down one app. An average is blank when nothing of that kind ran.

```console
$ hassette dashboard
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Invocations ┃ Errors ┃ Handler Avg ┃ Job Avg ┃ Last Active ┃ Health    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ config_app      │ running │ 0           │ 0      │             │         │             │ excellent │
│ trivial_app     │ running │ 0           │ 0      │             │         │             │ excellent │
│ bus_handler_app │ running │ 0           │ 0      │             │         │             │ excellent │
└─────────────────┴─────────┴─────────────┴────────┴─────────────┴─────────┴─────────────┴───────────┘
```

`--json` rows have the same `app` and `activity` keys as [`hassette app`](#hassette-app). If the server couldn't compute an app's counts and health, those cells are blank (never `0` or `excellent`) and a warning on stderr names the missing parts. `activity_buckets` and `last_error` only exist for a time window, so they are always `null` here.

**API endpoint:** `GET /api/telemetry/app-grid`

## `hassette config`

The resolved Hassette configuration, as loaded from all sources (TOML, env vars, defaults). Renders as a key-value panel showing the full configuration tree, including nested sections like `web_api`, `apps`, and `lifecycle`.

```bash
hassette config
```

**API endpoint:** `GET /api/config`

## `hassette telemetry`

Hassette records every handler invocation and job execution to an internal database. This command shows its statistics: record counts, whether any records were dropped under load or shutdown, and error handler failures.

```console
$ hassette telemetry
╭─────── Telemetry Status ────────╮
│  degraded                False  │
│  dropped_overflow        0      │
│  dropped_exhausted       0      │
│  dropped_shutdown        0      │
│  dropped_filtered        0      │
│  error_handler_failures  0      │
╰─────────────────────────────────╯
```

`dropped_filtered` counts routine framework records skipped by sampling, so it grows on a healthy instance. The other counters should stay at zero: a non-zero `dropped_*` value means records were lost, and `error_handler_failures` counts error handlers that raised or timed out.

When the telemetry database is unreachable, the endpoint returns HTTP 503 with `degraded: true`. The command treats that as a valid status — it prints the response and exits 0, so scripts can read the degraded state instead of catching a CLI error.

**API endpoint:** `GET /api/telemetry/status`

## Shared Flags

These flags appear across multiple commands.

| Flag                   | Format                       | Commands                                                     | Description                                                                                                                                 |
| ---------------------- | ---------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `--app <key>`          | string                       | `listener`, `job`, `log`, `blocking`                         | Filters results to a specific app key.                                                                                                      |
| `--instance <n>`       | int or string                | `listener`, `job`, `blocking`, `app health`, `app activity`, `app start`, `app stop`, `app reload` | Filters to (read commands) or targets (action commands) a specific app instance (index or name). Requires `--app` for `listener`/`job`/`blocking`; requires the positional `<key>` for all `app` subcommands.         |
| `--since <duration>`   | relative or absolute         | `listener`, `job`, `log`, `blocking`, `app health`, `app activity` | Time window for filtering. See [`--since` format](#--since-format).                                                                         |
| `--limit <n>`          | integer                      | `log`, `execution`, `app activity`, per-ID commands          | Maximum number of records to return.                                                                                                        |
| `--source-tier <tier>` | `app`, `framework`, or `all` | `listener`, `job`, `log`, `app health`                       | Filters by source tier. `app` returns user automation records. `framework` returns internal Hassette component records. `all` returns both. |
| `--json`               | n/a                          | all commands                                                 | Outputs as JSON. See [Output Modes](configuration.md#output-modes).                                                                         |

### Global flags

These flags apply to every command and are placed before the subcommand name.

| Flag              | Aliases       | Description                                                                                  |
| ----------------- | ------------- | ---------------------------------------------------------------------------------------------- |
| `--config-dir`    | n/a           | Directory to read `hassette.toml` and `.env` from, instead of searching. Also the default home of the apps directory. |
| `--config-file`   | `-c`          | Path to the TOML configuration file, instead of searching.                                    |
| `--env-file`      | `-e`, `--env` | Path to the `.env` file, instead of searching.                                                 |
| `--json`          | n/a           | Outputs results as JSON.                                                                       |
| `--debug`         | n/a           | Shows the full HTTP response on CLI errors.                                                    |
| `--server-url`    | `-s`          | Base URL of a remote Hassette instance to connect to. See [Discovery Order](configuration.md#discovery-order). |
| `--token-file`    | n/a           | Path to a file containing the bearer credential to attach. See [Web API Token](configuration.md#web-api-token). |
| `--no-verify-ssl` | n/a           | Disables TLS certificate verification for the resolved target.                                |

### --since format { #--since-format }

`--since` accepts relative durations and absolute timestamps.

**Relative durations** use a number followed by a unit suffix:

| Suffix | Unit    | Example |
| ------ | ------- | ------- |
| `s`    | seconds | `30s`   |
| `m`    | minutes | `15m`   |
| `h`    | hours   | `1h`    |
| `d`    | days    | `7d`    |
| `w`    | weeks   | `2w`    |

Compound durations such as `1h30m` are not supported — use the closest single unit instead, like `--since 90m`. Month and year units are not supported; use days.

**Absolute timestamps** use ISO 8601 format:

| Format                 | Example                     | Interpretation          |
| ---------------------- | --------------------------- | ----------------------- |
| Date only              | `2026-05-22`                | Midnight in local time. |
| Date and time (naive)  | `2026-05-22T14:00:00`       | Local time.             |
| Date and time (UTC)    | `2026-05-22T18:00:00Z`      | UTC.                    |
| Date and time (offset) | `2026-05-22T14:00:00-04:00` | Explicit offset.        |

Invalid values cause a non-zero exit with an error listing accepted formats.

### `--instance` resolution

`--instance` requires `--app` (or a positional `<key>` argument on `app health`, `app activity`, `app start`, `app stop`, and `app reload`). It accepts:

- **Integer index**, passed directly to the API as `instance_index`. Most apps have a single instance at index `0`.
- **Instance name**, resolved to an index by fetching the app manifest. If no instance matches the name, the CLI exits non-zero and lists available instance names.

`--instance` without an app context exits non-zero with a usage error.
