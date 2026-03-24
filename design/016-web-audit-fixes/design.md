# Design: Web Stack Audit Fixes

## Problem

The web stack audit (2026-03-24) identified 12 issues across backend routes, frontend components, and CI infrastructure. These range from a hardcoded zero KPI metric to missing type safety, dead code, and a sort bug. Individually small, collectively they erode reliability and developer confidence.

**Source:** `design/audits/2026-03-24-web-stack/audit.md`, issues #393–#404.

## Scope

12 fixes bundled into a single PR. All are independent — no fix depends on another. Grouped by area:

### Backend fixes (Python)

1. **#393 — Fix hardcoded avg_job_duration_ms KPI**
   - Add `avg_duration_ms: float = 0.0` field to `JobGlobalStats` model (`telemetry_models.py`)
   - Add `COALESCE(AVG(je.duration_ms), 0.0) AS avg_duration_ms` to the job query SQL in `get_global_summary()` — both the session-filtered branch (line ~275) and unfiltered branch (line ~298) (`telemetry_query_service.py`)
   - Map the new SQL column into `JobGlobalStats` construction
   - Replace `avg_job_duration_ms=0.0` with `summary.jobs.avg_duration_ms or 0.0` in `routes/telemetry.py:185`

2. **#395 — Remove dead `compute_app_grid_health()`**
   - Delete lines 153–181 of `telemetry_helpers.py`
   - No callers exist (grep confirms)

3. **#396 — Remove stub `/scheduler/history` endpoint**
   - Delete lines 52–59 of `routes/scheduler.py`
   - The endpoint is redundant: `/telemetry/job/{job_id}/executions` already serves per-job execution history
   - Remove `JobExecutionResponse` import if it becomes unused

4. **#400 — Improve WS drop observability**
   - Change `self.logger.debug(...)` to `self.logger.warning(...)` in `runtime_query_service.py:327`
   - Include client count context in the log message

5. **#401 — Add response models to mutation endpoints**
   - Create `ActionResponse` model: `status: str`, `app_key: str`, `action: str`
   - Apply to `routes/apps.py` start/stop/reload endpoints
   - For `/config`: create `ConfigResponse` from the `_CONFIG_SAFE_FIELDS` set
   - For `/services`: leave as `dict[str, Any]` (HA's service schema is external and unstable)

6. **#402 — Fix bus.py return type annotation**
   - Change `-> list[ListenerSummary]` to `-> list[ListenerMetricsResponse]` in `routes/bus.py:21`

### Frontend fixes (TypeScript)

7. **#394 — Extend ListenerData to match backend**
   - Add ~16 missing fields to `ListenerData` interface in `endpoints.ts`
   - Fields: `di_failures`, `cancelled`, `min_duration_ms`, `max_duration_ms`, `total_duration_ms`, `predicate_description`, `human_description`, `debounce`, `throttle`, `once`, `priority`, `last_error_message`, `last_error_type`, `source_location`, `registration_source`

8. **#397 — Parse backend error detail in API client**
   - In `client.ts`, read response body before throwing `ApiError`
   - Extract `detail` field from FastAPI's error JSON

9. **#403 — Replace LogTable `.reverse()` with actual `.sort()`**
   - Replace `[...filtered].reverse()` with `[...filtered].sort((a, b) => sortAsc.value ? a.timestamp - b.timestamp : b.timestamp - a.timestamp)`
   - Add test with non-chronological entry order to verify sort correctness
   - Remove the `describe.todo` block and replace with actual REST+WS merge test

10. **#404 — Add concurrency guard to ActionButtons exec**
    - Add `if (loading.value) return;` at top of `exec` function
    - Add test: click twice rapidly, assert API called exactly once

### CI/schema fixes

11. **#398 — Add schema freshness tests**
    - `scripts/export_schemas.py` already generates both schemas
    - Add a Python test that regenerates ws-schema.json and openapi.json in memory and asserts they match the files on disk
    - Fix the stale `ConnectedWsMessage` timestamp in ws-schema.json by regenerating

## Non-goals

- No CSS/styling changes
- No new features — strictly fixes for identified issues
- No refactoring beyond what's needed for each fix
- #399 (component test coverage for remaining 22 untested components) — large scope, better as a separate effort. #403 and #404 partially address it by adding tests alongside their fixes

## Alternatives considered

- **#396**: Considered implementing `/scheduler/history` instead of removing it. Rejected because `/telemetry/job/{job_id}/executions` already provides identical functionality.
- **#401 /services**: Considered creating a full Pydantic model for HA's service registry. Rejected because the schema is external and changes with HA versions — a `dict[str, Any]` is the correct representation for pass-through data.
- **#403**: Considered keeping `.reverse()` and just ensuring insertion order is correct. Rejected because REST+WS merge can produce interleaved timestamps that only a real sort handles correctly.

## Testing

Each fix includes its own test:
- #393: Verify KPI endpoint returns non-zero avg_job_duration_ms when jobs exist
- #395: No test needed (code deletion)
- #396: Remove or update any test asserting `/scheduler/history` exists
- #397: Test that ApiError contains the detail message from a non-2xx response
- #398: CI test asserting schema freshness
- #400: No test needed (log level change)
- #401: Verify OpenAPI schema shows typed response models
- #402: No test needed (type annotation)
- #403: Test with non-chronological timestamps, test REST+WS merge
- #404: Test double-click prevention
