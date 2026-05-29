---
task_id: "T02"
title: "Replace Alembic with PRAGMA user_version migration runner"
status: "planned"
depends_on: ["T01"]
implements: ["FR#7", "FR#8", "FR#9", "FR#17", "AC#4", "AC#8", "AC#11"]
---

## Summary
Replace the Alembic migration infrastructure with a ~35-line `PRAGMA user_version` runner. Delete the `src/hassette/migrations/` directory (14 files), `alembic.ini`, and Alembic/SQLAlchemy/Mako dependencies. Write the new runner and `migrations/001.sql` with the unified schema DDL.

## Prompt
**Step 1: Write the migration runner** (~35 lines) in a new module (e.g., `src/hassette/core/migration_runner.py`). The runner:
1. If fresh database (`user_version = 0`): opens a raw `sqlite3.Connection`, checks/sets `auto_vacuum = INCREMENTAL`, closes it. PRAGMA auto_vacuum cannot be set inside a transaction — the separate connection ensures no transaction is active. First-run only.
2. Reads `PRAGMA user_version`
3. Iterates sorted `.sql` files from `current_version + 1` to target
4. Each migration runs inside `BEGIN IMMEDIATE` / `COMMIT` with `PRAGMA user_version = N` as the final statement inside the transaction

Follow the `_source_tier_clause` convention for helper functions (see Convention Examples in context.md).

**Step 2: Write `migrations/001.sql`** with the unified schema DDL. Tables:
- `sessions` — carry over from current schema, but DROP the `dropped_no_session` column
- `listeners` — carry over, but update unique index to `(owner_key, instance_index, name, topic)` (no `WHERE once = 0` filter, no `handler_method` in key, no `COALESCE` fallback). `name` is `NOT NULL`.
- `scheduled_jobs` — carry over unchanged (natural key `owner_key, instance_index, job_name` already name-based)
- `executions` — unified table with: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `kind TEXT NOT NULL CHECK (kind IN ('handler', 'job'))`, `listener_id INTEGER REFERENCES listeners(id) ON DELETE SET NULL`, `job_id INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL`, `CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)`, `session_id`, `execution_start_ts`, `duration_ms`, `status`, `error_type`, `error_message`, `error_traceback`, `is_di_failure`, `source_tier`, `execution_id TEXT UNIQUE`, `trigger_context_id`, `trigger_origin` (nullable — handler-only). New columns: `trigger_mode TEXT` (nullable), `retry_count INTEGER NOT NULL DEFAULT 0`, `attempt_number INTEGER NOT NULL DEFAULT 1`, `args_json TEXT NOT NULL DEFAULT '[]'`, `kwargs_json TEXT NOT NULL DEFAULT '{}'`.
- `log_records` — carry over unchanged
- 6 indexes on executions (see design doc Architecture > Schema > Index plan)

**Step 3: Rewrite `database_service.py`** — replace `_get_expected_head_revision()`, `_get_current_db_revision()`, `_run_migrations()` to use the new runner. Integer comparison replaces string comparison in `_handle_schema_version()`. Delete Alembic imports (5).

**Step 4: Delete** `src/hassette/migrations/` (14 files), `alembic.ini`.

**Step 5: Remove dependencies** from `pyproject.toml` — remove `alembic>=1.13`. SQLAlchemy and Mako disappear as transitive deps.

**Step 6: Write unit tests** for the migration runner:
- Test: applies migrations in order and sets version atomically
- Test: simulated crash mid-migration leaves DB at previous version
- Test: new columns exist in schema after 001 applies
- Test: kind CHECK rejects invalid values

## Focus
- The `auto_vacuum` step MUST use a separate raw `sqlite3.Connection` — SQLite cannot set auto_vacuum inside a transaction.
- Existing `_handle_schema_version()` mismatch logic must survive — integer comparison instead of string.
- `_RETENTION_TABLES` in `database_service.py` must be updated: reduce from 3 entries to 2 (`log_records`, `executions`).
- Parent-guard DELETE queries for retired listeners/jobs must reference `executions` instead of `handler_invocations`/`job_executions`.
- The `session_manager.py` UPDATE statement references `dropped_no_session` — the column no longer exists in the new schema. T04 Step 7 owns this removal; note it here as a dependency, not an action for this task.
- No other Python file imports `alembic` or `sqlalchemy` — the removal is contained.

## Verify
- [ ] FR#7: Migration runner uses `PRAGMA user_version` for version tracking
- [ ] FR#8: `alembic` is not in `pyproject.toml` dependencies; `import alembic` fails
- [ ] FR#9: A test simulating crash mid-migration leaves DB at previous version
- [ ] AC#4: Running migrations on a fresh DB produces the expected schema (unified `executions` table, `PRAGMA user_version` set, no `alembic_version` table)
- [ ] AC#8: `pip show alembic` returns "not found" after `uv sync`
- [ ] FR#17: `CHECK (kind IN ('handler', 'job'))` constraint exists in 001.sql DDL
- [ ] AC#11: Unit test confirms invalid kind values are rejected at the SQL level
