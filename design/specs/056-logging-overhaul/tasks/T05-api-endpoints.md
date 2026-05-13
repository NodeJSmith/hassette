---
task_id: "T05"
title: "Rewrite log REST API and add runtime log level endpoint"
status: "done"
depends_on: ["T02", "T04"]
implements: ["FR#14", "FR#15", "FR#19", "AC#6", "AC#7", "AC#15", "AC#17"]
---

## Summary
Rewrite the log REST endpoint to query the database instead of the in-memory ring buffer. Add a per-execution log lookup endpoint with retention-expired detection. Add a runtime log level change endpoint. Update response models and WS payload types. Regenerate OpenAPI spec and TypeScript types.

## Prompt
1. Update `LogEntryResponse` in `src/hassette/web/models.py`:
   - Add fields: `execution_id: str | None = None`, `instance_name: str | None = None`, `instance_index: int | None = None`, `source_tier: str | None = None`
   - Keep `seq` field (now populated from the DB `seq` column)

2. Rewrite `GET /api/logs/recent` in `src/hassette/web/routes/logs.py`:
   - Query `telemetry_repository.get_log_records()` via `DatabaseService.submit()` instead of reading the in-memory buffer
   - Keep existing query params: `limit` (1-2000, default 100), `app_key`, `level`, `since`
   - Add `execution_id: str | None = None` query param
   - Add `source_tier: str | None = None` query param
   - Return `list[LogEntryResponse]`

3. Add `GET /api/logs/by-execution/{execution_id}` in `src/hassette/web/routes/logs.py`:
   - Query `telemetry_repository.get_log_records_by_execution()` via `DatabaseService.submit()`
   - Query params: `limit` (1-5000, default 500)
   - Response model: a wrapper with `records: list[LogEntryResponse]`, `truncated: bool`, `retention_expired: bool`
   - `retention_expired` logic: if zero records returned, check if `execution_id` exists in `handler_invocations` or `job_executions` and its timestamp is older than `log_retention_days * 86400` seconds ago. If so, set `retention_expired=True`.

4. Add `PUT /api/logs/level` in `src/hassette/web/routes/logs.py`:
   - Request body: `{"logger": "<name>", "level": "<DEBUG|INFO|WARNING|ERROR|CRITICAL>"}`
   - Validate the level string. Call `logging.getLogger(logger_name).setLevel(level)`.
   - Return `{"logger": "<name>", "effective_level": "<level>"}`.
   - structlog wraps stdlib, so this takes effect immediately for both structlog and stdlib callers.

5. Update `RuntimeQueryService.get_recent_logs()` in `src/hassette/core/runtime_query_service.py`:
   - Change from reading the in-memory buffer to querying the DB via `DatabaseService.submit()`
   - Pass through all filter params to the repository method
   - Keep the method signature compatible for callers

6. Update `LogCaptureHandler.emit()` to include `execution_id`, `instance_name`, `instance_index`, `source_tier` in the WS broadcast payload (the `to_dict()` call already includes them from T02's LogEntry update).

7. Update `WsLogPayload` in `frontend/src/api/ws-types.ts`:
   - Add: `execution_id: string | null`, `instance_name: string | null`, `instance_index: number | null`, `source_tier: string | null`

8. Update `frontend/src/state/create-app-state.ts` — the `RingBuffer<WsLogPayload>` type will pick up the new fields automatically from the type change.

9. Regenerate schemas and types:
   - Run `uv run python scripts/export_schemas.py` to update OpenAPI spec
   - Run `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts`
   - Verify `frontend/src/api/endpoints.ts` `LogEntry` type alias picks up new fields

10. Add `getLogsByExecution` and `setLogLevel` endpoint functions in `frontend/src/api/endpoints.ts`:
    - `getLogsByExecution(executionId: string, limit?: number)` — calls `GET /api/logs/by-execution/{id}`
    - `setLogLevel(logger: string, level: string)` — calls `PUT /api/logs/level`

11. Update test fixtures:
    - `tests/integration/test_web_api.py` — update LogCaptureHandler fixture usage (no more register_app_logger), test new endpoints
    - `tests/unit/core/test_runtime_query_service.py` — update to mock DB queries instead of buffer reads
    - `frontend/src/components/shared/log-table.test.tsx` — update WsLogPayload mock data with new fields
    - `frontend/src/state/create-app-state.test.ts` — update WsLogPayload test data

## Focus
- The existing `GET /api/logs/recent` at `web/routes/logs.py:13-21` is 9 lines. The rewrite replaces `runtime.get_recent_logs()` (which reads the buffer) with a DB query.
- `RuntimeQueryService.get_recent_logs()` at `runtime_query_service.py:349-372` currently calls `handler.get_buffer_snapshot()`. This entire method body changes to a DB query.
- `LogWsMessage` at `web/models.py:153` uses `LogEntryResponse` as `data` — the new fields will be included in WS messages automatically.
- `endpoints.ts:82-88` defines `getRecentLogs` using `apiFetch<LogEntry[]>(buildUrl(...))`. The `LogEntry` type alias at line 18 reads from generated-types.ts, so schema regeneration updates it automatically.
- `overview-tab.tsx:12,345` also imports and calls `getRecentLogs` — verify this still works with the updated response shape.

## Verify
- [ ] FR#14: GET /api/logs/recent returns DB-backed records with filtering by time, app, level, execution_id
- [ ] FR#15: WS log messages include execution_id, instance_name, instance_index, source_tier fields
- [ ] FR#19: PUT /api/logs/level changes a logger's effective level immediately
- [ ] AC#6: After restart, GET /api/logs/recent returns pre-restart records
- [ ] AC#7: GET /api/logs/by-execution/{id} returns only that execution's records
- [ ] AC#15: WS client receives log messages with correlation identifiers
- [ ] AC#17: Setting a logger to DEBUG via PUT endpoint causes DEBUG logs to appear; reverting to INFO suppresses them
