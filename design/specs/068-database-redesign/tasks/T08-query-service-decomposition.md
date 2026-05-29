---
task_id: "T08"
title: "Decompose and unify query service"
status: "planned"
depends_on: ["T05", "T06"]
implements: ["FR#1", "FR#18", "AC#13"]
---

## Summary
Split the 1,187-line `telemetry_query_service.py` into focused modules under `core/telemetry/` while merging mirrored query pairs into single parameterized queries. Remove session exposure from API-facing queries.

## Prompt
**Step 1: Create module structure** under `src/hassette/core/telemetry/`:
- `__init__.py` — empty
- `query_service.py` — `TelemetryQueryService` class (init, DB access, `execute()` context manager) + re-exports for backward compatibility. ~100 lines.
- `registration_queries.py` — `get_listener_summary`, `get_job_summary`, `get_all_listeners_summary`, `get_all_jobs_summary`, `get_slow_handlers`. ~350 lines.
- `execution_queries.py` — unified `get_executions` (replaces `get_handler_invocations` + `get_job_executions`), `get_app_recent_activity`, `get_per_app_activity_buckets`, `get_per_app_last_errors`, `get_recent_invocations_1h*`, `check_execution_predates_retention_cutoff`. ~350 lines.
- `summary_queries.py` — `get_app_health_aggregates`, `get_all_app_summaries`, `get_session_list`, `get_log_records*`. ~200 lines.
- `helpers.py` — `_source_tier_clause`, `_since_clause`, `_row_to_dict`, `_build_app_summaries`, `AppHealthAggregates`.

**Step 2: Merge mirrored query pairs** — each pair that does the same thing for handlers and jobs becomes a single parameterized query against the `executions` table. The `kind` parameter or FK column filter replaces the table name switch.

**Step 3: Unified `get_executions()`** — replaces `get_handler_invocations()` + `get_job_executions()`. Accepts optional `listener_id`, `job_id`, or `kind` filter params. Returns unified `Execution` model instances.

**Step 4: `check_execution_predates_retention_cutoff`** — drops from 2 queries to 1 (one table instead of two).

**Step 5: `AppHealthSummary` aggregation queries** — retain split fields (`total_invocations`/`total_executions`). Reconstruct by kind using `COUNT(*) FILTER (WHERE kind = 'handler')` or equivalent.

**Step 6: Session queries** — `session_id` stays in query results for internal use but is NOT exposed in API-facing response models (FR#18).

**Step 7: `ActivityFeedEntry` query** — update the `row_id` generation from `'h-' || rowid` / `'j-' || rowid` to `execution_id` (the UUID column).

**Step 8: Re-export from `query_service.py`** for backward compatibility — consumers that import `from hassette.core.telemetry_query_service import TelemetryQueryService` should still work via re-export.

**Step 9: Delete the original `telemetry_query_service.py`** after all imports are redirected.

**Step 10: Update tests** — `test_telemetry_query_service.py` mirrored query tests merge into unified tests.

## Focus
- `_source_tier_clause` helper pattern should be reused for the new `_kind_clause` helper.
- The UNION ALL methods (`activity`, `errors`, `health`) need minimal SQL change — they already query both tables and union. Now they query one table.
- Keep backward-compatible imports via re-export to avoid a blast radius across all consumers.
- SQLite does not support `FILTER (WHERE ...)` on aggregate functions. Use `SUM(CASE WHEN kind = 'handler' THEN 1 ELSE 0 END)` instead.

## Verify
- [ ] FR#1: Mirrored query pairs are merged into single queries against `executions` table
- [ ] FR#18: Session identity fields are absent from API-facing query return types
- [ ] AC#13: No session ID appears in response models used by REST endpoints
