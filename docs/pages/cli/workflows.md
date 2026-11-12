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

The output shows `status: ok`, `degraded`, or `starting`, plus uptime and the number of tracked app instances.

**Are all apps healthy?**

```bash
hassette dashboard
```

Scan the `Health` and `Errors` columns. Any app showing `warning` or non-zero errors needs attention.

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

If `status` is `ok`, the framework is healthy. If it's `degraded`, the Home Assistant connection has dropped or apps haven't been released to start yet; `websocket_connected` and `bootstrap_released` tell you which. Move to the next step either way to see which app is affected.

**2. Find the problem app**

```bash
hassette dashboard
```

The dashboard shows every app's invocation count, error count, average handler and job duration, and health status. A blank average means nothing of that kind ran, for example an app with no scheduled jobs. Look for apps with a non-zero `Errors` value or a health status other than `excellent`:

```
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Invocations ┃ Errors ┃ Handler Avg ┃ Job Avg ┃ Last Active ┃ Health    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ motion_lights   │ running │ 142         │ 0      │ 12ms        │         │ 2m ago      │ excellent │
│ garage_door     │ running │ 34          │ 3      │ 45ms        │ 1.2s    │ 14m ago     │ warning   │
│ thermostat      │ running │ 8           │ 0      │ 230ms       │ 85ms    │ 1h ago      │ excellent │
└─────────────────┴─────────┴─────────────┴────────┴─────────────┴─────────┴─────────────┴───────────┘
```

`garage_door` has 3 errors. Drill into it next.

**3. Inspect the app's listeners**

```bash
hassette listener --app garage_door
```

This lists every listener registered by `garage_door` with per-listener invocation, success, and failure counts. Find the row with a non-zero `Fail` value and note its `ID`.

**4. View invocation history**

```bash
hassette listener 42 --since 1h
```

Replace `42` with the listener ID from step 3. Each row shows status, duration, error info, and execution ID. The table shortens execution IDs in a terminal, so get the full ID from JSON:

```bash
hassette listener 42 --since 1h --json | jq -r '.[] | select(.status != "success") | .execution_id'
```

**5. Read the execution logs**

```bash
hassette execution a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

The summary at the top shows what triggered the run: the entity and the change (`off → on`) that fired the handler, which tells a wildcard or multi-entity listener's runs apart. Below it are the log entries from that invocation: your app's lines plus framework errors. Pass `--author all` to see every line. The `Function` and `Line` columns tell you exactly where in your code each message came from.

## Why Didn't My Listener Run?

A listener that shows 0 runs either never saw a matching event or saw events and dropped them. `--misses` tells the two apart.

**1. Find the listener's ID**

```bash
hassette listener --app garage_door
```

**2. List what it dropped**

```bash
hassette listener 42 --misses --since 1h
```

Each row counts the events one reason dropped in one hour, with the last such event's entity and values. A `filter` row names the filter that rejected them: a row for `→ open` showing `closed → opening` means the door reported `opening`, not `open`, so `changed_to="open"` never matched. A `throttled`, `debounce_superseded` or `once_spent` row is usually the `throttle=`, `debounce=` or `once=` setting working as configured, even with a large count. A `busy` or `queue_full` row means events arrived while the handler was still running, which points at the `mode=` setting. A `backpressure` row means the whole bus was saturated. Counts are written every 30 seconds, so a drop that just happened can take that long to appear.

**3. If the table is empty**

Nothing reached the listener's filters. Only events for the listener's own entity count, and the default change check records nothing either: `on_state_change` drops an attribute-only update without recording it (pass `changed=True` to count those). Check the entity ID and topic in step 1, then check that Home Assistant is sending the event at all, for example in its Developer Tools event listener.

## Monitoring a Specific App

Scope a command to one app with `--app` (`listener`, `job`, `log`, `blocking`) or with the app key argument (`app health`, `app activity`):

```bash
# Health metrics
hassette app health motion_lights --since 6h

# Listener stats
hassette listener --app motion_lights

# Recent handler and job runs
hassette app activity motion_lights --since 1h

# Scheduled jobs (functions registered with the scheduler)
hassette job --app motion_lights

# Recent log output
hassette log --app motion_lights --limit 30
```

### Multi-Instance Apps

When an app runs as multiple instances (one per room, for example — declared in `hassette.toml`, see [App Configuration](../core-concepts/apps/configuration.md)), add `--instance` with the instance name to filter further:

```bash
hassette listener --app remote_control --instance office
```

`--instance` needs an app: `--app` on `listener` and `job`, or the app key on `app health` and `app activity`. The `log` command does not support `--instance`.

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

Every command except `hassette run` accepts `--json` and writes structured JSON to stdout. Pipe it to `jq` for filtering and scripting — the JSON contains every field the server returns; see [Commands](commands.md) for each command's output. The scripts below are bash; adapt the pattern to whatever runs your monitoring.

**Extract failing apps** (each row's `app` and `activity` keys are described under [`hassette app`](commands.md#hassette-app)):

```bash
hassette dashboard --json | jq '.[] | select(.activity.stats.health.health_status != "excellent") | .app.app_key'
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

**Alert on failures** (exits non-zero if handler failures across all listeners total more than 5):

```bash
#!/usr/bin/env bash
failures=$(hassette listener --json | jq '[.[].failed] | add // 0')
if [ "$failures" -gt 5 ]; then
  echo "Total handler failures: $failures" >&2
  exit 1
fi
```

See [Commands](commands.md) for the full flag reference for each command, and [Configuration](configuration.md) for connection settings. The [web UI](../web-ui/index.md) shows the same data if you prefer a browser.
