---
task_id: "T08"
title: "Add log and execution commands"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#1", "FR#2", "FR#6", "AC#1", "AC#5"]
---

## Summary

Implement the log and execution commands. `log` queries recent log entries with filtering by app, time window, limit, and source tier. `execution <uuid>` fetches logs for a specific execution context. These complete the set of CLI commands covering all GET endpoints.

## Prompt

### Create `src/hassette/cli/commands/log.py`

**`hassette log`** — `GET /api/logs/recent` → `list[LogEntryResponse]`
- Render as table
- Supports `--app` (passes `app_key` query param to the logs endpoint — note: this does NOT route to a per-app telemetry endpoint; the logs endpoint accepts `app_key` directly as a filter)
- Supports `--since`, `--limit`, `--source-tier`
- Does NOT support `--instance` — the logs endpoint has no instance filtering (design doc constraint)
- Columns: timestamp, level, app_key, instance_name (if present), function/logger, message (truncated)
- Fields: check `LogEntryResponse` in `web/models.py` line 154

**`hassette execution <uuid>`** — `GET /api/executions/{execution_id}` → `LogsByExecutionResponse`
- Positional argument: `uuid` (execution_id string)
- Render as table (contains a list of log entries for that execution)
- Supports `--limit`
- No other filtering flags — the execution ID is the filter
- Fields: check `LogsByExecutionResponse` in `web/models.py` line 170

### Register commands

Register `log` and `execution` as top-level subcommands on the cyclopts App.

### Unit tests

Test with a mocked HTTP client:
- `log` calls `GET /api/logs/recent` with no params
- `log --app my-app` passes `app_key=my-app` as query param
- `log --since 1h --limit 20` passes correct `since` (epoch float) and `limit=20`
- `log --source-tier framework` passes `source_tier=framework`
- `log --instance 0` exits with usage error (instance not supported on log)
- `execution abc-123-def` calls `GET /api/executions/abc-123-def`
- `execution abc-123-def --limit 50` passes `limit=50`
- Column definitions produce valid tables with representative log data

## Focus

- Response models: `LogEntryResponse` (models.py:154), `LogsByExecutionResponse` (models.py:170)
- Route endpoints: logs.py `GET /api/logs/recent` (line 21); executions.py `GET /api/executions/{execution_id}` (line 51)
- The logs endpoint accepts `app_key`, `level`, `since`, `limit`, `source_tier` as query params — check `src/hassette/web/routes/logs.py` for exact parameter names
- `LogsByExecutionResponse` wraps `entries: list[LogEntryResponse]` and `execution_id: str` — extract the entries list for table rendering
- `--source-tier` behavior on logs: accepts all tiers when omitted (unlike listener/job which default to `app`). This is server behavior — the CLI passes through.
- Log timestamps: `LogEntryResponse` has a `timestamp` field — format it as human-readable relative time in human mode (e.g., "2m ago", "1h ago")

## Verify

- [ ] FR#1: Log and execution commands query correct endpoints and display results
- [ ] FR#2: `log` and `execution` are noun-based subcommands
- [ ] FR#6: `--app`, `--since`, `--limit`, `--source-tier` filter log results correctly
- [ ] AC#1: Both log endpoints (recent and by-execution) are queryable
- [ ] AC#5: `log --since 1h --limit 20` returns at most 20 entries from the last hour
