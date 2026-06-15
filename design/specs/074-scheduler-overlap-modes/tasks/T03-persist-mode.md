---
task_id: "T03"
title: "Persist scheduled-job mode to the database"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#10", "AC#10"]
---

## Summary

Persist each job's resolved mode to a new `scheduled_jobs.mode` column for display/telemetry. The
job-side persistence chain is entirely net-new (unlike `listeners`, which already has it): add the
migration, the registration field, the construction-site thread-through, the upsert columns, and
select the column in the job summary query. App code stays authoritative — the column is written
from the in-memory job, never read back to reconstruct the guard.

## Prompt

Implement design.md "Architecture §5 (Persistence)". Mirror the listener pattern, but note every
piece is absent on the job side today.

1. **`src/hassette/migrations_sql/004.sql`** (new file): exactly the shape of `003.sql` but for the
   jobs table:
   ```sql
   ALTER TABLE scheduled_jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'single'
       CHECK (mode IN ('single', 'restart', 'queued', 'parallel'));
   ```

2. **`src/hassette/core/registration.py` — `ScheduledJobRegistration`** (line 69): add
   `mode: str = "single"` with a docstring mirroring `ListenerRegistration.mode` (line 63). No such
   field exists today.

3. **`src/hassette/core/scheduler_service.py` — `add_job`** (the `ScheduledJobRegistration(...)`
   construction at line ~259): pass `mode=job.mode.value`. Do NOT rely on the dataclass default —
   that would silently persist every job as `single`.

4. **`src/hassette/core/telemetry_repository.py` — `register_job`** (the upsert at line 327): add
   `mode` to ALL THREE places — the INSERT column list, the `VALUES` named params (`:mode` →
   `registration.mode`), and the `ON CONFLICT DO UPDATE SET` list (`mode = excluded.mode`). Follow
   the `"group"`/`name_auto` handling, but note both `mode` and the dataclass field are absent today
   (unlike `group`, which is already wired).

5. **Job summary query**: in `src/hassette/core/telemetry/registration_queries.py`, the
   `get_all_jobs_summary` (line ~167) and `get_job_summary` (line ~240) functions build the
   `JobSummary` — select the new `mode` column there so it flows to the model. (These functions live
   in `registration_queries.py`, NOT `telemetry_repository.py`.) The `JobSummary` field itself and
   the API surface are T05; this task ensures the column is queried.

6. **Tests (same task).** A memory→DB persistence test (FR#10/AC#10): register a job with
   `mode="queued"`, assert `scheduled_jobs.mode == 'queued'`. Do NOT assert a DB→guard
   reconstruction — none exists. Adapt migration/schema tests that snapshot `scheduled_jobs` columns
   or assert the migration set (see Focus) to include `004.sql`/the new column.

Do NOT add the `JobSummary` model fields or web/frontend surfacing — that is T05.

## Focus

- Migration files live in `src/hassette/migrations_sql/`; only `001`–`003` exist. `003.sql` is the
  exact pattern (a 2-line ALTER). The migration runner applies files in order at startup before any
  code writes — confirm `004.sql` is picked up (check `test_migration_runner.py` for how the runner
  enumerates files).
- The `register_job` upsert (`telemetry_repository.py:327-400`) uses named params and
  `ON CONFLICT(app_key, instance_index, job_name) DO UPDATE SET ...`. The `register_listener` upsert
  in the same file already includes `mode` — use it as the reference for the three insertion points.
- `add_job` builds `ScheduledJobRegistration` at `scheduler_service.py:259-274`; `job.mode` is an
  `ExecutionMode` (added in T01), so persist `job.mode.value` (the string).
- The job summary query that constructs `JobSummary`: search the telemetry query layer
  (`src/hassette/core/telemetry/registration_queries.py` and/or `telemetry_repository.py`
  `get_all_jobs_summary`/`get_job_summary`). The SELECT must include `mode`.
- Migration/schema tests to check/adapt (reverse-dep gap): `tests/unit/test_schema_migration.py`,
  `tests/unit/core/test_migration_runner.py`, `tests/unit/test_migration_002.py`,
  `tests/unit/core/conftest.py`, `tests/unit/core/test_telemetry_repository.py`,
  `tests/integration/test_registration.py`. Any that assert the `scheduled_jobs` column set or the
  migration count need the new column/file.
- App code is authoritative for mode (design Key Decision 9): on restart the app re-registers and
  the upsert overwrites the column. The column is display/telemetry only.

## Verify

- [ ] FR#10: registering a job persists its resolved mode to `scheduled_jobs.mode` via the `register_job` upsert; the column is added by `004.sql` with a CHECK constraint and `DEFAULT 'single'`.
- [ ] AC#10: registering with `mode="queued"` writes `'queued'` to `scheduled_jobs.mode` (memory→DB); no DB→guard reconstruction is asserted.
