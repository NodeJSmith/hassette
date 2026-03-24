# WP03: Schema Validation Tests

**Lane:** todo
**Estimated scope:** 1 fix, 1-2 new test files

## Changes

### Add CI schema freshness tests (#398)

**Files:**
- New test file (likely `tests/integration/test_schema_freshness.py` or similar) that:
  1. Imports `WsServerMessage` from `hassette.web.models`
  2. Uses `TypeAdapter(WsServerMessage).json_schema()` to generate ws-schema.json in memory
  3. Reads `frontend/ws-schema.json` from disk
  4. Asserts they match (with a helpful error message suggesting to run `scripts/export_schemas.py`)
  5. Same pattern for `openapi.json` — generate from the FastAPI app and compare

- Regenerate `frontend/ws-schema.json` via `scripts/export_schemas.py` to fix the stale `ConnectedWsMessage` (missing `timestamp` in `required`)

**Test:** The test itself IS the deliverable — it validates schema freshness.

## Acceptance criteria

- [ ] `ws-schema.json` is regenerated and includes `timestamp` in `ConnectedWsMessage.required`
- [ ] CI test fails if `ws-schema.json` drifts from Pydantic models
- [ ] CI test fails if `openapi.json` drifts from FastAPI app
- [ ] All existing tests pass
