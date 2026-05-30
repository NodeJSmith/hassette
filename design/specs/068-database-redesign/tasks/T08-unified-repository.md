---
task_id: "T08"
title: "Unify repository write path for executions table"
status: "done"
depends_on: ["T02", "T07"]
implements: ["FR#1", "FR#4", "AC#1"]
---

## Summary
Rewrite `telemetry_repository.py` to write to the unified `executions` table. Merge dual INSERT param builders, dual `executemany`, dual persist logic, and dual FK fallback into single-path equivalents. Update the upsert conflict target for the new listener natural key. Update reconciliation SQL.

## Prompt
**Step 1: Replace INSERT param builders** — delete `_inv_insert_params()` and `_job_insert_params()`, write a single `_execution_insert_params(record: ExecutionRecord)` following the same flat-dict convention.

**Step 2: Update `persist_batch()`** — merge the dual-list logic into a single list of `ExecutionRecord` with the appropriate `kind`, `listener_id`/`job_id` set.

**Step 3: Update `persist_batch_with_fk_fallback()` and `_insert_row_with_fk_fallback()`** — rewrite for the unified `executions` table. The FK fallback sets `listener_id=NULL` or `job_id=NULL` depending on kind.

**Step 4: Update `register_listener()` upsert** — change the `ON CONFLICT` target to match the new unique index expression `(app_key, instance_index, name, topic)`. No `WHERE once = 0` filter, no `COALESCE`, no `handler_method` in the key. `name` is `NOT NULL`.

**Step 5: Update reconciliation queries** — `_build_delete_query()` and `_build_retire_query()` reference `handler_invocations`/`job_executions` in `NOT EXISTS`/`EXISTS` subqueries. Change to `executions` with the correct FK column (`listener_id` or `job_id`). See design doc Reconciliation and Retention section.

**Step 6: Verify upsert/index alignment** — write a unit test that queries `sqlite_master` for the unique index definition and asserts (a) it matches the repository's `ON CONFLICT` target verbatim, and (b) its columns are exactly the canonical tuple `(app_key, instance_index, name, topic)` (FR#4 structural test). Part (b) ties the DB index to the same source of truth that T03 pins the in-memory `_listener_natural_key()` against — together these guard all three definition sites against drift.

**Step 7: Update existing tests** — `test_telemetry_repository.py` has dual table INSERT/upsert tests. Update for unified table.

## Focus
- The upsert `ON CONFLICT` target must EXACTLY match the unique index expression — divergence causes SQLite to silently INSERT instead of UPDATE.
- The once-listener INSERT fork at `telemetry_repository.py:309-310` relied on `WHERE once = 0` partial index. With the filter removed, once-listeners participate in upsert like everything else. Remove the fork.
- `_RETENTION_TABLES` and parent-guard DELETE queries in `database_service.py` should already be updated in T02 — verify.

## Verify
- [ ] FR#1: `INSERT INTO executions` with `kind` field replaces dual table inserts
- [ ] FR#4: Upsert conflict target matches unique index definition (sqlite_master test)
- [ ] AC#1: Existing repository tests pass after adaptation to unified table
