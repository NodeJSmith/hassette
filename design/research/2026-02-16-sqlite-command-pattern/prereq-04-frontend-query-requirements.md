# Prereq 4: Frontend Query Requirements Audit

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — can start immediately (analysis of existing code)

## Dependents

- [Prereq 5: Schema design](./prereq-05-schema-design.md) — query patterns drive index design

## Problem

Schema indexes should be driven by the actual queries `DataSyncService` will run, not guessed. This prereq maps every current read path to a future DB query pattern and identifies new queries the DB enables.

## Current read paths in `DataSyncService`

From `core/data_sync_service.py`:

### Bus / Listener data

| Method                                              | Current source                                                                             | Called by                  |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------------------------- |
| `get_listener_metrics(owner)`                       | `bus_service.get_all_listener_metrics()` → `dict[int, ListenerMetrics]`, filtered by owner | Dashboard listener list    |
| `get_listener_metrics_for_instance(app_key, index)` | Same, filtered by resolved owner                                                           | Per-instance listener view |
| `get_bus_metrics_summary()`                         | Sum over all `ListenerMetrics` values                                                      | Dashboard summary cards    |

### Scheduler / Job data

| Method                                    | Current source                                                                                                | Called by                     |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| `get_job_execution_history(limit, owner)` | `scheduler_service.get_execution_history()` → `deque[JobExecutionRecord]`, filtered by owner, sliced by limit | Dashboard job history table   |
| `get_scheduled_jobs(owner)`               | `scheduler_service.get_all_jobs()` → heap queue                                                               | Dashboard scheduled jobs list |
| `get_scheduler_summary()`                 | Count over all jobs                                                                                           | Dashboard summary cards       |

### Other (not migrating to DB)

| Method                                                                   | Source                         | Notes                                |
| ------------------------------------------------------------------------ | ------------------------------ | ------------------------------------ |
| `get_entity_state()` / `get_all_entity_states()` / `get_domain_states()` | `StateProxy`                   | Stays in-memory (mirrors HA)         |
| `get_app_status_snapshot()` / `get_all_manifests_snapshot()`             | `AppHandler`                   | Runtime state, not telemetry         |
| `get_recent_events(limit)`                                               | `_event_buffer: deque[dict]`   | Could move to DB later, not in scope |
| `get_recent_logs(limit, app_key, level)`                                 | `LogCaptureHandler._buffer`    | Could move to DB later, not in scope |
| `get_system_status()`                                                    | Computed from multiple sources | Runtime state, not telemetry         |

## Future DB query patterns

### Replacing `get_listener_metrics(owner)` — aggregate view

This is the most complex migration. Currently returns `ListenerMetrics` objects with aggregate fields. Two strategies:

**Strategy A: Compute from per-invocation records**
```sql
SELECT
    stable_key,
    owner,
    handler_name,
    topic,
    COUNT(*) as total_invocations,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed,
    SUM(CASE WHEN status = 'error' AND error_type = 'DependencyError' THEN 1 ELSE 0 END) as di_failures,
    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
    AVG(duration_ms) as avg_duration_ms,
    MIN(duration_ms) as min_duration_ms,
    MAX(duration_ms) as max_duration_ms,
    MAX(started_at) as last_invoked_at
FROM handler_invocations
WHERE owner = ?
GROUP BY stable_key
```

Pros: Single source of truth, no dual maintenance. Cons: Potentially slow on large tables (mitigated by indexes + retention policy).

**Strategy B: Keep `ListenerMetrics` in parallel, use DB for drill-down only**

Pros: Fast aggregate reads (in-memory). Cons: Dual data paths, aggregates can drift from DB if there's a bug.

**Recommendation**: Start with Strategy B (parallel), migrate to Strategy A once we can benchmark aggregate query performance with realistic data volumes. The parallel approach lets the dashboard stay fast while we build confidence in DB performance.

### Replacing `get_job_execution_history(limit, owner)`

```sql
SELECT job_id, job_name, owner, started_at, duration_ms, status,
       error_type, error_message, error_traceback
FROM job_executions
WHERE owner = ?  -- optional filter
ORDER BY started_at DESC
LIMIT ?
```

Straightforward — `JobExecutionRecord` already has all needed fields.

### Replacing `get_bus_metrics_summary()`

```sql
SELECT
    COUNT(*) as total,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed,
    AVG(duration_ms) as avg_duration_ms
FROM handler_invocations
```

Or, with Strategy B, just sum the in-memory `ListenerMetrics` as today.

### New queries the DB enables

These don't exist today but are natural once per-invocation data is persisted:

| Query                      | Use case                                             | SQL pattern                                                                   |
| -------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------- |
| Handler invocation history | Click a handler → see last N invocations             | `WHERE stable_key = ? ORDER BY started_at DESC LIMIT ?`                       |
| Error drill-down           | Dashboard error tab, filter by time/type             | `WHERE status = 'error' AND started_at > ? ORDER BY started_at DESC`          |
| Duration trends            | Performance sparkline per handler                    | `WHERE stable_key = ? ORDER BY started_at DESC LIMIT 100` (compute in Python) |
| Cross-restart history      | "This handler has failed 47 times across 3 sessions" | `WHERE stable_key = ? GROUP BY ...` (joins sessions table)                    |
| Slow handler detection     | Highlight handlers > p95 duration                    | `WHERE duration_ms > ? ORDER BY duration_ms DESC LIMIT ?`                     |

## Index recommendations

Based on the query patterns above:

```sql
-- Primary access pattern: filter by owner, group by stable_key
CREATE INDEX idx_handler_inv_owner ON handler_invocations(owner);

-- Drill-down: specific handler history
CREATE INDEX idx_handler_inv_key_time ON handler_invocations(stable_key, started_at DESC);

-- Error filtering
CREATE INDEX idx_handler_inv_status_time ON handler_invocations(status, started_at DESC);

-- Retention cleanup
CREATE INDEX idx_handler_inv_created ON handler_invocations(created_at);

-- Job history: filter by owner, order by time
CREATE INDEX idx_job_exec_owner_time ON job_executions(owner, started_at DESC);

-- Job retention cleanup
CREATE INDEX idx_job_exec_created ON job_executions(created_at);
```

## Deliverable

This file, refined after reviewing actual template code to confirm which methods are called and how results are rendered. The index list feeds directly into [prereq 5](./prereq-05-schema-design.md).
