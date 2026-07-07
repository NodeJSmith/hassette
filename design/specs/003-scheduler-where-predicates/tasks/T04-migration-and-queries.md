---
task_id: "T04"
title: "Add database migration 009.sql, update telemetry queries, and add skipped to models"
status: "done"
depends_on: ["T01"]
implements: ["FR#12", "FR#13", "FR#14", "AC#7", "AC#8"]
---

## Summary
Create the database migration that adds `predicate_description`/`human_description` columns to `scheduled_jobs` and modifies the `executions.status` CHECK constraint to allow `'skipped'`. Update the SQL aggregation queries and Pydantic telemetry models to include the `skipped` count and predicate description fields. Regenerate the OpenAPI spec and frontend types. Unit tests for model fields and query correctness.

## Target Files
- create: `src/hassette/migrations_sql/009.sql`
- modify: `src/hassette/core/telemetry/registration_queries.py`
- modify: `src/hassette/core/telemetry/summary_queries.py`
- modify: `src/hassette/schemas/telemetry_models.py`
- read: `src/hassette/migrations_sql/001.sql` (reference for executions table schema and indexes)
- read: `src/hassette/migrations_sql/005.sql` (reference for table recreation pattern if any)
- read: `src/hassette/core/telemetry/registration_queries.py` (reference for listener summary pattern)
- modify: `tests/unit/test_telemetry_models.py`
- modify: `tests/unit/core/test_telemetry_models.py`
- read: `design/specs/003-scheduler-where-predicates/design.md`

## Prompt
Create the migration and update telemetry infrastructure:

**1. Create `src/hassette/migrations_sql/009.sql`:**

Three changes in a single migration file:

**Part A — Add columns to `scheduled_jobs`:**
```sql
ALTER TABLE scheduled_jobs ADD COLUMN predicate_description TEXT;
ALTER TABLE scheduled_jobs ADD COLUMN human_description TEXT;
```

**Part B — Modify `executions.status` CHECK constraint:**
SQLite does not support `ALTER CONSTRAINT`. Requires table recreation:
1. `CREATE TABLE executions_new (...)` — copy the full schema from `001.sql` (lines 82-108) but change the CHECK to `status IN ('success', 'error', 'cancelled', 'timed_out', 'skipped')`. Also include any columns added by migrations 002-008 (check each migration for `ALTER TABLE executions ADD COLUMN`).
2. `INSERT INTO executions_new SELECT * FROM executions;`
3. `DROP TABLE executions;`
4. `ALTER TABLE executions_new RENAME TO executions;`
5. Recreate ALL indexes from `001.sql` (lines 110-118) and any added by later migrations.

**Critical:** The `executions_new` table must include the mutual-exclusivity CHECK (`(listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1`), all foreign key references, and every column added by migrations 002-008.

Examine `001.sql` lines 82-118 for the full table + index schema to replicate, and grep for `ALTER TABLE executions` across `002.sql`-`008.sql` to find any additional columns.

**2. `src/hassette/core/telemetry/registration_queries.py`:**
- In `get_job_summary()` (line 117), add to the SELECT list:
  - `sj.predicate_description,` and `sj.human_description,` — mirroring `get_listener_summary()`'s `l.predicate_description, l.human_description` at lines 80-81.
  - `SUM(CASE WHEN e.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,` — add alongside the existing `successful`/`failed`/`cancelled`/`timed_out` buckets.

**3. `src/hassette/core/telemetry/summary_queries.py`:**
- In `get_app_health_aggregates()`, update the `job_avg_duration_ms` computation (line 83) to exclude skipped executions:
  ```sql
  AVG(CASE WHEN e.kind = 'job' AND e.status != 'skipped' THEN e.duration_ms END) AS job_avg_duration_ms
  ```
- Check for any other `AVG`/`MIN`/`MAX` duration aggregations in this file and apply the same `status != 'skipped'` exclusion.

**3b. `src/hassette/core/telemetry/registration_queries.py` — per-job duration aggregations:**
- In `get_job_summary()` (line 117), the `AVG(e.duration_ms)`, `MIN(e.duration_ms)`, and `MAX(e.duration_ms)` aggregations (lines ~188-191) also need `status != 'skipped'` exclusion — otherwise zero-duration skip records distort the per-job averages/min/max. Use `CASE WHEN` wrappers: `AVG(CASE WHEN e.status != 'skipped' THEN e.duration_ms END)`, etc.
- Note: this is a different file from the `get_app_health_aggregates()` fix above — `get_job_summary()` lives in `registration_queries.py`, not `summary_queries.py`.

**4. `src/hassette/schemas/telemetry_models.py`:**
- Add `skipped: int = 0` to `JobSummary` (after `timed_out`, around line 168). Follow the same pattern as `timed_out: int = 0`.
- Add `predicate_description: str | None = None` and `human_description: str | None = None` to `JobSummary`. Place them near the other registration-level fields.
- Update the `JobSummary` class docstring invariant from `successful + failed + cancelled + timed_out == total_executions` to include `+ skipped`.

**5. Schema regeneration:**
Run `uv run python scripts/export_schemas.py --types` to regenerate `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts`.

**6. Tests:**
- In `tests/unit/test_telemetry_models.py` and `tests/unit/core/test_telemetry_models.py`: add a test for the `skipped` field on `JobSummary` (follow the precedent of `test_job_summary_cancelled_field_present`).
- Add a test verifying the invariant `successful + failed + cancelled + timed_out + skipped == total_executions` holds when `skipped > 0`.

## Focus
- The `executions` table recreation is the riskiest part of this migration. Read `001.sql` lines 82-118 carefully and replicate the FULL schema. Also check each migration 002-008 for `ALTER TABLE executions ADD COLUMN` — any columns added there must be included in the new table.
- The table recreation must use `INSERT INTO executions_new SELECT * FROM executions` — column order must match exactly. List all columns explicitly in both the CREATE and INSERT to be safe.
- The `idx_exec_*` indexes (lines 110-118 of 001.sql) must be recreated after the rename because `DROP TABLE` drops associated indexes.
- Gap found: `tests/unit/test_telemetry_models.py` and `tests/unit/core/test_telemetry_models.py` both unit-test `JobSummary` fields. The precedent test `test_job_summary_cancelled_field_present` shows the exact pattern to follow for a `skipped` field test.
- `get_listener_summary()` in `registration_queries.py` (line 23) already selects `l.predicate_description, l.human_description` (lines 80-81) — use this as the exact pattern for the job summary query.

## Verify
- [ ] FR#12: Migration 009.sql adds `'skipped'` to the `executions.status` CHECK constraint via table recreation
- [ ] FR#13: `JobSummary` model has a `skipped: int = 0` field
- [ ] FR#14: `total_executions` includes skipped records (COUNT includes all rows; invariant updated in docstring)
- [ ] AC#7: `JobSummary` includes `predicate_description` and `human_description` fields (frontend display is T05)
- [ ] AC#8: Tests verify `successful + failed + cancelled + timed_out + skipped == total_executions`
