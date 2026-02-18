# Prereq 5: Schema Design

**Status**: Decisions made, ready for implementation

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- [Prereq 1: Data model](./prereq-01-data-model.md) — record fields define all table structures
- [Prereq 3: Exception handling audit](./prereq-03-exception-handling-audit.md) — status values and error field semantics
- [Prereq 4: Frontend query requirements](./prereq-04-frontend-query-requirements.md) — query patterns drive index design

## Dependents

- [Prereq 7: Alembic setup](./prereq-07-alembic-setup.md) — initial migration creates these tables

## Problem

Design the SQLite schema for persistent operational telemetry. Five tables: two parent tables (registration-time metadata), two execution tables (high-frequency writes), and one session table (lifecycle tracking).

## Schema

### `sessions` — framework lifecycle tracking

Created on startup, updated on shutdown. Orphaned sessions (no clean shutdown) are marked `"unknown"` on the next startup.

```sql
CREATE TABLE sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            REAL    NOT NULL,  -- Instant (UTC epoch seconds)
    stopped_at            REAL,              -- Instant, NULL while running
    last_heartbeat_at     REAL    NOT NULL,  -- Instant, updated every N minutes
    status                TEXT    NOT NULL,  -- "running", "success", "error", "unknown"
    error_type            TEXT,              -- exception class name (NULL unless status="error")
    error_message         TEXT,              -- str(exc)
    error_traceback       TEXT               -- traceback.format_exc()
);
```

**Status values:**
- `"running"` — session is active (set on startup)
- `"success"` — clean shutdown completed
- `"error"` — unhandled exception killed the process (error fields populated)
- `"unknown"` — orphaned session detected on next startup (power loss, OOM kill, segfault). `stopped_at` set to `last_heartbeat_at` as best estimate.

**Heartbeat**: `last_heartbeat_at` is updated every N minutes while the session is running. On startup, any session still in `"running"` status is marked `"unknown"` with `stopped_at = last_heartbeat_at`. This gives a "last known alive" estimate without the semantic weirdness of updating `stopped_at` while still running.

### `listeners` — bus event listener registrations (parent table)

Populated once per listener at startup via upsert. Natural key provides cross-restart identity.

```sql
CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,  -- "kitchen.KitchenLights"
    instance_index        INTEGER NOT NULL,  -- 0
    handler_method        TEXT    NOT NULL,  -- "on_light_change"
    topic                 TEXT    NOT NULL,  -- "state_changed.light.kitchen"

    -- Configuration metadata
    debounce              REAL,              -- seconds, NULL if not set
    throttle              REAL,              -- seconds, NULL if not set
    once                  INTEGER NOT NULL DEFAULT 0,  -- boolean
    priority              INTEGER NOT NULL DEFAULT 0,
    predicate_description TEXT,              -- human-readable predicate repr

    -- Source capture
    source_location       TEXT    NOT NULL,  -- "apps/kitchen.py:42"
    registration_source   TEXT,              -- AST-extracted source snippet, NULL if capture failed

    -- Lifecycle
    first_registered_at   REAL    NOT NULL,  -- Instant
    last_registered_at    REAL    NOT NULL,  -- Instant

    UNIQUE (app_key, instance_index, handler_method, topic)
);
```

### `scheduled_jobs` — scheduled job registrations (parent table)

Populated once per job at startup via upsert. Job name uniqueness is validated at `Scheduler.add_job()` registration time (see [prereq 1](./prereq-01-data-model.md)).

```sql
CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,  -- "kitchen.KitchenLights"
    instance_index        INTEGER NOT NULL,  -- 0
    job_name              TEXT    NOT NULL,  -- "open_blinds_morning"

    -- Handler
    handler_method        TEXT    NOT NULL,  -- "open_blinds"

    -- Trigger configuration
    trigger_type          TEXT,              -- "cron", "interval", or NULL (one-shot)
    trigger_value         TEXT,              -- cron: "0 7 * * * 0", interval: "300.0"
    repeat                INTEGER NOT NULL DEFAULT 0,  -- boolean

    -- Registration-time arguments
    args_json             TEXT    NOT NULL DEFAULT '[]',   -- safe_json_serialize(args)
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',   -- safe_json_serialize(kwargs)

    -- Source capture
    source_location       TEXT    NOT NULL,  -- "apps/kitchen.py:58"
    registration_source   TEXT,              -- AST-extracted source snippet, NULL if capture failed

    -- Lifecycle
    first_registered_at   REAL    NOT NULL,  -- Instant
    last_registered_at    REAL    NOT NULL,  -- Instant

    UNIQUE (app_key, instance_index, job_name)
);
```

### `handler_invocations` — per-invocation record for bus event handlers

High-frequency writes. Slim — identity and configuration live on the `listeners` parent table.

```sql
CREATE TABLE handler_invocations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    listener_id           INTEGER NOT NULL REFERENCES listeners(id),
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_dtme  REAL    NOT NULL,  -- Instant (UTC epoch seconds)
    duration_ms           REAL    NOT NULL,  -- monotonic-clock duration
    status                TEXT    NOT NULL,  -- "success", "error", "cancelled"
    error_type            TEXT,              -- exception class name (NULL on success)
    error_message         TEXT,              -- str(exc) (NULL on success)
    error_traceback       TEXT               -- traceback.format_exc() (NULL on success)
);
```

### `job_executions` — per-execution record for scheduled jobs

High-frequency writes. Slim — identity and configuration live on the `scheduled_jobs` parent table.

```sql
CREATE TABLE job_executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                INTEGER NOT NULL REFERENCES scheduled_jobs(id),
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_dtme  REAL    NOT NULL,  -- Instant (UTC epoch seconds)
    duration_ms           REAL    NOT NULL,  -- monotonic-clock duration
    status                TEXT    NOT NULL,  -- "success", "error", "cancelled"
    error_type            TEXT,              -- exception class name (NULL on success)
    error_message         TEXT,              -- str(exc) (NULL on success)
    error_traceback       TEXT               -- traceback.format_exc() (NULL on success)
);
```

## Design decisions

### All timestamps are REAL (Instant)

Every timestamp column is `REAL` storing UTC epoch seconds from `whenever.Instant`. No TEXT/ISO 8601 columns. Consistent, fast numeric comparisons, no ambiguity. Display conversion to local time happens in the UI layer.

See [prereq 1](./prereq-01-data-model.md) for the full timestamp design rationale.

### Status values

**Execution tables** (`handler_invocations`, `job_executions`): `"success"`, `"error"`, `"cancelled"`
- DI failures are `status="error"` with `error_type="DependencyError"` — no distinct status value
- `"cancelled"` is from `asyncio.CancelledError`, typically during shutdown
- See [prereq 3](./prereq-03-exception-handling-audit.md) for the full exception contract

**Sessions table**: `"running"`, `"success"`, `"error"`, `"unknown"`

### Booleans as INTEGER

SQLite has no native boolean type. `once`, `repeat` stored as `INTEGER` (0/1) with `DEFAULT 0`. Standard SQLite convention.

### Session FK on execution tables

Every execution record carries a `session_id` FK. The executor knows its session ID at startup and stamps every record. Cost is one INTEGER per row (8 bytes, constant value). Benefits:
- `WHERE session_id = ?` — scope dashboard to current session
- `WHERE session_id != ?` — show historical data
- `GROUP BY session_id` — cross-session analytics
- Retention by session — `DELETE WHERE session_id IN (SELECT id FROM sessions WHERE started_at < ?)`

Deriving session membership from time ranges is fragile (orphaned sessions have no `stopped_at` until next startup).

### Parent table upsert

On restart, parent tables upsert via their natural key (`UNIQUE` constraint):

```sql
-- Listeners
INSERT INTO listeners (app_key, instance_index, handler_method, topic, ...)
VALUES (?, ?, ?, ?, ...)
ON CONFLICT (app_key, instance_index, handler_method, topic)
DO UPDATE SET
    last_registered_at = excluded.last_registered_at,
    debounce = excluded.debounce,
    throttle = excluded.throttle,
    once = excluded.once,
    priority = excluded.priority,
    predicate_description = excluded.predicate_description,
    source_location = excluded.source_location,
    registration_source = excluded.registration_source;

-- Scheduled jobs
INSERT INTO scheduled_jobs (app_key, instance_index, job_name, ...)
VALUES (?, ?, ?, ...)
ON CONFLICT (app_key, instance_index, job_name)
DO UPDATE SET
    last_registered_at = excluded.last_registered_at,
    handler_method = excluded.handler_method,
    trigger_type = excluded.trigger_type,
    trigger_value = excluded.trigger_value,
    repeat = excluded.repeat,
    args_json = excluded.args_json,
    kwargs_json = excluded.kwargs_json,
    source_location = excluded.source_location,
    registration_source = excluded.registration_source;
```

`first_registered_at` is NOT in the `DO UPDATE` — it's set once on initial insert and preserved across restarts.

## Indexes

Derived from [prereq 4](./prereq-04-frontend-query-requirements.md) query patterns:

```sql
-- handler_invocations
CREATE INDEX idx_hi_listener_time  ON handler_invocations(listener_id, execution_start_dtme DESC);
CREATE INDEX idx_hi_status_time    ON handler_invocations(status, execution_start_dtme DESC);
CREATE INDEX idx_hi_time           ON handler_invocations(execution_start_dtme);
CREATE INDEX idx_hi_session        ON handler_invocations(session_id);

-- job_executions
CREATE INDEX idx_je_job_time       ON job_executions(job_id, execution_start_dtme DESC);
CREATE INDEX idx_je_status_time    ON job_executions(status, execution_start_dtme DESC);
CREATE INDEX idx_je_time           ON job_executions(execution_start_dtme);
CREATE INDEX idx_je_session        ON job_executions(session_id);
```

### Index rationale

| Index                  | Supports                                                                        |
| ---------------------- | ------------------------------------------------------------------------------- |
| `idx_hi_listener_time` | Per-listener drill-down, GROUP BY aggregates for listener summary               |
| `idx_hi_status_time`   | Error drill-down — recent errors across all handlers                            |
| `idx_hi_time`          | Retention cleanup, global time-range queries, dashboard summary                 |
| `idx_hi_session`       | Session scoping — current session vs historical                                 |
| `idx_je_job_time`      | Per-job drill-down, GROUP BY aggregates for job summary                         |
| `idx_je_status_time`   | Error drill-down — recent errors across all jobs                                |
| `idx_je_time`          | Retention cleanup, global time-range queries                                    |
| `idx_je_session`       | Session scoping                                                                 |

Note: The `UNIQUE` constraints on `listeners` and `scheduled_jobs` natural keys serve as implicit indexes for upsert conflict detection and app-level filtering (`WHERE app_key = ? AND instance_index = ?`).

## SQLite configuration

```sql
PRAGMA journal_mode = WAL;           -- concurrent reads during writes
PRAGMA wal_autocheckpoint = 1000;    -- checkpoint after 1000 pages (~4MB)
PRAGMA synchronous = NORMAL;         -- safe with WAL, faster than FULL
PRAGMA busy_timeout = 5000;          -- 5s wait on lock contention
PRAGMA foreign_keys = ON;            -- enforce FK constraints
```

## Retention

Periodic cleanup in the executor's `serve()` loop or a dedicated maintenance task:

```sql
DELETE FROM handler_invocations WHERE execution_start_dtme < ?;
DELETE FROM job_executions WHERE execution_start_dtme < ?;
```

The `?` parameter is computed in Python as `Instant.now() - timedelta(days=retention_days)` converted to epoch seconds.

Default: 7 days, configurable via `HassetteConfig.db_retention_days`. Run once per hour (not per batch cycle).

Sessions are NOT subject to retention — they're tiny (one row per restart) and valuable for long-term analytics.

## Deliverable

Final schema as an Alembic initial migration with all five tables, indexes, and PRAGMA configuration. Feeds into [prereq 7](./prereq-07-alembic-setup.md).
