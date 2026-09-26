---
task_id: "T06"
title: "Regenerate schemas and update remaining tests"
status: "done"
depends_on: ["T01", "T02", "T03", "T04", "T05"]
implements: ["AC#7", "AC#8"]
---

## Summary
Regenerate all schemas and TypeScript types after the backend model changes land, then update the remaining test files that weren't covered by T01-T05: schema freshness tests, frontend test factories, MSW handlers, and any integration tests asserting the old WS log message shape. This is the final task — it brings the generated artifacts and test suite into consistency with all the changes made by T01-T05.

## Target Files
- regenerate: `openapi.json`
- regenerate: `ws-schema.json`
- regenerate: `frontend/src/api/generated-types.ts`
- regenerate: `frontend/src/api/ws-types.ts`
- regenerate: `frontend/src/api/ws-validator.generated.ts`
- modify: `tests/integration/test_schema_freshness.py`
- modify: `tests/integration/web_api/test_endpoints.py` (if it asserts WS log message shape)
- modify: `tests/integration/web_api/test_auth.py` (if it references log endpoints)
- modify: `frontend/src/test/factories.ts`
- modify: `frontend/src/test/handlers.ts`
- read: `design/specs/114-ws-log-notify-fetch/design.md`

## Prompt
1. **Regenerate all schemas and types** in one command:
```bash
uv run python scripts/export_schemas.py --types
```
This regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`, and `ws-validator.generated.ts`.

2. **Verify regeneration** — check that:
   - `ws-schema.json` includes `log_hint` message type, not `log`
   - `ws-types.ts` has `LogHintWsMessage` type, no `LogWsMessage`
   - `generated-types.ts` includes `id` field on the log entry response type
   - `ws-validator.generated.ts` validates `log_hint` messages

3. **Update `tests/integration/test_schema_freshness.py`** (line 53) — it hardcodes `LogWsMessage` in a parametrize list. Replace with `LogHintWsMessage`. The parametrize list enumerates WS message types for schema-freshness assertions.

4. **Update `frontend/src/test/factories.ts`** — add `id` field (e.g., `id: 1` or auto-incrementing) to any `LogEntryResponse` factory/fixture. The generated type from step 1 now requires `id`.

5. **Update `frontend/src/test/handlers.ts`** — add `id` field to MSW handler responses that return log entry shapes. These mock the REST API responses that the frontend fetches.

6. **Check `tests/integration/web_api/` test files** that grep found referencing `get_log_records`:
   - `test_endpoints.py` — if it asserts WS log message shape or tests the `/logs/recent` endpoint, verify assertions still pass with the `id` field now present in responses
   - `test_auth.py` — if it references log endpoints, ensure the new `/logs/since/{since_id}` route is accessible (or appropriately gated) under the same auth rules
   - `test_telemetry_unavailable_seam.py` — if it tests `db_degrades_to` for the log endpoint, verify the new `/logs/since/{since_id}` route follows the same degradation pattern
   - `test_execution_endpoint.py` — uses `get_log_records_by_execution`, unrelated — no changes needed

7. **Run the full test suite** to verify everything passes:
```bash
uv run nox -s dev
cd frontend && npm run test
```

8. **Run the schema freshness check** to verify generated files match:
```bash
uv run python tools/check_schemas_fresh.py
```

## Focus
- `test_schema_freshness.py` at line 53 parametrizes over WS message model names — it's likely a list of class names or type literals. Find the exact reference and update it.
- Frontend test factories in `frontend/src/test/factories.ts` may build `LogEntry` objects (the TS type from `generated-types.ts`) — these now need `id`. Check whether the factory uses spread defaults or constructs explicitly.
- MSW handlers in `frontend/src/test/handlers.ts` mock REST responses — they return arrays of log entry objects. Add `id` to each mock entry.
- The new `GET /logs/since/{since_id}` route should follow the same auth patterns as `GET /logs/recent` — both are in the same router with the same tags. No separate auth configuration needed.
- `frontend/src/api/ws-types.ts` is fully generated — do NOT hand-edit it. The regeneration in step 1 handles everything.
- The `WsLogPayload` type in `ws-types.ts` (referenced by store.ts, which T04 cleaned up) will disappear after regeneration — any remaining references should have been removed in T04.

## Verify
- [ ] AC#7: `uv run python scripts/export_schemas.py --types` produces updated schemas; `ws-schema.json` includes `log_hint` not `log`; `generated-types.ts` includes `id` on log entry type; `tools/check_schemas_fresh.py` passes
- [ ] AC#8: Full backend test suite (`uv run nox -s dev`) passes; full frontend test suite (`cd frontend && npm run test`) passes
