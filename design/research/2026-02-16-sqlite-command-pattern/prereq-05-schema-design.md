# Prereq 5: Schema Design

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 1: HandlerInvocationRecord](./prereq-01-handler-invocation-record.md) — record fields define `handler_invocations` columns
- [Prereq 2: Stable listener identity](./prereq-02-stable-listener-identity.md) — stable key is a column in `handler_invocations`
- [Prereq 3: Exception handling audit](./prereq-03-exception-handling-audit.md) — status values and error field semantics
- [Prereq 4: Frontend query requirements](./prereq-04-frontend-query-requirements.md) — query patterns drive index design
- [Prereq 6: Open questions](./prereq-06-open-questions.md) — DB file location, retention policy, aiosqlite decision

## Dependents

- [Prereq 7: Alembic setup](./prereq-07-alembic-setup.md) — initial migration creates these tables

## Problem

Design the SQLite schema for persistent operational telemetry. Three tables needed: handler invocations, job executions, and session tracking.

## Proposed schema

### `handler_invocations` — per-invocation record for bus event handlers

```sql
CREATE TABLE handler_invocations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_key  TEXT    NOT NULL,  -- "{owner}:{handler_name}:{topic}" from prereq 2
    owner       TEXT    NOT NULL,  -- resource unique_name
    topic       TEXT    NOT NULL,  -- event topic dispatched
    handler_name TEXT   NOT NULL,  -- module-qualified handler name
    started_at  REAL    NOT NULL,  -- unix timestamp (time.time())
    duration_ms REAL    NOT NULL,  -- monotonic-clock duration
    status      TEXT    NOT NULL,  -- "success", "error", "cancelled"
    error_type  TEXT,              -- exception class name (NULL on success)
    error_message TEXT,            -- str(exc) (NULL on success)
    error_traceback TEXT,          -- traceback.format_exc() (NULL on success)
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))  -- for retention cleanup
);
```

### `job_executions` — per-execution record for scheduled jobs

```sql
CREATE TABLE job_executions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL,  -- ScheduledJob.job_id (process-local, may repeat across restarts)
    job_name        TEXT    NOT NULL,  -- ScheduledJob.name
    owner           TEXT    NOT NULL,  -- ScheduledJob.owner
    started_at      REAL    NOT NULL,  -- unix timestamp (time.time())
    duration_ms     REAL    NOT NULL,  -- monotonic-clock duration
    status          TEXT    NOT NULL,  -- "success", "error", "cancelled"
    error_type      TEXT,
    error_message   TEXT,
    error_traceback TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

### `sessions` — framework lifecycle tracking

```sql
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,  -- ISO 8601 datetime
    stopped_at  TEXT,             -- NULL while running
    stop_reason TEXT              -- "clean_shutdown", "crash", "unknown"
);
```

## Design decisions

### Timestamps: REAL vs TEXT

| Column                                 | Type   | Rationale                                                                                                          |
| -------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------ |
| `started_at` (invocations/jobs)        | `REAL` | Unix timestamp, fast numeric comparisons for range queries, matches Python's `time.time()` return type             |
| `created_at`                           | `TEXT` | ISO 8601 via `datetime('now')`, human-readable in sqlite3 CLI, used only for retention cleanup (not perf-critical) |
| `started_at` / `stopped_at` (sessions) | `TEXT` | ISO 8601, low-frequency writes, human readability matters more than comparison speed                               |

### Status values

Shared across both tables: `"success"`, `"error"`, `"cancelled"`

No `"di_failure"` status — DI failures are `status="error"` with `error_type="DependencyError"`. See [prereq 3](./prereq-03-exception-handling-audit.md) for rationale.

### `job_id` is not a foreign key

`ScheduledJob.job_id` is a process-local auto-incrementing int (like `listener_id`). It resets on restart. It's stored as a denormalized value for correlating executions within a single session, not as a relational key. The `job_name` + `owner` combination provides cross-restart identity.

## Indexes

Derived from [prereq 4](./prereq-04-frontend-query-requirements.md) query patterns:

```sql
-- handler_invocations
CREATE INDEX idx_hi_owner        ON handler_invocations(owner);
CREATE INDEX idx_hi_key_time     ON handler_invocations(stable_key, started_at DESC);
CREATE INDEX idx_hi_status_time  ON handler_invocations(status, started_at DESC);
CREATE INDEX idx_hi_created      ON handler_invocations(created_at);

-- job_executions
CREATE INDEX idx_je_owner_time   ON job_executions(owner, started_at DESC);
CREATE INDEX idx_je_created      ON job_executions(created_at);
```

### Index rationale

| Index                | Supports                                                       |
| -------------------- | -------------------------------------------------------------- |
| `idx_hi_owner`       | `get_listener_metrics(owner)` — filter by app owner            |
| `idx_hi_key_time`    | Handler drill-down — last N invocations for a specific handler |
| `idx_hi_status_time` | Error dashboard — recent errors across all handlers            |
| `idx_hi_created`     | Retention cleanup — `DELETE WHERE created_at < ?`              |
| `idx_je_owner_time`  | `get_job_execution_history(limit, owner)` — job history by app |
| `idx_je_created`     | Retention cleanup                                              |

## SQLite configuration

```sql
PRAGMA journal_mode = WAL;           -- concurrent reads during writes
PRAGMA wal_autocheckpoint = 1000;    -- checkpoint after 1000 pages (~4MB)
PRAGMA synchronous = NORMAL;         -- safe with WAL, faster than FULL
PRAGMA busy_timeout = 5000;          -- 5s wait on lock contention
PRAGMA foreign_keys = ON;            -- habit, even though we have no FKs yet
```

## Retention

Periodic cleanup in the executor's `serve()` loop (or a dedicated maintenance task):

```sql
DELETE FROM handler_invocations WHERE created_at < datetime('now', '-7 days');
DELETE FROM job_executions WHERE created_at < datetime('now', '-7 days');
```

Default: 7 days, configurable via `HassetteConfig.db_retention_days`. Run once per hour (not per batch cycle).

## Open items

- [ ] Confirm `stable_key` format once [prereq 2](./prereq-02-stable-listener-identity.md) is finalized
- [ ] Confirm status values once [prereq 3](./prereq-03-exception-handling-audit.md) decisions are made
- [ ] Benchmark aggregate query performance with ~100k rows to validate Strategy A vs B from [prereq 4](./prereq-04-frontend-query-requirements.md)

## Deliverable

Final `schema.sql` file (or Alembic initial migration) with all three tables, indexes, and PRAGMA configuration. Feeds into [prereq 7](./prereq-07-alembic-setup.md).
