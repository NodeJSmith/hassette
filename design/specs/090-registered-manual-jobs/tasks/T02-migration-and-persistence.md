---
task_id: "T02"
title: "Add migration 012 and update persistence layer"
status: "done"
depends_on: ["T01"]
implements: ["FR#23", "AC#6"]
---

## Summary

Write the SQLite migration `012.sql` that renames `cancelled_at` to `removed_at` on both `scheduled_jobs` and `listeners`, extends the `trigger_type` CHECK constraint with `manual`, adds `schedule_status` (NOT NULL, CHECK-constrained) and nullable `schedule_status_reason` (CHECK-constrained) columns, and backfills legacy rows. Update all persistence code that references the old column names and methods.

## Target Files

- create: `src/hassette/migrations_sql/012.sql`
- modify: `src/hassette/core/telemetry/repository.py`
- modify: `src/hassette/core/telemetry/registration_queries.py`
- modify: `src/hassette/core/telemetry/summary_queries.py`
- modify: `src/hassette/core/registration.py`
- modify: `src/hassette/core/migration_runner.py`
- modify: `src/hassette/core/database_service.py`
- modify: `src/hassette/core/scheduler_service.py`
- modify: `src/hassette/core/bus_service.py`
- modify: `src/hassette/bus/bus.py`
- modify: `src/hassette/bus/options.py`
- modify: `src/hassette/core/command_executor.py`
- read: `src/hassette/migrations_sql/001.sql`
- read: `src/hassette/migrations_sql/009.sql`
- read: `design/specs/090-registered-manual-jobs/design.md` (Migration, Persistence And Queries)
- create: `tests/unit/test_migration_012.py`
- modify: `tests/unit/test_migration_002.py`
- modify: `tests/integration/database/`

## Prompt

**Write migration `012.sql`:**

This is the first migration in the project's history to rebuild an FK-parent table. `scheduled_jobs` is referenced by `executions.job_id REFERENCES scheduled_jobs(id) ON DELETE SET NULL`.

Follow the drop-and-rebuild pattern from `009.sql` but with extra care:

1. Rename `listeners.cancelled_at` → `removed_at` using `ALTER TABLE listeners RENAME COLUMN cancelled_at TO removed_at`.
2. For `scheduled_jobs` (FK parent, requires rebuild):
   - Create `scheduled_jobs_new` with the updated schema: `cancelled_at` renamed to `removed_at`, `trigger_type` CHECK extended with `'manual'`, new `schedule_status TEXT NOT NULL CHECK (schedule_status IN ('scheduled', 'waiting', 'completed', 'manual'))`, new `schedule_status_reason TEXT CHECK (schedule_status_reason IN ('legacy_unknown', 'trigger_error') OR schedule_status_reason IS NULL)`.
   - `INSERT INTO scheduled_jobs_new SELECT *, 'scheduled' AS schedule_status, 'legacy_unknown' AS schedule_status_reason FROM scheduled_jobs` — **explicitly enumerate and preserve `id`** in the column list so `executions.job_id` references are not broken.
   - Drop old table, rename new.
   - Rebuild indexes and views (`active_scheduled_jobs`, `active_framework_scheduled_jobs`, `active_app_scheduled_jobs`). These views currently filter only on `retired_at IS NULL` (not `cancelled_at`) — add `AND removed_at IS NULL` to each so removed jobs are excluded from active lists per the design's dual-column filter requirement.
3. Update `active_listeners`, `active_framework_listeners`, `active_app_listeners` views — same pattern: they currently filter on `retired_at IS NULL`, add `AND removed_at IS NULL`.

**Update persistence code:**

- `repository.py`: rename `mark_job_cancelled()` → `mark_job_removed()`, update all `cancelled_at` references to `removed_at`.
- `command_executor.py`: rename `CommandExecutor.mark_job_cancelled()` → `mark_job_removed()` (this method delegates to `self.repository.mark_job_cancelled(db_id)` — the call site must match the repository rename).
- `scheduler_service.py`: rename `SchedulerService.mark_job_cancelled()` → `mark_job_removed()` (this method delegates to `self._executor.mark_job_cancelled` and must structurally satisfy the renamed `SchedulerServiceProtocol`). The `register_job()` upsert's `ON CONFLICT DO UPDATE SET` must explicitly include `schedule_status = excluded.schedule_status, schedule_status_reason = excluded.schedule_status_reason` alongside the existing `cancelled_at = NULL` → `removed_at = NULL` clearing.
- `registration_queries.py`: update `cancelled_at` → `removed_at` in all queries. Add `retired_at IS NULL` to `get_job_summary()` active-job filter (currently only checks `cancelled_at IS NULL`).
- `summary_queries.py`: same column rename.
- `registration.py`: rename `cancelled_at` field references on `ListenerRegistration`. Add `schedule_status: str` and `schedule_status_reason: str | None` fields to `ScheduledJobRegistration` — these are required because the migration adds `schedule_status TEXT NOT NULL` with no DEFAULT. Thread the new fields through to the `register_job()` INSERT column/VALUES list in `repository.py`, and through the `ON CONFLICT DO UPDATE SET` clause (already specified above).
- `database_service.py`: verify retention queries — these use `retired_at` only (not `cancelled_at`), so they likely need no changes, but confirm by reading the file.
- `bus_service.py`: update `mark_listener_cancelled` references.
- `bus.py`: update `cancelled_at` references.
- `bus/options.py`: update docstring referencing `cancelled_at`.
- `command_executor.py`: update `reconcile_registrations()` references.

**Write migration tests** in `tests/unit/test_migration_012.py`:
- Verify `id` preservation: create a pre-migration DB with known scheduled_jobs rows and executions referencing them, run migration, verify `PRAGMA foreign_key_check` passes and `executions.job_id` still resolves.
- Verify `cancelled_at` timestamp values are preserved as `removed_at`.
- Verify legacy backfill: all existing rows have `schedule_status='scheduled'` and `schedule_status_reason='legacy_unknown'`.
- Verify removed legacy rows (`removed_at IS NOT NULL`) are excluded from active views.
- Verify re-registration clears `legacy_unknown`: after upserting with `schedule_status='manual', schedule_status_reason=NULL`, confirm the reason is cleared.
- Verify CHECK constraints reject invalid `schedule_status` and `schedule_status_reason` values.
- Verify `trigger_type='manual'` is now accepted.

See design doc: Migration, Persistence And Queries.

## Focus

- **FK-parent rebuild is the critical path.** Migration `009.sql` rebuilt the FK child (`executions`). This migration rebuilds the FK parent (`scheduled_jobs`). If `id` values are not preserved, every historical execution row's `job_id` silently points at the wrong row. `migration_runner.py` uses bare `sqlite3.connect()` with no `PRAGMA foreign_keys` — SQLite will not raise on broken FKs at migration time.
- The column names in `repository.py` upserts are enumerated explicitly — every `cancelled_at` reference must be found. Use grep to be thorough: `grep -rn 'cancelled_at' src/hassette/`.
- `database_service.py:622-639` has retention queries using `retired_at` only — verify no `cancelled_at` references exist there (they don't in current code).
- `bus.py:415` has a comment mentioning `cancelled_at` — update the comment.
- `scripts/seed_db.py` also constructs `cancelled_at` params — that's covered in T08 (tooling), not here.

## Verify

- [ ] FR#23: `scheduled_jobs` and `listeners` tables have `removed_at` column, no `cancelled_at`. `mark_job_removed()` exists in the repository.
- [ ] AC#6: Migration test with pre-existing data passes `PRAGMA foreign_key_check`. Legacy rows have `schedule_status='scheduled'` and `schedule_status_reason='legacy_unknown'`. Re-registration clears `legacy_unknown`. CHECK constraints reject invalid values.
