---
task_id: "T05"
title: "Add composite indexes for status-filtered queries"
status: "planned"
depends_on: []
implements: ["FR#6", "AC#6"]
---

## Summary
Create migration `010_perf_indexes.py` adding two composite indexes that support the status-filtered lookup patterns used by handler and job summary queries. These indexes cover the `WHERE status IN ('error', 'timed_out')` filter combined with the `listener_id`/`job_id` partition and `execution_start_ts` ordering used by the ROW_NUMBER() CTEs.

## Prompt
1. **Create `src/hassette/migrations/versions/010_perf_indexes.py`:**
   ```python
   """Add composite indexes for status-filtered handler and job queries.

   Supports the ROW_NUMBER() CTE pattern used by get_listener_summary,
   get_job_summary, and get_all_jobs_summary for last-error lookups.

   Revision ID: 010
   Revises: 009
   """

   from alembic import op

   revision = "010"
   down_revision = "009"
   branch_labels = None
   depends_on = None

   def upgrade() -> None:
       op.execute(
           "CREATE INDEX idx_hi_listener_status_time "
           "ON handler_invocations(listener_id, status, execution_start_ts DESC)"
       )
       op.execute(
           "CREATE INDEX idx_je_job_status_time "
           "ON job_executions(job_id, status, execution_start_ts DESC)"
       )

   def downgrade() -> None:
       op.execute("DROP INDEX IF EXISTS idx_je_job_status_time")
       op.execute("DROP INDEX IF EXISTS idx_hi_listener_status_time")
   ```

2. **Verify the migration integrates correctly** — check that the migration runner in `src/hassette/core/database_service.py` picks up the new file and that the version check increments properly.

## Focus
- Follow the convention from `009_log_records_table.py`: docstring, revision as simple numeric string, `down_revision` pointing to previous, `IF EXISTS` in downgrade.
- Index naming convention: `idx_` prefix + table abbreviation + column names. `idx_hi_` for handler_invocations, `idx_je_` for job_executions.
- The existing `idx_hi_listener_time` covers `(listener_id, execution_start_ts DESC)` but does NOT include `status`. The new index adds the status column needed for the `WHERE status IN (...)` filter in the ROW_NUMBER() CTE.
- This is additive — no data changes, fully reversible. SQLite builds indexes from existing rows on upgrade.

## Verify
- [ ] FR#6: Migration `010_perf_indexes.py` exists with `idx_hi_listener_status_time` on `handler_invocations(listener_id, status, execution_start_ts DESC)` and `idx_je_job_status_time` on `job_executions(job_id, status, execution_start_ts DESC)`
- [ ] AC#6: Both indexes are created on upgrade and dropped on downgrade; migration revision chain is `009` → `010`
