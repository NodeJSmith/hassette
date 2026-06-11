---
task_id: "T01"
title: "Add cancelled_at column and listener cancellation write path"
status: "planned"
depends_on: []
implements: ["FR#9"]
---

## Summary
Add the durable cancellation marker for listeners, mirroring the scheduler's `cancelled_at`
mechanism. This is the persistence foundation: a new migration adds the column, the listener
upsert clears it on re-registration, and a `mark_listener_cancelled` write path is threaded
through the repository, command executor, and bus service. Later tasks call this when a
listener is replaced, cancelled, or fires (once-listeners).

## Prompt
Implement the listener cancellation persistence layer, mirroring the existing scheduled-job
mechanism exactly.

1. **Migration** — create `src/hassette/migrations_sql/002.sql` containing:
   ```sql
   ALTER TABLE listeners ADD COLUMN cancelled_at REAL;
   ```
   This bumps the schema head to 2 (the runner derives head from the highest numeric filename
   stem — see `src/hassette/core/migration_runner.py` and `database_service._get_expected_head_version`).
   Existing v1 DBs are deleted and recreated, so the `ADD COLUMN` runs against a freshly created
   `listeners` table. See the design's `## Migration` section.

2. **Repository upsert** — in `src/hassette/core/telemetry_repository.py`, `register_listener`
   (around line 300–313), add `cancelled_at = NULL` to the `ON CONFLICT ... DO UPDATE SET`
   clause, mirroring `register_job` at line 376 (`cancelled_at = NULL  -- re-registration clears cancellation`).
   This makes re-registration clear any prior cancellation while preserving the row id.

3. **Repository write method** — add `mark_listener_cancelled(self, db_id: int) -> None` to
   `TelemetryRepository`, mirroring `mark_job_cancelled` (telemetry_repository.py:403):
   `UPDATE listeners SET cancelled_at = :cancelled_at WHERE id = :id` with `time.time()`, then
   `await db.commit()`.

4. **Command executor passthrough** — add `mark_listener_cancelled(self, db_id: int) -> None`
   to `src/hassette/core/command_executor.py`, mirroring `mark_job_cancelled` (command_executor.py:574):
   delegate to `self.repository.mark_listener_cancelled(db_id)` via `self.hassette.database_service.submit(...)`.

5. **Bus service passthrough** — add `mark_listener_cancelled(self, db_id: int) -> None` to
   `src/hassette/core/bus_service.py` that delegates to `self._executor.mark_listener_cancelled(db_id)`,
   mirroring how `SchedulerService.mark_job_cancelled` (scheduler_service.py:462) delegates to its
   executor. This is the entry point the bus cancel path (T03/T04) will spawn.

Write a unit test that calls `register_listener`, then `mark_listener_cancelled`, and asserts
the row's `cancelled_at` is set; then re-registers under the same natural key and asserts
`cancelled_at` is cleared back to NULL with the row id preserved.

## Focus
- The telemetry DB is disposable: `database_service._handle_schema_version` (database_service.py:446)
  deletes any DB below head and recreates it. No data migration needed; do not write an in-place
  data-backfill.
- `register_listener` returns the row id via `RETURNING id`; do not change that.
- `mark_job_cancelled` is the precise template — match its signature, `submit`/`spawn` wiring,
  and commit behavior. The scheduler spawns the write on a service task bucket so it survives
  resource shutdown; the bus-side trigger (spawning) lands in T03/T04, but the
  `BusService.mark_listener_cancelled` method belongs here.
- Existing listener repository tests live near `tests/unit/` (search for `register_listener`);
  follow their fixture/setup style.
- Do NOT add `cancelled_at` to the active-listener views or reconciliation in this task unless
  parity with `scheduled_jobs` requires it — the existing active views filter only
  `retired_at IS NULL` (001.sql:144–149). If reconciliation must exclude cancelled rows, mirror
  exactly what `scheduled_jobs` reconciliation does and note it.

## Verify
- [ ] FR#9: `mark_listener_cancelled` (repository → command executor → bus service) sets
      `listeners.cancelled_at` for a given `db_id`, and a unit test confirms the column is set
      after the call and cleared to NULL after re-registration under the same natural key, with
      the row id unchanged. `002.sql` adds the `cancelled_at` column and the schema head becomes 2.
