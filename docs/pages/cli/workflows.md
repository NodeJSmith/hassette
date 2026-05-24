# Workflows

The CLI commands are designed to chain together. Start broad, then drill down to the specific data you need.

## Drill-Down: From Status to Root Cause

The most common workflow starts with a system-level check and progressively narrows:

### 1. Check system health

```bash
hassette status
```

This tells you whether the system is `ok`, `degraded`, or `starting`, and how many apps are loaded. If something is wrong, the next step is to find which app.

### 2. Find the problem app

```bash
hassette dashboard
```

The dashboard shows invocation counts, error counts, and health status for every app at a glance. Look for apps with a non-zero `Errs` column or a health status other than `excellent`:

```
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ App             ┃ Status  ┃ Invoc ┃ Errs ┃ Avg Dur ┃ Last Active ┃ Health    ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ motion_lights   │ running │ 142   │ 0    │ 12ms    │ 2m ago      │ excellent │
│ garage_door     │ running │ 34    │ 3    │ 45ms    │ 14m ago     │ warning   │
│ thermostat      │ running │ 8     │ 0    │ 230ms   │ 1h ago      │ excellent │
└─────────────────┴─────────┴───────┴──────┴─────────┴─────────────┴───────────┘
```

Here `garage_door` has 3 errors. Drill into it.

### 3. Inspect the app's listeners

```bash
hassette listener --app garage_door
```

This shows all listeners registered by the app, with per-listener invocation counts and failure rates. Find the listener with failures.

### 4. View invocation history

```bash
hassette listener 42 --since 1h
```

The invocation table shows the status, duration, error type, and execution ID for each invocation. Find the failed one and grab its execution ID.

### 5. Read the execution logs

```bash
hassette execution a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

This shows every log entry emitted during that specific handler invocation — the complete trace of what happened.

---

## Monitoring a Specific App

When you know which app you care about, use `--app` filters to scope every command:

```bash
# Health summary
hassette app health motion_lights --since 6h

# Its listeners and their stats
hassette listener --app motion_lights --since 1h

# Its scheduled jobs
hassette job --app motion_lights

# Its recent logs
hassette log --app motion_lights --limit 30
```

### Multi-Instance Apps

For apps with multiple instances (e.g., one per room), add `--instance`:

```bash
# Filter to the "office" instance
hassette listener --app remote_control --instance office

# Or by index
hassette listener --app remote_control --instance 0
```

---

## Quick Health Checks

### Is Hassette running?

```bash
hassette status --json | jq -r '.status'
# "ok"
```

### Are all apps healthy?

```bash
hassette dashboard --json | jq '.[] | select(.health_status != "excellent") | .app_key'
```

If this returns nothing, all apps are healthy.

### Any listeners with errors?

```bash
hassette listener --json | jq '.[] | select(.failed > 0) | {id: .listener_id, handler: .handler_method, failed}'
```

### What happened in the last hour?

```bash
hassette log --since 1h --limit 50
```

---

## Comparing Time Windows

Use `--since` to compare different time periods:

```bash
# Last hour — is the current error rate elevated?
hassette app health motion_lights --since 1h

# Last 24 hours — what's the baseline?
hassette app health motion_lights --since 24h

# Last week — any trends?
hassette app health motion_lights --since 7d
```
