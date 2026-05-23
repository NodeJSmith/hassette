---
task_id: "T04"
title: "Add health aggregate and global listeners queries"
status: "planned"
depends_on: ["T03"]
implements: ["FR#4", "FR#5", "AC#4", "AC#5"]
---

## Summary
Add two new query methods to `TelemetryQueryService`: a purpose-built aggregate query for the app health endpoint (replacing two detail queries + Python aggregation), and a global listeners summary query (replacing the N-query fan-out pattern). Update the route handlers to use the new methods. This depends on T03 because `get_all_listeners_summary()` uses the ROW_NUMBER() CTE pattern established there.

## Prompt
1. **Add `get_app_health_aggregates()`** to `src/hassette/core/telemetry_query_service.py`:
   - Returns a single result object with: `total_invocations`, `handler_errors`, `handler_timed_out`, `handler_avg_duration_ms`, `total_executions`, `job_errors`, `job_timed_out`, `job_avg_duration_ms`, `last_activity_ts`
   - Uses two CTEs (`handler_agg`, `job_agg`) joined in one query:
     ```sql
     WITH handler_agg AS (
         SELECT COUNT(hi.rowid) AS total_invocations,
                SUM(CASE WHEN hi.status = 'error' THEN 1 ELSE 0 END) AS handler_errors,
                SUM(CASE WHEN hi.status = 'timed_out' THEN 1 ELSE 0 END) AS handler_timed_out,
                COALESCE(AVG(hi.duration_ms), 0.0) AS handler_avg_duration_ms,
                MAX(hi.execution_start_ts) AS handler_last_activity
         FROM handler_invocations hi
         JOIN listeners l ON l.id = hi.listener_id
         WHERE l.app_key = :app_key AND l.instance_index = :instance_index
               {since_clause} {tier_clause}
     ),
     job_agg AS (
         SELECT COUNT(je.rowid) AS total_executions, ...
         FROM job_executions je
         JOIN scheduled_jobs j ON j.id = je.job_id
         WHERE j.app_key = :app_key AND j.instance_index = :instance_index
               {since_clause} {tier_clause}
     )
     SELECT * FROM handler_agg, job_agg
     ```
   - Create a `AppHealthAggregates` dataclass or Pydantic model for the result
   - Support `since`, `source_tier` parameters matching the existing method signatures

2. **Update `app_health` route** in `src/hassette/web/routes/telemetry.py` (lines ~116-176):
   - Replace the `get_listener_summary()` + `get_job_summary()` calls (lines 128-133) with a single `get_app_health_aggregates()` call
   - Simplify the response assembly — read fields directly from the aggregates object instead of summing across lists
   - Keep the `try/except DB_ERRORS` pattern and 503 fallback

3. **Add `get_all_listeners_summary()`** to `src/hassette/core/telemetry_query_service.py`:
   - Mirrors `get_all_jobs_summary()` but for the `listeners` + `handler_invocations` tables
   - Single query returning all listeners across all apps and instances
   - Uses the ROW_NUMBER() CTE from T03 for last-error (row-coherent)
   - Does NOT need `_snapshot_lock` — single-statement query
   - Returns `list[ListenerSummary]`
   - Support `since`, `source_tier` parameters

4. **Update `bus.py` route** in `src/hassette/web/routes/bus.py` (lines 16-34):
   - When no `app_key` filter is provided, call `telemetry.get_all_listeners_summary(since=since)` directly
   - Remove the call to `gather_all_listeners()` for the unfiltered case
   - Keep `gather_all_listeners()` for the filtered case (single app_key) or replace with `get_listener_summary()` directly

5. **Write tests:**
   - `get_app_health_aggregates()`: verify totals match the sum of per-item detail queries with mixed handler/job success/error/timed_out statuses. Test with zero invocations, test with `since` parameter.
   - `get_all_listeners_summary()`: verify returns all listeners across apps/instances matching the combined results of per-instance `get_listener_summary()` calls. Test last-error coherence. Test `source_tier` filtering.

## Focus
- `get_all_app_summaries()` (line ~395) is the closest existing pattern for a CTE-based aggregate query — study its structure for the `get_app_health_aggregates()` implementation.
- `get_all_jobs_summary()` (line ~316) is the closest pattern for `get_all_listeners_summary()` — mirror its structure but for listeners/handler_invocations instead of scheduled_jobs/job_executions.
- The `gather_all_listeners()` function in `src/hassette/web/utils.py:18-45` creates one task per app instance via `asyncio.gather`. The new global query replaces this for the unfiltered case.
- The `app_health` route's response assembly (lines 146-163) currently sums across `listeners` and `jobs` lists — with the aggregate query, this becomes direct field reads.
- Use the `_source_tier_clause()` and `_since_clause()` helpers already in `telemetry_query_service.py` for parameter handling.

## Verify
- [ ] FR#4: The `app_health` route calls `get_app_health_aggregates()` — no `get_listener_summary()` or `get_job_summary()` calls remain in the route handler
- [ ] FR#5: The `GET /bus/listeners` route (without app_key) calls `get_all_listeners_summary()` — no `gather_all_listeners()` fan-out for the unfiltered case
- [ ] AC#4: Tests confirm `get_app_health_aggregates()` returns correct totals matching per-item sums
- [ ] AC#5: Tests confirm `get_all_listeners_summary()` returns all listeners across apps/instances in a single query
