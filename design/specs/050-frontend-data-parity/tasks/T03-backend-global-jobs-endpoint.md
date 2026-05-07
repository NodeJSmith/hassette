---
task_id: "T03"
title: "Add global jobs endpoint and extend ServiceInfoResponse"
status: "done"
depends_on: ["T01"]
implements: ["FR#9", "FR#10", "AC#7"]
---

## Summary
Create the global jobs endpoint (replacing the tombstoned scheduler.py), add `get_all_jobs_summary()` to the telemetry query service, extend `ServiceInfoResponse` with `role`/`ready_phase`/`retry_at` for the diagnostics cold-load, and update `gather_all_listeners()` to drop its hardcoded `source_tier` filter. Also remove the hardcoded `source_tier="app"` from `gather_all_listeners()` so the global handlers endpoint returns all tiers.

## Prompt
**1. Add `get_all_jobs_summary()` to `TelemetryQueryService`** (`src/hassette/core/telemetry_query_service.py`):
- Model it after `get_all_app_summaries()` (line 387) for query style
- Single SQL query joining `scheduled_jobs` with `job_executions` — no `app_key` WHERE clause
- Include the same LEFT JOIN error subquery added in T01
- Include MIN/MAX duration aggregates
- Accept `since: float | None = None` and `source_tier` parameters
- Return `list[JobSummary]`

**2. Create global jobs route** — replace `src/hassette/web/routes/scheduler.py` (currently a tombstone comment):
- `GET /api/scheduler/jobs` returning `list[JobSummary]`
- Query params: `since` (optional float), `source_tier` (optional, default None for all tiers)
- Implementation follows the enrichment pattern from `app_jobs()` in `telemetry.py:214-290`:
  1. Call `get_all_jobs_summary()`
  2. Take a single heap snapshot via `scheduler_service.get_all_jobs()`
  3. Build lookup by `db_id`, enrich each DB row with live data (next_run, fire_at, jitter, cancelled)
  4. On heap failure, return DB rows without enrichment (degraded, logged warning)
- Use `DB_ERRORS` catch pattern from `src/hassette/web/routes/telemetry.py:48`
- Register the router in `src/hassette/web/app.py`

**3. Update `gather_all_listeners()`** (`src/hassette/web/utils.py:16`):
- Remove or parameterize the hardcoded `source_tier="app"` in the `get_listener_summary()` calls
- The function should return listeners of all tiers by default

**4. Extend `ServiceInfoResponse`** (`src/hassette/web/models.py:19`):
- Add `role: str = ""`, `ready_phase: str | None = None`, `retry_at: float | None = None`
- Update the mapper in `src/hassette/web/mappers.py:108` (`system_status_response_from()`) to populate these from the domain `ServiceInfo` objects
- This may require updating `SystemStatus.services` in `src/hassette/core/domain_models.py` to carry richer service data — check `runtime_query_service.py:get_system_status()` to see what's available

**5. Regenerate schemas** — T03 is the canonical schema regeneration point. If T01 and T02 have already completed, this single regeneration captures all backend model changes (JobSummary fields, ListenerWithSummary traceback, ServiceInfoResponse extension, new global jobs route). Run `uv run python scripts/export_schemas.py` then `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts`. Verify the generated types include all new fields before proceeding to frontend tasks.

Write tests for:
- Global jobs endpoint returns jobs from multiple apps
- Global jobs endpoint enriches with live heap data when available
- Global jobs endpoint returns DB-only data on scheduler failure (503-like degradation)
- `gather_all_listeners()` returns both app and framework tiers
- `ServiceInfoResponse` includes `role`, `ready_phase`, `retry_at` when available

## Focus
- The per-app `app_jobs()` endpoint at `telemetry.py:214-290` is the exact reference implementation for enrichment — copy and adapt
- The tombstone at `scheduler.py` says the endpoint was removed — we're restoring a global view with a different query strategy
- `get_all_app_summaries()` (line 387) uses `BEGIN DEFERRED` for WAL snapshot isolation across multiple queries — consider whether `get_all_jobs_summary()` needs this (likely yes if the query joins multiple tables)
- `gather_all_listeners()` at `utils.py:16` passes `source_tier="app"` to each `get_listener_summary()` call — this needs to become `None` or be removed entirely
- `ServiceInfo` in `domain_models.py` may only have `name` and `status` — check `runtime_query_service.py` to see if richer data (role, ready_phase) is available from the Resource tree. If not, the service list from `hassette.children` needs to provide it.
- Register the new router in `app.py` following the existing pattern (line 19+)

## Verify
- [ ] FR#9: `gather_all_listeners()` returns listeners of all tiers (app + framework) when called without a `source_tier` filter
- [ ] FR#10: `GET /api/scheduler/jobs` returns all jobs across all apps with live scheduling data (next_run, fire_at, jitter, cancelled)
- [ ] AC#7: Global jobs endpoint returns enriched data from the scheduler heap; returns DB-only data when scheduler is unavailable
- [ ] AC#7: `ServiceInfoResponse` includes `role`, `ready_phase`, and `retry_at` fields in the `GET /api/health` response
