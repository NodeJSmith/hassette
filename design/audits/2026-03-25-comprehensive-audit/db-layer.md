# Database Layer Audit — Hassette

## Summary

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Queries | 0 | 0 | 2 | 1 |
| Schema | 0 | 0 | 1 | 1 |
| Connections | 0 | 1 | 0 | 0 |
| Migrations | 0 | 0 | 0 | 1 |

**Database:** SQLite (via aiosqlite)
**ORM:** None (raw SQL with parameterized queries)
**Migration tool:** Alembic
**Write serialization:** Single-writer queue (`asyncio.Queue` + worker task)

**Verdict: PASS** — No CRITICAL or HIGH findings that block release. The one HIGH finding (read/write contention on a shared connection) is a design trade-off appropriate for the deployment context (single-node Home Assistant add-on with SQLite). All MEDIUM/LOW findings are documented with acceptance rationale below.

---

## Architecture Overview

The database layer is well-structured for its purpose (operational telemetry for a single-node automation framework):

- **DatabaseService** (`src/hassette/core/database_service.py`) owns the single `aiosqlite.Connection`, runs Alembic migrations on startup, manages heartbeat and retention cleanup.
- **CommandExecutor** (`src/hassette/core/command_executor.py`) batches write records (handler invocations, job executions) via an in-memory queue, persisting in batches of up to 100 with `executemany`.
- **SessionManager** (`src/hassette/core/session_manager.py`) manages session lifecycle (create, finalize, crash recording, orphan cleanup).
- **TelemetryQueryService** (`src/hassette/core/telemetry_query_service.py`) provides read-only query methods for the web UI.
- All writes are serialized through `DatabaseService.submit()` / `enqueue()` which routes through a single `_db_write_worker` task — preventing concurrent write conflicts on SQLite.

### What is done well

1. **Parameterized queries everywhere** — no SQL injection risk. All user-facing values use `?` placeholders. The f-string usage in `TelemetryQueryService` only interpolates static clause fragments (`join_condition`, `session_clause`), never user input.
2. **WAL mode + NORMAL synchronous** — good SQLite performance configuration (`_set_pragmas`).
3. **Foreign keys enabled** — `PRAGMA foreign_keys = ON`.
4. **Comprehensive indexing** — all high-cardinality tables (`handler_invocations`, `job_executions`) have indexes on their primary query patterns (by parent ID + timestamp, by status + timestamp, by session, by timestamp alone).
5. **Retention cleanup** — automatic hourly cleanup of records older than `db_retention_days` (default 7).
6. **Sentinel filtering** — records with `listener_id=0` or `session_id=0` are dropped before insert, preventing garbage data.
7. **Batch writes** — `executemany` for telemetry records, reducing transaction overhead.
8. **Graceful shutdown** — write queue is drained before connection close.
9. **Proper down migrations** — all 3 migration files have working `downgrade()` functions.

---

## HIGH

### DB-001: Read/write contention on shared aiosqlite connection
**Files:**
- `src/hassette/core/database_service.py:67` (single `db` property)
- `src/hassette/core/telemetry_query_service.py:51` (reads via `_db` property)

**Issue:** All writes are properly serialized through the `_db_write_worker` queue, but reads in `TelemetryQueryService` execute directly on the same `aiosqlite.Connection` without going through the write queue. This means a web UI query and a batch write can execute concurrently on the same connection object.

**Impact:** With SQLite WAL mode, concurrent reads and writes are generally safe at the database level. However, `aiosqlite.Connection` is a wrapper around a synchronous `sqlite3.Connection` running in a dedicated thread. Concurrent `execute()` calls from different asyncio tasks against the same wrapper could interleave in unexpected ways if aiosqlite's internal serialization has edge cases. In practice, this is unlikely to cause issues because aiosqlite internally serializes calls to the background thread, but it relies on an undocumented implementation detail.

**Severity rationale:** Rated HIGH because correctness depends on aiosqlite's internal threading model rather than an explicit architectural guarantee. However, this is acceptable for the deployment context: a single-node Home Assistant add-on where the web UI serves one or two concurrent users, not a high-throughput web service.

**Recommendation:** Accept as-is for current deployment scope. If the project ever moves to a multi-user or high-concurrency scenario, consider opening a separate read-only connection for `TelemetryQueryService`. This would give true reader/writer isolation under WAL mode.

---

## MEDIUM

### DB-002: N+1-like query pattern in `gather_all_listeners`
**File:** `src/hassette/web/utils.py:18-38`

**Issue:** `gather_all_listeners()` issues one `get_listener_summary()` SQL query per app instance, then gathers results with `asyncio.gather`. For N app instances, this produces N separate SQL queries against the database.

**Impact:** For a typical Home Assistant setup with 5-20 apps, this means 5-20 queries per request to `/bus/listeners`. The queries run concurrently via `asyncio.gather` but still serialize at the aiosqlite level (single connection thread). At 20 apps this is unlikely to be noticeable (each query is indexed and fast), but it scales linearly with app count.

**Severity rationale:** Rated MEDIUM because N is bounded by the number of user-configured apps (typically <30) and the existing `get_all_app_summaries()` method already demonstrates the correct batch pattern for the dashboard. This endpoint is not on a hot path.

**Recommendation:** If app count grows or latency becomes noticeable, refactor to a single batch query similar to `get_all_app_summaries()`. For now, acceptable.

### DB-003: Correlated subqueries in `get_current_session_summary`
**File:** `src/hassette/core/telemetry_query_service.py:514-532`

**Issue:** The `get_current_session_summary()` query uses 4 correlated scalar subqueries (COUNT on `handler_invocations` and `job_executions`, each with a status filter variant). Each subquery scans the respective table filtered by `session_id`.

**Impact:** With the existing `idx_hi_session` and `idx_je_session` indexes, each subquery is an index scan. For a long-running session accumulating thousands of records, these 4 index scans execute on every dashboard load. At 10,000 invocations per session, this is still fast (<10ms on SQLite), but it does not scale gracefully.

**Severity rationale:** MEDIUM. The session-scoped telemetry volume is bounded by retention (7 days default) and the typical event rate of a home automation system (hundreds to low thousands per day). This would only become a problem with unusually high-frequency automations.

**Recommendation:** Consider adding a composite index on `(session_id, status)` for both tables if dashboard latency becomes a concern. Alternatively, maintain running counters in the session row itself.

### DB-004: No `CHECK` constraints on `status` columns
**Files:**
- `src/hassette/migrations/versions/001_initial_schema.py:18` (`sessions.status`)
- `src/hassette/migrations/versions/001_initial_schema.py:74` (`handler_invocations.status`)
- `src/hassette/migrations/versions/001_initial_schema.py:89` (`job_executions.status`)

**Issue:** The `status` columns in `sessions`, `handler_invocations`, and `job_executions` are `TEXT NOT NULL` without `CHECK` constraints to enforce valid values. Invalid status values would not be rejected by the database.

**Impact:** Low. The application layer uses well-defined constants ("running", "success", "error", "cancelled", "failure", "unknown"). There is no user-facing input path that could inject arbitrary status values. This is a defense-in-depth concern, not an active risk.

**Recommendation:** Add `CHECK` constraints in a future migration:
```sql
CHECK (status IN ('running', 'success', 'failure', 'unknown'))  -- sessions
CHECK (status IN ('success', 'error', 'cancelled'))             -- invocations/executions
```

---

## LOW

### DB-005: No `VACUUM` or `ANALYZE` scheduled
**File:** `src/hassette/core/database_service.py`

**Issue:** There is no periodic `VACUUM` or `ANALYZE` command. The retention cleanup deletes rows hourly, but SQLite does not reclaim disk space from deleted rows without `VACUUM`. `ANALYZE` updates query planner statistics.

**Impact:** Minimal for the expected data volume. With 7-day retention and typical home automation event rates (hundreds/day), the database stays small (< 50MB). SQLite's query planner handles small tables well without `ANALYZE`. Auto-vacuum could be enabled as a pragma, but the current approach of periodic DELETEs with retention cleanup is sufficient.

**Recommendation:** Consider adding `PRAGMA auto_vacuum = INCREMENTAL` in `_set_pragmas()` and running `PRAGMA incremental_vacuum` alongside retention cleanup. Low priority.

### DB-006: Migration 003 table rebuild without explicit transaction
**File:** `src/hassette/migrations/versions/003_nullable_fk_for_cleanup.py:19-77`

**Issue:** Migration 003 rebuilds both `handler_invocations` and `job_executions` via rename-create-copy-drop. Alembic wraps migrations in a transaction (`context.begin_transaction()` in `env.py:17`), so this is safe. However, if the migration were ever run outside Alembic (e.g., manual SQL), the lack of explicit `BEGIN`/`COMMIT` could leave the database in an inconsistent state.

**Impact:** Theoretical only. All migrations run through Alembic's `command.upgrade(config, "head")` which handles transactions.

**Recommendation:** Document that migrations must always run through Alembic. No code change needed.

### DB-007: `get_recent_errors` returns untyped `list[dict]`
**File:** `src/hassette/core/telemetry_query_service.py:382-473`

**Issue:** `get_recent_errors()` returns `list[dict]` instead of typed Pydantic models. The caller in `telemetry.py:232-259` manually extracts fields with `.get()` and default values, which is fragile.

**Impact:** No runtime risk — the query columns are well-defined and stable. This is a code quality / maintainability concern.

**Recommendation:** Define a `RecentError` Pydantic model (similar to `HandlerInvocation` / `JobExecution`) and return typed objects. Low priority.

---

## Not Applicable / Non-Issues

The following common database audit concerns do not apply to this codebase:

- **SQL injection**: All queries use parameterized `?` placeholders. The f-string SQL patterns in `TelemetryQueryService` interpolate only static clause fragments, never user input.
- **Connection pooling**: Not applicable. SQLite is an embedded database with a single connection. The single-writer queue provides explicit write serialization.
- **Missing indexes**: Comprehensive indexes exist on all high-cardinality tables covering the primary query patterns.
- **Unbounded queries**: All list endpoints have `LIMIT` parameters (default 50, max 500 enforced by FastAPI `Query(ge=1, le=500)`).
- **Missing foreign keys**: FK constraints exist with appropriate `ON DELETE SET NULL` for history preservation.
- **Missing timestamps**: All tables have timestamp columns (`started_at`, `execution_start_ts`, `first_registered_at`, `last_registered_at`).
- **N+1 in loops**: No queries execute inside Python loops. The `gather_all_listeners` function uses `asyncio.gather` for parallel execution (see DB-002 for the scaling note).
- **Transaction boundaries**: Writes are properly committed after each operation. Batch inserts in `_do_persist_batch` use a single `commit()` for the entire batch.
- **Data loss migrations**: Migration 003's table rebuild preserves all existing data via `INSERT INTO ... SELECT * FROM`. The downgrade path correctly filters out NULL parent IDs that would violate the restored NOT NULL constraint.

## Recommendations (Priority Order)

1. **Monitor dashboard query latency** if app count grows beyond 30 — DB-002 and DB-003 would be the first bottlenecks.
2. **Add `CHECK` constraints** on status columns in a future migration (DB-004) — low effort, improves data integrity.
3. **Consider `auto_vacuum`** pragma (DB-005) — prevents slow disk space growth over months of operation.
4. **Type the `get_recent_errors` return** (DB-007) — improves maintainability with minimal effort.
5. **Accept DB-001 as-is** unless the project moves to a multi-user deployment model.
