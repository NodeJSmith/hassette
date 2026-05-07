---
task_id: "T01"
title: "Extend JobSummary model and query with error and duration fields"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#3", "AC#1", "AC#2"]
---

## Summary
Extend the backend `JobSummary` model with last-error fields (`last_error_message`, `last_error_type`, `last_error_ts`) and min/max duration (`min_duration_ms`, `max_duration_ms`). Update `get_job_summary()` in the telemetry query service to populate these via a LEFT JOIN subquery for errors (same pattern as handlers) and MIN/MAX aggregates for duration. All new fields use `float | None = None` or `str | None = None` — no COALESCE sentinel.

## Prompt
Add fields to the `JobSummary` model in `src/hassette/core/telemetry_models.py` (after line 154):
- `last_error_message: str | None = None`
- `last_error_type: str | None = None`
- `last_error_ts: float | None = None`
- `min_duration_ms: float | None = None`
- `max_duration_ms: float | None = None`

Extend `get_job_summary()` in `src/hassette/core/telemetry_query_service.py` (starts at line 329):
1. Add a LEFT JOIN subquery on `job_executions` to fetch the most recent error — follow the exact pattern from `get_listener_summary()` lines 303-307 which uses a correlated subquery with `since_err_clause`
2. Add `MIN(je.duration_ms)` and `MAX(je.duration_ms)` to the SELECT clause — do NOT use COALESCE, let them pass through as NULL
3. Map the new columns to the JobSummary model fields in the `model_validate()` call

Write unit tests in the existing test file `tests/integration/test_telemetry_query_service.py` (or create a focused test file if needed). Test:
- A job with errors returns `last_error_message`, `last_error_type`, `last_error_ts`
- A job with only successful executions returns `None` for all error fields
- A job with no executions returns `None` for error fields AND duration fields
- Min/max durations are correct for a job with multiple executions at different durations

After model changes, regenerate schemas: `uv run python scripts/export_schemas.py` then `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts`.

## Focus
- `get_listener_summary()` at line 255 is the reference implementation — the LEFT JOIN subquery pattern is at lines 303-307
- The `since_err_clause` parameter scopes the error subquery to the time window — copy this pattern exactly
- `job_executions` table schema has `error_type`, `error_message`, `error_traceback` columns (see `migrations/versions/001_initial_schema.py:138-155`)
- The `timed_out` status was added in migration 005 — the CHECK constraint is already correct
- Existing `avg_duration_ms` and `total_duration_ms` use `COALESCE(AVG(...), 0.0)` — the new min/max must NOT follow this pattern (use NULL instead per Key Decision #2 in context.md)
- The mapper in `src/hassette/web/mappers.py` does NOT apply to JobSummary — it's used for ListenerWithSummary only. JobSummary is returned directly from the route

## Verify
- [ ] FR#1: `get_job_summary()` returns `last_error_message`, `last_error_type`, and `last_error_ts` populated from the most recent errored execution
- [ ] FR#3: `get_job_summary()` returns `min_duration_ms` and `max_duration_ms` as `float | None` (NULL when no executions exist, numeric when they do)
- [ ] AC#1: A job with at least one error has non-None error fields; a job with only successes has None error fields
- [ ] AC#2: A job with executions has numeric min/avg/max; a job with no executions has None for min/max
