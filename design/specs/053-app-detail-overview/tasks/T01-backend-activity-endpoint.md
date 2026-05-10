---
task_id: "T01"
title: "Add cross-handler activity endpoint"
status: "planned"
depends_on: []
implements: ["FR#10"]
---

## Summary
Add a new backend endpoint that returns recent invocations and executions across all of an app's handlers and jobs, merged and sorted by time. This is the only new backend work — the `ActivityFeedEntry` Pydantic model already exists, the UNION ALL SQL pattern is proven in `get_per_app_activity_buckets()`, and the route registration pattern is mechanical.

## Prompt
Add a new method `get_app_recent_activity` to `TelemetryQueryService` in `src/hassette/core/telemetry_query_service.py`.

**SQL query**: Use the exact UNION ALL pattern from `get_per_app_activity_buckets()` (line ~649) but with different SELECT columns and `ORDER BY timestamp DESC LIMIT :limit` instead of bucket aggregation. The SELECT should match `ActivityFeedEntry` fields: `status`, `execution_start_ts AS timestamp`, `app_key`, `handler_method AS handler_name`, `duration_ms`, `error_type`, `'handler' AS kind` (and the equivalent for jobs with `'job' AS kind`).

**Method signature**: `async def get_app_recent_activity(self, app_key: str, instance_index: int | None, limit: int, since: float | None, source_tier: QuerySourceTier) -> list[ActivityFeedEntry]`

**Route**: Add `GET /telemetry/app/{app_key}/activity` to `src/hassette/web/routes/telemetry.py`. Follow the exact pattern of `app_listeners()` (line ~177): `@router.get` with `response_model=list[ActivityFeedEntry]`, inject `TelemetryDep`, accept `app_key` as path param, `instance_index`, `limit: int = Query(default=50, ge=1, le=500)`, `since`, `source_tier`. Handle `DB_ERRORS` with 503 fallback.

**Schema regeneration**: Run `uv run python scripts/export_schemas.py` and `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts`.

**Frontend endpoint function**: Add `getAppActivity(appKey, instanceIndex, limit, since)` to `frontend/src/api/endpoints.ts` following the pattern of `getAppListeners`.

**Integration test**: Add tests to `tests/integration/test_telemetry_query_service.py` following existing patterns. Seed the database with invocations and executions across multiple handlers for the same app, then verify:
- Results are merged and sorted by timestamp descending
- `limit` parameter is respected
- `since` parameter filters correctly
- Results include both handler and job entries with correct `kind` values
- `source_tier` filtering works

## Focus
**Reuse**: The `ActivityFeedEntry` model at `src/hassette/core/telemetry_models.py` line ~275 already has the exact fields needed — do NOT create a new model. The `_source_tier_clause()` and `_since_clause()` helpers in the query service handle tier and time filtering — use them.

**Pattern to follow**: `get_per_app_activity_buckets()` at line ~624 is the closest existing method. Copy its UNION ALL structure and adapt the SELECT/ORDER BY.

**Gotcha**: SQLite cannot push LIMIT into UNION ALL branches. The `since` parameter (always provided by `useScopedApi`) bounds the scan, so this is acceptable for typical volumes.

**Test fixtures**: Look at how existing tests in `test_telemetry_query_service.py` seed data — they use the `hassette_instance` fixture from `tests/integration/conftest.py` and write directly to the database.

## Verify
- [ ] FR#10: The endpoint `GET /telemetry/app/{app_key}/activity` returns handler invocations and job executions merged into a single list sorted by timestamp descending
- [ ] FR#10 (limit): The `limit` query parameter caps the number of returned entries
- [ ] FR#10 (since): The `since` query parameter filters to entries after the given timestamp
- [ ] FR#10 (source_tier): The `source_tier` query parameter filters by app vs framework tier
