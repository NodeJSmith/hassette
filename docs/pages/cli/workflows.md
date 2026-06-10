# Workflows

CLI commands chain together. Start broad, narrow to the problem, then read the full trace.

Three terms appear throughout: a **handler** is a Python function in your app that runs in response to a Home Assistant event (e.g., a motion sensor firing). A **listener** is the registered subscription that connects a handler to an event. An **invocation** is a single execution of that handler — one time it ran. The CLI calls each invocation an *execution* and gives it an execution ID; the two words name the same thing.

The examples pipe `--json` output to [`jq`](https://jqlang.org), a command-line JSON filter — install it with `apt install jq` or `brew install jq`, or skip those one-liners.

## Quick Health Checks

Four one-liners for fast answers:

**Is Hassette running?**

```bash
hassette status
```

The output shows `status: ok`, `degraded`, or `starting`, plus uptime and connected app count.

**Are all apps healthy?**

```bash
hassette dashboard
```

Scan the `Health` and `Errs` columns. Any app showing `warning` or non-zero errors needs attention.

**Any listeners with errors?**

```bash
hassette listener --json | jq '.[] | select(.failed > 0) | {id: .listener_id, handler: .handler_method, failed}'
```

Returns only the listeners that have failures, with their IDs and handler names.

**What happened recently?**

```bash
hassette log --since 1h --limit 50
```

Shows the last 50 log entries from the past hour across all apps.

## Drill-Down: From Status to Root Cause

Start at the system level. Each step narrows the scope until you have a single execution to inspect.

**1. Check system health**

```bash
hassette status
```

If `status` is `ok`, the framework is healthy. If it's `degraded`, something is wrong at the service level. Move to the next step either way to see which app is affected.

**2. Find the problem app**

```bash
hassette dashboard
```

The dashboard shows every app's invocation count, error count, average duration, and health status. Look for apps with a non-zero `Errs` value or a health status other than `excellent`:

```
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Invoc ┃ Errs ┃ Avg Dur ┃ Last Active ┃ Health    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ motion_lights   │ running │ 142   │ 0    │ 12ms    │ 2m ago      │ excellent │
│ garage_door     │ running │ 34    │ 3    │ 45ms    │ 14m ago     │ warning   │
│ thermostat      │ running │ 8     │ 0    │ 230ms   │ 1h ago      │ excellent │
└─────────────────┴─────────┴───────┴──────┴─────────┴─────────────┴───────────┘
```

`garage_door` has 3 errors. Drill into it next.

**3. Inspect the app's listeners**

```bash
hassette listener --app garage_door
```

This lists every listener registered by `garage_door` with per-listener invocation counts and failure rates. Find the row with a non-zero `Fail` value and note its `ID`.

**4. View invocation history**

```bash
hassette listener 42 --since 1h
```

Replace `42` with the listener ID from step 3. Each row shows status, duration, error info, and execution ID. Find the failed row and copy the value in its `Execution ID` column.

**5. Read the execution logs**

```bash
hassette execution a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

This shows every log entry emitted during that specific handler invocation. The `Function` and `Line` columns tell you exactly where in your code each message came from.

## Monitoring a Specific App

Use `--app` to scope any command to one app:

```bash
# Health metrics
hassette app health motion_lights --since 6h

# Listener stats
hassette listener --app motion_lights

# Recent invocations across all listeners
hassette app activity motion_lights --since 1h

# Scheduled jobs (functions registered with the scheduler)
hassette job --app motion_lights

# Recent log output
hassette log --app motion_lights --limit 30
```

### Multi-Instance Apps

When an app runs as multiple instances (one per room, for example — declared in `hassette.toml`, see [App Configuration](../core-concepts/apps/configuration.md)), add `--instance` to filter further. Use the instance name or its zero-based index:

```bash
# By name
hassette listener --app remote_control --instance office

# By index
hassette listener --app remote_control --instance 0
```

`--instance` requires `--app`. The `log` command does not support `--instance`.

## Comparing Time Windows

`--since` accepts relative durations (`30s`, `30m`, `1h`, `7d`, `2w`) and absolute timestamps (`2026-05-22`, `2026-05-22T14:00:00`). Use different windows to separate a spike from a trend:

```bash
# Is the current error rate elevated?
hassette app health motion_lights --since 1h

# What's the baseline?
hassette app health motion_lights --since 24h

# Any longer trends?
hassette app health motion_lights --since 7d
```

If the 1h error rate is much higher than the 24h rate, the problem started recently. If the rates match, it's been happening all day.

Listener invocation history works the same way:

```bash
# Failures in the last hour
hassette listener 42 --since 1h

# Failures over the past day
hassette listener 42 --since 24h
```

## Scripting with `--json`

Every command accepts `--json` and writes structured JSON to stdout. Pipe it to `jq` for filtering and scripting — the JSON contains every field the server returns; see [Commands](commands.md) for each command's output. The scripts below are bash; adapt the pattern to whatever runs your monitoring.

**Extract failing apps:**

```bash
hassette dashboard --json | jq '.[] | select(.health_status != "excellent") | .app_key'
```

**Count total handler failures across all listeners:**

```bash
hassette listener --json | jq '[.[].failed] | add'
```

**Health check script** (exits non-zero if the system is not `ok`):

```bash
#!/usr/bin/env bash
status=$(hassette status --json | jq -r '.status')
if [ "$status" != "ok" ]; then
  echo "Hassette is $status" >&2
  exit 1
fi
```

**Alert on error rate** (exits non-zero if any app has more than 5 failures):

```bash
#!/usr/bin/env bash
failures=$(hassette listener --json | jq '[.[].failed] | add // 0')
if [ "$failures" -gt 5 ]; then
  echo "Total handler failures: $failures" >&2
  exit 1
fi
```

See [Commands](commands.md) for the full flag reference for each command, and [Configuration](configuration.md) for connection settings. The [web UI](../web-ui/index.md) shows the same data if you prefer a browser.
