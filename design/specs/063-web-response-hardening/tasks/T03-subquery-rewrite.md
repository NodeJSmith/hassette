---
task_id: "T03"
title: "Rewrite correlated subqueries to ROW_NUMBER() CTEs"
status: "done"
depends_on: []
implements: ["FR#3", "AC#3"]
---

## Summary
Replace the correlated `LEFT JOIN ... ON id = (SELECT ... LIMIT 1)` pattern for last-error retrieval in three query methods with a `ROW_NUMBER()` window function CTE. This eliminates O(N) per-handler subqueries while preserving row coherence — all error columns come from the same invocation row. The pattern is already established in `get_per_app_last_errors()`. Also remove `_snapshot_lock` from `get_all_jobs_summary()` since the rewritten query is a single statement.

## Prompt
1. **Rewrite `get_listener_summary()`** in `src/hassette/core/telemetry_query_service.py` (lines ~196-242):
   - Remove the `LEFT JOIN handler_invocations last_err ON last_err.id = (SELECT ...)` block (lines 231-235)
   - Remove the `since_err_clause` variable and its usage (line 191)
   - Add a CTE at the top of the query:
     ```sql
     WITH ranked_errors AS (
         SELECT listener_id, error_type, error_message, error_traceback, execution_start_ts,
                ROW_NUMBER() OVER (PARTITION BY listener_id ORDER BY execution_start_ts DESC) AS rn
         FROM handler_invocations
         WHERE status IN ('error', 'timed_out')
         {since_err_clause if needed}
     )
     ```
   - Replace the `last_err` join with: `LEFT JOIN ranked_errors last_err ON last_err.listener_id = l.id AND last_err.rn = 1`
   - Keep the existing `last_err.error_type`, `last_err.error_message`, `last_err.error_traceback` SELECT columns unchanged
   - Reference `get_per_app_last_errors()` at line ~718 for the proven pattern

2. **Rewrite `get_job_summary()`** (lines ~244-310):
   - Same pattern but for `job_executions` table with `job_id` partitioning:
     ```sql
     WITH ranked_errors AS (
         SELECT job_id, error_type, error_message, error_traceback, execution_start_ts,
                ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY execution_start_ts DESC) AS rn
         FROM job_executions
         WHERE status IN ('error', 'timed_out')
         {since_err_clause if needed}
     )
     ```

3. **Rewrite `get_all_jobs_summary()`** (lines ~316-393):
   - Same CTE pattern as step 2
   - **Remove `_snapshot_lock` acquisition** (lines 384-391): the rewritten query is a single statement, so SQLite guarantees consistency without `BEGIN DEFERRED`. Remove the `async with self._snapshot_lock:` block, the `await self._db.execute("BEGIN DEFERRED")`, the `try/finally`, and the `ROLLBACK`. Execute the query directly with `async with self._db.execute(query, params) as cursor:`.

4. **Write tests** in `tests/integration/telemetry/test_telemetry_query_service.py` (or a new file alongside it):
   - Test with multiple errors at different timestamps for the same listener — verify `last_error_type`, `last_error_message`, `last_error_traceback` all come from the most recent error (row coherence)
   - Test with a single error — verify it's returned correctly
   - Test with no errors — verify `last_error_*` fields are all None
   - Test with `since` parameter — verify the error CTE respects the time filter

## Focus
- The existing pattern to follow is at `src/hassette/core/telemetry_query_service.py:696-743` (`get_per_app_last_errors()`) — it uses `ROW_NUMBER() OVER (PARTITION BY app_key ORDER BY execution_start_ts DESC)` with `WHERE rn = 1`.
- The `since` parameter needs careful handling in the CTE: the `since_err_clause` from `_since_clause()` must be included in the CTE's WHERE clause so that the "most recent error" is scoped to the query window.
- `_snapshot_lock` is a non-reentrant `asyncio.Lock()` defined at line 137. After removing it from `get_all_jobs_summary`, only `get_all_app_summaries` (line 484) still holds it.
- The test fixtures in `tests/integration/telemetry/conftest.py` provide `query_service` and `db` fixtures. Use the `insert_invocation()` and `insert_listener()` helpers from `tests/integration/telemetry/helpers.py`.

## Verify
- [ ] FR#3: The handler/job summary queries use a `ROW_NUMBER()` CTE — no correlated subqueries (`SELECT ... LIMIT 1` inside a JOIN ON) remain in `get_listener_summary`, `get_job_summary`, or `get_all_jobs_summary`
- [ ] AC#3: Tests confirm that last-error fields are row-coherent (all columns from the same invocation) with multiple errors at different timestamps
