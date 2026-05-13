---
task_id: "T04"
title: "Add log_records table with retention and persistence"
status: "done"
depends_on: ["T03"]
implements: ["FR#10", "FR#11", "FR#12", "FR#13", "AC#6", "AC#9", "AC#11", "AC#14"]
---

## Summary
Create the `log_records` database table, repository methods, retention integration, and wire the LogPersistenceHandler to the database. After this task, log records are persisted to SQLite, aged out by `log_retention_days`, and included in the size failsafe. The REST API and frontend are not touched — those come in T05-T07.

## Prompt
1. Create Alembic migration `src/hassette/migrations/versions/009_log_records_table.py`:
   ```sql
   CREATE TABLE log_records (
       id              INTEGER PRIMARY KEY AUTOINCREMENT,
       seq             INTEGER NOT NULL,
       timestamp       REAL NOT NULL,
       level           TEXT NOT NULL,
       logger_name     TEXT NOT NULL,
       func_name       TEXT,
       lineno          INTEGER,
       message         TEXT NOT NULL,
       exc_info        TEXT,
       app_key         TEXT,
       instance_name   TEXT,
       instance_index  INTEGER,
       execution_id    TEXT,
       source_tier     TEXT
   );
   CREATE INDEX idx_lr_time ON log_records(timestamp);
   CREATE INDEX idx_lr_exec ON log_records(execution_id) WHERE execution_id IS NOT NULL;
   CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp);
   ```
   Follow the pattern in `008_job_name_auto_column.py`: `revision = "009"`, `down_revision = "008"`.

2. Add a Pydantic model for log records in `src/hassette/core/telemetry_models.py`:
   - `LogRecord` with fields matching the DB schema
   - Follow the pattern of `HandlerInvocation` (line 99) for field naming

3. Add repository methods in `src/hassette/core/telemetry_repository.py`:
   - `insert_log_records(db: aiosqlite.Connection, records: list[dict])` — batch INSERT using `executemany`
   - `get_log_records(db, *, limit=100, since=None, app_key=None, level=None, execution_id=None, source_tier=None)` — paginated query with optional filters, ordered by timestamp DESC
   - `get_log_records_by_execution(db, execution_id: str, *, limit=500)` — all records for one execution, ordered by seq ASC. Returns `(records, truncated)` tuple where `truncated=True` when `count > limit`.
   - Follow existing patterns in the file for SQL construction and parameter binding.

4. Add config fields in `src/hassette/config/config.py`:
   - `log_retention_days: int = Field(default=3, ge=1)`
   - `log_persistence_level: LOG_ANNOTATION = Field(default="INFO")`
   - Add a Pydantic `model_validator` constraining `log_retention_days <= db_retention_days`

5. Extend `_do_run_retention_cleanup()` in `src/hassette/core/database_service.py` (around line 525):
   - Add deletion of `log_records` where `timestamp < log_retention_cutoff` (using `log_retention_days`, which may differ from `db_retention_days`)
   - Log the count of deleted log records alongside the existing invocation/execution counts

6. Extend `_check_size_failsafe()` in `src/hassette/core/database_service.py` (around line 590):
   - Add a dedicated pre-pass loop that deletes from `log_records` only (oldest-first, same `_SIZE_FAILSAFE_DELETE_BATCH` constant) until the DB is under the size limit
   - Re-check DB size after the pre-pass
   - Only if still over the limit does it enter the existing execution-record loop

7. Wire `LogPersistenceHandler.set_database()` from `RuntimeQueryService.on_initialize()` in `src/hassette/core/runtime_query_service.py`:
   - After the existing `handler.set_broadcast(self.broadcast, loop)` call (around line 135), call `persistence_handler.set_database(self._database_service, loop)`
   - Get the persistence handler reference via a new `get_log_persistence_handler()` function in `logging_.py` (following the `get_log_capture_handler()` pattern)

8. Expose `log_records_dropped` counter in the system status response:
   - Add the `LogPersistenceHandler.dropped_count` to the existing drop counter mechanism in `CommandExecutor.get_drop_counters()` or create a parallel accessor

9. Write unit tests:
   - Migration 009 creates table and indexes
   - `insert_log_records()` writes records and they're queryable
   - `get_log_records()` filters by app_key, level, execution_id, since
   - `get_log_records_by_execution()` returns ordered records with truncated flag
   - Retention cleanup deletes log_records older than log_retention_days
   - Size failsafe pre-pass deletes log_records before execution records
   - Validator rejects `log_retention_days > db_retention_days`

## Focus
- Migration pattern: `008_job_name_auto_column.py` uses `op.add_column()`. For a new table, use `op.create_table()` or raw `op.execute()` following `001_initial_schema.py`.
- `_do_run_retention_cleanup()` at `database_service.py:525-579` uses `await self.db.execute(...)` with parameterized SQL. Follow the same pattern for log_records.
- `_check_size_failsafe()` at `database_service.py:590-658` uses `_SIZE_FAILSAFE_DELETE_BATCH = 1000` and `_SIZE_FAILSAFE_MAX_ITERATIONS = 100`. The pre-pass for log_records should use the same constants.
- `RuntimeQueryService.on_initialize()` at `runtime_query_service.py:96-141` is where late-wiring happens. The `handler = get_log_capture_handler()` call at line 133 gets the capture handler. Add a parallel `get_log_persistence_handler()` call.
- `telemetry_repository.py` functions take `db: aiosqlite.Connection` as the first argument and are called via `DatabaseService.submit(repo_fn(self.db, ...))`.

## Verify
- [ ] FR#10: Log records are persisted with all specified fields (timestamp, level, logger_name, func_name, lineno, message, exc_info, app_key, instance_name, instance_index, execution_id, source_tier)
- [ ] FR#11: Records below log_persistence_level are not written to the database
- [ ] FR#12: Records older than log_retention_days are deleted during retention cleanup
- [ ] FR#13: Size failsafe deletes log_records first (pre-pass) before execution records
- [ ] AC#6: After a simulated restart (new DB connection), previously-persisted records are queryable
- [ ] AC#9: Setting log_retention_days=1 and triggering cleanup deletes old log records
- [ ] AC#11: DEBUG logs are absent from DB when log_persistence_level=INFO
- [ ] AC#14: Size failsafe deletes log_records oldest-first when DB approaches size limit
