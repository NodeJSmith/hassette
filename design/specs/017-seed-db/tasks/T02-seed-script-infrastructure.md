---
task_id: "T02"
title: "Create seed script with SeedContext and integrity checks"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "FR#9", "FR#10"]
---

## Summary

Create `scripts/seed_db.py` — the standalone seed script with argparse CLI, SeedContext class for cross-table ID bookkeeping, sync insert helper, and all integrity checks (FK enforcement, consistency assertions, transaction wrapping, atomic file swap). Includes the scenario registry dict but not the scenario generators themselves (those are T03). The `empty` scenario is implemented here as the trivial baseline (schema only, zero rows).

## Target Files

- create: `scripts/seed_db.py`
- read: `src/hassette/core/migration_runner.py`
- read: `src/hassette/core/telemetry/repository.py`
- read: `src/hassette/core/database_service.py`
- read: `src/hassette/core/execution_record.py`
- read: `src/hassette/core/registration.py`
- read: `scripts/export_schemas.py`

## Prompt

Create `scripts/seed_db.py` following the convention from `scripts/export_schemas.py` (module docstring with Usage section, argparse in `def main()`, `if __name__ == "__main__": main()` guard).

### CLI interface

- `--scenario <name>` (required): selects which scenario to generate. Valid names: `healthy`, `empty`, `degraded`, `error`, `large-volume`, `lifecycle`, `adversarial`.
- `--output <path>` (optional): where to write the SQLite file. Default: `./hassette-{scenario}.db` in the current directory.
- Print a summary after generation: app count, listener count, job count, execution count, log record count, blocking event count.

### SeedContext class

A `@dataclass` that owns cross-table ID bookkeeping. See `design/specs/017-seed-db/design.md` (Architecture § "SeedContext") for the full shape. Key fields:

```python
@dataclass
class SeedContext:
    cursor: sqlite3.Cursor
    session_ids: list[int]
    listener_ids: dict[tuple[str, int, str], int]  # (app_key, instance_index, name) -> db_id
    job_ids: dict[tuple[str, int, str], int]  # (app_key, instance_index, job_name) -> db_id
    execution_ids: list[str]
```

Methods: `add_session()`, `add_listener()`, `add_job()`, `add_execution()`, `add_log_record()`, `add_blocking_event()`. Each method:
1. Builds the INSERT params using the param builder functions from T01 (for listeners/jobs/executions) or direct dict construction (for sessions/log_records/blocking_events)
2. Executes via `insert_row(cursor, sql, params)` helper
3. Tracks the returned ID in the appropriate dict/list

### insert_row helper

```python
def insert_row(cursor: sqlite3.Cursor, sql: str, params: dict[str, Any]) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return row[0]  # RETURNING id
```

For tables without RETURNING (log_records, blocking_events), return `cursor.lastrowid`.

### INSERT SQL strings

- Import `execution_insert_params`, `listener_insert_params`, `job_insert_params` from `hassette.core.telemetry.repository` (T01 output).
- For listeners and jobs: construct plain `INSERT INTO ... (...) VALUES (...) RETURNING id` SQL from the param dict keys. The autoincrement `id` is needed for FK references in executions. Do NOT include `ON CONFLICT` — the seed script always writes a fresh file.
- For executions: construct plain `INSERT INTO ... (...) VALUES (...)` SQL from the param dict keys. No `RETURNING` needed — the `execution_id` string (used for log/blocking correlation) is already known from the `ExecutionRecord`. Note: do NOT import `_EXECUTION_INSERT_SQL` from `repository.py` — it lacks `RETURNING` and is designed for `executemany` batch inserts.
- For log_records: import `_LOG_INSERT_SQL` from `hassette.core.database_service` (or construct from `_LOG_COLUMNS`). Note: 13 columns, not 7.
- For sessions and blocking_events: hand-write INSERT SQL matching the schema columns.

### Integrity checks

1. **PRAGMA foreign_keys = ON** immediately after `sqlite3.connect()`.
2. **Transaction**: wrap the entire scenario in `BEGIN IMMEDIATE` ... `COMMIT` with `except: conn.rollback(); raise`.
3. **Post-seed FK check**: `cursor.execute("PRAGMA foreign_key_check")` — if any rows returned, abort with an error listing the violations.
4. **Post-seed consistency assertion**: `SELECT lr.execution_id FROM log_records lr LEFT JOIN executions e ON lr.execution_id = e.execution_id WHERE lr.execution_id IS NOT NULL AND e.execution_id IS NULL` — abort if any rows. Same for `blocking_events`.
5. **Atomic swap**: generate to a temp path (`{output}.tmp`), then `os.replace(tmp_path, output_path)` only after all checks pass.

### Scenario registry

```python
SCENARIOS: dict[str, Callable[[SeedContext], None]] = {
    "healthy": scenario_healthy,
    "empty": scenario_empty,
    ...
}
```

Implement `scenario_empty` here (it does nothing — just the bare schema with zero rows). The other 6 scenarios are placeholder stubs that raise `NotImplementedError("TODO: T03")` until T03 implements them.

### Deterministic conventions

- Reference timestamp: `Instant.from_utc(2026, 1, 15, 12, 0)` (using `whenever` library).
- `execution_id` format: `f"{scenario}_{app_key}_{index:04d}"`.
- `instance_name` format: `f"{class_name}.{instance_index}"` (matching production default).

## Focus

- The migration runner is synchronous and uses stdlib `sqlite3`: `from hassette.core.migration_runner import run_migrations`. Call it with `run_migrations(db_path)` before opening the seeder's own connection.
- `_LOG_COLUMNS` has 13 columns (not 7): `seq, timestamp, level, logger_name, func_name, lineno, message, exc_info, app_key, instance_name, instance_index, execution_id, source_tier`.
- Sessions table has no dedicated param builder — read `src/hassette/migrations_sql/001.sql` (lines 1-15) for the column list.
- Blocking events table defined in `src/hassette/migrations_sql/005.sql` — read for column list. `execution_id` is nullable. `session_id` is nullable.
- Use `whenever` for timestamps, not stdlib `datetime`.

## Verify

- [ ] FR#1: `uv run python scripts/seed_db.py --scenario empty --output /tmp/test-empty.db` exits 0
- [ ] FR#2: `--output /tmp/custom-path.db` writes to the specified path
- [ ] FR#4: SeedContext tracks IDs across all 6 tables (sessions, listeners, jobs, executions, log_records, blocking_events)
- [ ] FR#5: running the script twice for `--scenario empty` produces identical database content (same rows in same order — compare at SQL level, not file bytes)
- [ ] FR#6: PRAGMA foreign_keys is ON and PRAGMA foreign_key_check runs post-seed
- [ ] FR#7: post-seed consistency assertion runs (LEFT JOIN check for log_records and blocking_events)
- [ ] FR#8: inserts are wrapped in a transaction; output file is atomically swapped
- [ ] FR#9: re-running replaces the existing file (atomic swap handles this)
- [ ] FR#10: scenario_empty uses no app keys (zero rows in all tables)
