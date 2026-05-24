---
task_id: "T07"
title: "Add listener and job commands"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#1", "FR#2", "FR#6", "AC#1", "AC#4", "AC#11"]
---

## Summary

Implement listener and job commands with full filtering support. `listener` lists all listeners or filters by app/instance. `listener <id>` shows invocation history. `job` and `job <id>` follow the same pattern for scheduled jobs. These commands exercise the most filtering flags — `--app`, `--instance`, `--since`, `--source-tier`, and `--limit`.

## Prompt

### Create `src/hassette/cli/commands/listener.py`

**`hassette listener`** — `GET /api/bus/listeners` → `list[ListenerWithSummary]`
- Render as table
- Supports `--app` (routes to `/api/telemetry/app/{key}/listeners`), `--instance`, `--since`, `--source-tier`
- When `--app` is provided, `--instance` is available. When `--app` is not provided, `--instance` is a usage error.
- Columns: select from ListenerWithSummary fields for 80-column display. Key fields: listener ID, topic/entity, handler method name, kind, invocation counts (total/ok/fail), avg duration, instance_index (when filtering by app)
- Fields: check `ListenerWithSummary` in `web/models.py` line 295

**`hassette listener <id>`** — `GET /api/telemetry/handler/{id}/invocations` → `list[HandlerInvocation]`
- Positional argument: `id` (listener_id, integer)
- Render as table
- Supports `--since` and `--limit`
- Columns: invocation status, duration, error details, timestamps
- Fields: check `HandlerInvocation` in `core/telemetry_models.py` line 99

### Create `src/hassette/cli/commands/job.py`

**`hassette job`** — `GET /api/scheduler/jobs` → `list[JobSummary]`
- Render as table
- Supports `--app` (routes to `/api/telemetry/app/{key}/jobs`), `--instance`, `--since`, `--source-tier`
- Same `--app`/`--instance` relationship as listener
- Columns: select from JobSummary fields. Key fields: job ID, function name, trigger type, next run, execution counts, instance_index
- Fields: check `JobSummary` in `core/telemetry_models.py` line 120

**`hassette job <id>`** — `GET /api/telemetry/job/{id}/executions` → `list[JobExecution]`
- Positional argument: `id` (job_id, integer)
- Render as table
- Supports `--since` and `--limit`
- Columns: execution status, duration, error details, timestamps
- Fields: check `JobExecution` in `core/telemetry_models.py` line 171

### Register commands

Register `listener` and `job` as subcommands on the cyclopts App. The bare forms (no positional ID) list all items. With an ID positional, they show history.

### Unit tests

Use the shared mock client fixture from T03 and test data factories from `src/hassette/test_utils/web_helpers.py`. Do NOT create parallel mock client setup or test data builders.

For each command, test with the mocked HTTP client:
- `listener` calls `GET /api/bus/listeners`
- `listener --app my-app` calls `GET /api/telemetry/app/my-app/listeners`
- `listener --app my-app --instance 0` passes `instance_index=0`
- `listener --instance 0` (without `--app`) exits with usage error
- `listener --source-tier app` passes `source_tier=app`
- `listener 42` calls `GET /api/telemetry/handler/42/invocations`
- `listener 42 --limit 5` passes `limit=5`
- Same set for `job` commands
- Column definitions produce valid tables at 80 columns

## Focus

- Response models: `ListenerWithSummary` (models.py:295), `HandlerInvocation` (telemetry_models.py:99), `JobSummary` (telemetry_models.py:120), `JobExecution` (telemetry_models.py:171)
- Route endpoints: bus.py `GET /api/bus/listeners` (line 19); scheduler.py `GET /api/scheduler/jobs` (line 21); telemetry.py `GET /api/telemetry/app/{key}/listeners` (line 178), `GET /api/telemetry/app/{key}/jobs` (line 229), `GET /api/telemetry/handler/{id}/invocations` (line 268), `GET /api/telemetry/job/{id}/executions` (line 285)
- Endpoint routing: the global endpoints (`/api/bus/listeners`, `/api/scheduler/jobs`) and per-app endpoints (`/api/telemetry/app/{key}/listeners`, `/api/telemetry/app/{key}/jobs`) return the same model types — ListenerWithSummary and JobSummary respectively
- `--source-tier` default: listener and job endpoints default to `app` when source_tier is omitted — this is server behavior, the CLI just passes it through
- Wide tables: ListenerWithSummary has many fields — choose columns carefully for 80-column fit. Consider hiding some columns by default and showing all in JSON mode.

## Verify

- [ ] FR#1: Listener and job commands query correct endpoints and display results
- [ ] FR#2: `listener`, `listener <id>`, `job`, `job <id>` are noun-based subcommands
- [ ] FR#6: `--app`, `--instance`, `--since`, `--source-tier`, `--limit` filter correctly
- [ ] AC#1: All four listener/job endpoints are queryable
- [ ] AC#4: `listener --app my-app` returns only listeners belonging to my-app
