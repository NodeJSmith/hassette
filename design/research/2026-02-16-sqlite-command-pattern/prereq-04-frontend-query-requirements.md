# Prereq 4: Frontend Query Requirements

**Status**: Decisions made, ready for implementation

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 1: Data model](./prereq-01-data-model.md) — table structure and column names

## Dependents

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — uses these query patterns to drive index and FK design (including session table and session FK on execution tables)

## Problem

Schema indexes should be driven by the queries the UI actually needs, not guessed. This prereq defines what the UI should be able to show, translates that into query patterns against the [prereq 1 data model](./prereq-01-data-model.md), and identifies indexes.

The current `DataSyncService` was a proof of concept — we're designing from "what should the UI show" forward, not mapping existing methods 1:1.

## Decisions

### Single source of truth: DB only, no parallel in-memory aggregates

**Decision**: All telemetry reads come from the database. No parallel in-memory `ListenerMetrics` path.

Dual data paths inevitably drift. One source of truth, one code path, one place to debug. If aggregate queries are slow, we add indexes or materialized views — not a second data path.

`ListenerMetrics` in its current form is retired. Aggregate values are computed via SQL `GROUP BY` against `handler_invocations` joined to `listeners`.

## What the UI should show

### Per-app listener summary

"For this app instance, show me all its listeners and how they're doing."

```sql
SELECT
    l.id,
    l.handler_method,
    l.topic,
    l.debounce,
    l.throttle,
    l.once,
    l.priority,
    l.predicate_description,
    l.source_location,
    l.registration_source,
    COUNT(hi.rowid) AS total_invocations,
    SUM(CASE WHEN hi.status = 'success' THEN 1 ELSE 0 END) AS successful,
    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS failed,
    SUM(CASE WHEN hi.status = 'error' AND hi.error_type = 'DependencyError' THEN 1 ELSE 0 END) AS di_failures,
    SUM(CASE WHEN hi.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
    SUM(hi.duration_ms) AS total_duration_ms,
    AVG(hi.duration_ms) AS avg_duration_ms,
    MIN(hi.duration_ms) AS min_duration_ms,
    MAX(hi.duration_ms) AS max_duration_ms,
    MAX(hi.execution_start_ts) AS last_invoked_at,
    -- Last error details (from most recent error invocation)
    last_err.error_type AS last_error_type,
    last_err.error_message AS last_error_message
FROM listeners l
LEFT JOIN handler_invocations hi ON hi.listener_id = l.id
LEFT JOIN handler_invocations last_err ON last_err.id = (
    SELECT id FROM handler_invocations
    WHERE listener_id = l.id AND status = 'error'
    ORDER BY execution_start_ts DESC LIMIT 1
)
WHERE l.app_key = ? AND l.instance_index = ?
GROUP BY l.id
```

### Per-app job summary

"For this app instance, show me all its scheduled jobs and their recent results."

```sql
SELECT
    sj.id,
    sj.job_name,
    sj.handler_method,
    sj.trigger_type,
    sj.trigger_value,
    sj.repeat,
    sj.args_json,
    sj.kwargs_json,
    sj.source_location,
    sj.registration_source,
    COUNT(je.rowid) AS total_executions,
    SUM(CASE WHEN je.status = 'success' THEN 1 ELSE 0 END) AS successful,
    SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS failed,
    MAX(je.execution_start_ts) AS last_executed_at,
    AVG(je.duration_ms) AS avg_duration_ms
FROM scheduled_jobs sj
LEFT JOIN job_executions je ON je.job_id = sj.id
WHERE sj.app_key = ? AND sj.instance_index = ?
GROUP BY sj.id
```

### Global summary cards (dashboard)

"High-level numbers across all listeners and jobs."

```sql
-- Listener summary
SELECT
    (SELECT COUNT(*) FROM listeners) AS total_listeners,
    COUNT(DISTINCT hi.listener_id) AS invoked_listeners,
    COUNT(hi.rowid) AS total_invocations,
    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
    SUM(CASE WHEN hi.status = 'error' AND hi.error_type = 'DependencyError' THEN 1 ELSE 0 END) AS total_di_failures,
    AVG(hi.duration_ms) AS avg_duration_ms
FROM handler_invocations hi

-- Job summary
SELECT
    (SELECT COUNT(*) FROM scheduled_jobs) AS total_jobs,
    COUNT(DISTINCT je.job_id) AS executed_jobs,
    COUNT(je.rowid) AS total_executions,
    SUM(CASE WHEN je.status = 'error' THEN 1 ELSE 0 END) AS total_errors
FROM job_executions je
```

Note: `total_listeners` / `total_jobs` counts all registered entries from the parent tables (including those never invoked). `invoked_listeners` / `executed_jobs` counts only those with at least one execution record.

### Handler invocation history (drill-down) — NEW

**Currently missing from the UI.** The bus page shows aggregate counts per listener but there is no way to click into a listener and see individual invocations. The scheduler page has this for jobs (execution history table) but listeners have no equivalent. This is a key new capability enabled by per-invocation records in the DB.

"Click a listener → see its last N invocations."

```sql
SELECT
    hi.execution_start_ts,
    hi.duration_ms,
    hi.status,
    hi.error_type,
    hi.error_message,
    hi.error_traceback
FROM handler_invocations hi
WHERE hi.listener_id = ?
ORDER BY hi.execution_start_ts DESC
LIMIT ?
```

### Job execution history (drill-down)

"Click a job → see its last N executions."

```sql
SELECT
    je.execution_start_ts,
    je.duration_ms,
    je.status,
    je.error_type,
    je.error_message
FROM job_executions je
WHERE je.job_id = ?
ORDER BY je.execution_start_ts DESC
LIMIT ?
```

### Error drill-down

"Show me all recent errors across all handlers and jobs."

```sql
-- Handler errors
SELECT
    l.app_key,
    l.handler_method,
    l.topic,
    hi.execution_start_ts,
    hi.duration_ms,
    hi.error_type,
    hi.error_message
FROM handler_invocations hi
JOIN listeners l ON l.id = hi.listener_id
WHERE hi.status = 'error'
    AND hi.execution_start_ts > ?  -- time filter
ORDER BY hi.execution_start_ts DESC
LIMIT ?

-- Job errors (same pattern)
SELECT
    sj.app_key,
    sj.job_name,
    sj.handler_method,
    je.execution_start_ts,
    je.duration_ms,
    je.error_type,
    je.error_message
FROM job_executions je
JOIN scheduled_jobs sj ON sj.id = je.job_id
WHERE je.status = 'error'
    AND je.execution_start_ts > ?
ORDER BY je.execution_start_ts DESC
LIMIT ?
```

### Slow handler/job detection

"Highlight anything running slower than expected."

```sql
SELECT
    l.app_key,
    l.handler_method,
    l.topic,
    hi.execution_start_ts,
    hi.duration_ms
FROM handler_invocations hi
JOIN listeners l ON l.id = hi.listener_id
WHERE hi.duration_ms > ?  -- threshold
ORDER BY hi.duration_ms DESC
LIMIT ?
```

### Session list

"Show me all sessions — when they started, how long they ran, how they ended."

```sql
SELECT
    s.id,
    s.started_at,
    s.stopped_at,
    s.status,
    s.error_type,
    s.error_message,
    (COALESCE(s.stopped_at, s.last_heartbeat_at) - s.started_at) AS duration_seconds
FROM sessions s
ORDER BY s.started_at DESC
LIMIT ?
```

### Current session summary

"This session has been running for X hours with Y invocations and Z errors."

```sql
SELECT
    s.started_at,
    s.last_heartbeat_at,
    (SELECT COUNT(*) FROM handler_invocations WHERE session_id = s.id) AS total_invocations,
    (SELECT COUNT(*) FROM handler_invocations WHERE session_id = s.id AND status = 'error') AS invocation_errors,
    (SELECT COUNT(*) FROM job_executions WHERE session_id = s.id) AS total_executions,
    (SELECT COUNT(*) FROM job_executions WHERE session_id = s.id AND status = 'error') AS execution_errors
FROM sessions s
WHERE s.status = 'running'
```

### Session scoping

Most queries above support an optional `AND session_id = ?` filter to scope to the current session or a specific historical session. This enables a "current session" vs "all time" toggle in the UI.

Examples of session-scoped variants:

```sql
-- Per-app listener summary, current session only
SELECT ...
FROM listeners l
LEFT JOIN handler_invocations hi ON hi.listener_id = l.id AND hi.session_id = ?
WHERE l.app_key = ? AND l.instance_index = ?
GROUP BY l.id

-- Global summary cards, current session only
SELECT
    COUNT(DISTINCT hi.listener_id) AS active_listeners,
    COUNT(hi.rowid) AS total_invocations,
    SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS total_errors,
    AVG(hi.duration_ms) AS avg_duration_ms
FROM handler_invocations hi
WHERE hi.session_id = ?

-- Error drill-down, current session only
SELECT ...
FROM handler_invocations hi
JOIN listeners l ON l.id = hi.listener_id
WHERE hi.status = 'error' AND hi.session_id = ?
ORDER BY hi.execution_start_ts DESC
LIMIT ?
```

The session filter goes on the JOIN condition (for LEFT JOINs with GROUP BY) or in the WHERE clause (for direct queries). This keeps the "all time" query as the default and session scoping as an additive filter.

## Data that stays in-memory (not in DB)

Some data the UI currently shows is runtime state that doesn't belong in the telemetry DB:

| Data                          | Current source                     | Why it stays in-memory                                                              |
| ----------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------- |
| Scheduled job `next_run`      | Scheduler heap queue               | Computed from trigger config + current time. Changes every execution.               |
| Scheduled job `cancelled` flag | `ScheduledJob.cancelled`          | Runtime lifecycle state — a cancelled job is removed, not persisted.                |
| App status (running/stopped)  | `AppHandler` / manifests           | Runtime lifecycle, not telemetry. Changes on start/stop/reload.                     |
| Entity states                 | `StateProxy` (mirrors HA)          | Real-time HA state, not hassette telemetry.                                         |
| Recent events buffer          | `DataSyncService._event_buffer`    | Rolling 50-event buffer for dashboard timeline. Could move to DB later, not now.    |
| Recent logs                   | `LogCaptureHandler._buffer`        | In-memory log ring buffer. Could move to DB later, not now.                         |

The scheduler page will continue to read `next_run` and `cancelled` from the in-memory scheduler, alongside DB-sourced execution history and registration metadata. These are complementary data sources, not competing ones — runtime state from memory, historical telemetry from DB.

### Retention cleanup

"Delete records older than N days."

```sql
DELETE FROM handler_invocations
WHERE execution_start_ts < ?

DELETE FROM job_executions
WHERE execution_start_ts < ?
```

## Index recommendations

Driven by the query patterns above. All execution table indexes include the FK column for JOIN performance.

```sql
-- handler_invocations
CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC);
CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC);
CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts);
CREATE INDEX idx_hi_session ON handler_invocations(session_id);

-- job_executions
CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC);
CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC);
CREATE INDEX idx_je_time ON job_executions(execution_start_ts);
CREATE INDEX idx_je_session ON job_executions(session_id);

-- listeners (natural key for upsert + app filtering)
CREATE UNIQUE INDEX idx_listeners_natural_key ON listeners(app_key, instance_index, handler_method, topic);

-- scheduled_jobs (natural key for upsert + app filtering)
CREATE UNIQUE INDEX idx_jobs_natural_key ON scheduled_jobs(app_key, instance_index, job_name);
```

Notes:
- `idx_hi_listener_time` / `idx_je_job_time` — covers drill-down queries and the GROUP BY aggregates (SQLite can use the index to skip scanning irrelevant rows)
- `idx_hi_status_time` / `idx_je_status_time` — covers error drill-down
- `idx_hi_time` / `idx_je_time` — covers retention cleanup and time-range filters on global queries
- `idx_hi_session` / `idx_je_session` — covers session scoping and current session summary subqueries
- Natural key unique indexes on parent tables double as the upsert conflict target and the app-level filter

## UI layout decisions deferred to implementation

This prereq defines *what data* the UI needs but not *where it goes*. Layout decisions for new views (handler invocation drill-down, session list, current/all-time toggle, source code display) will be made during implementation. The existing UI patterns provide clear precedent — the bus page already has expandable detail rows, the scheduler page already has a history table, and the design system is documented in `design/interface-design/`.

## Deliverable

This file (decisions finalized). Query patterns and index recommendations feed directly into [prereq 5](./prereq-05-schema-design.md). `DataSyncService` decomposition is tracked in [prereq 8](./prereq-08-datasyncservice-decomposition.md).
