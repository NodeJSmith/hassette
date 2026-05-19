---
task_id: "T04"
title: "Migrate config API endpoint and frontend"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["AC#8"]
---

## Summary

Update the `/api/config` endpoint to serve nested config structure, restructure the `ConfigResponse` model, regenerate OpenAPI/TypeScript types, and update the frontend config page to consume the new shape. This task crosses the backend/frontend boundary but represents one coherent API contract change.

## Prompt

### Step 1: Update config route and response model

**`src/hassette/web/routes/config.py`:**

Replace the flat `_CONFIG_SAFE_FIELDS` allowlist approach with an exclude-based approach. Instead of `model_dump(include=_CONFIG_SAFE_FIELDS)`, use `model_dump(exclude={"token", ...})` to exclude sensitive root fields. This naturally handles nested models — the entire nested group is included unless explicitly excluded.

Alternatively, build a nested include set if fine-grained control per group is needed. The current allowlist exposes 24 fields + 3 path fields = 27 total. After migration, the same fields should be exposed but organized under their groups.

Remove the manual Path field injection (lines 45-47 for `app_dir`, `data_dir`, `config_dir`) — after migration, `data_dir` and `config_dir` are root-level fields, and `app_dir` is under `config.app.directory`. Use `model_dump(mode="json")` or add `json_encoders` for Path serialization instead of manual `str()` casting.

**`src/hassette/web/models.py` (ConfigResponse at line 376):**

Restructure `ConfigResponse` from a flat 26-field model to a nested structure mirroring the config groups. Create lightweight response sub-models for each group that only include the safe-to-expose fields:

```python
class DatabaseConfigResponse(BaseModel):
    retention_days: int = 7
    max_size_mb: float = 500
    # ... only safe fields

class ConfigResponse(BaseModel):
    dev_mode: bool = False
    database: DatabaseConfigResponse = Field(default_factory=DatabaseConfigResponse)
    # ... other groups
```

Not all fields in each config group need to be in the response — the current allowlist already filters. Match the same set of exposed fields, just organized by group.

### Step 2: Regenerate schemas and TypeScript types

```bash
uv run python scripts/export_schemas.py
cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts
```

### Step 3: Update frontend config page

**`frontend/src/pages/config.tsx`:**

The page currently groups config fields manually into 6 display groups (general, connection, buffers, timeouts, scheduler, paths). After migration, the API response is already grouped by config model. Update the page to either:

a) Read fields from the nested response structure (`config.database.retention_days` instead of flat field names), OR
b) Flatten the nested response for display (keeping the existing display grouping but reading from nested source)

Option (a) is preferred — align the display groups with the config model groups where possible. The current display groups partially overlap with the config groups (e.g., "connection" mixes web_api and root fields). Restructure to match the backend groups more closely.

Update all field access patterns. The current 28 field accesses like `config.dev_mode`, `config.web_api_host`, `config.scheduler_min_delay_seconds` become `config.dev_mode` (root stays), `config.web_api.host`, `config.scheduler.min_delay_seconds`.

**`frontend/src/test/factories.ts`:**

Update `createSystemConfig()` factory to produce the nested structure matching the new `ConfigResponse` shape.

**`frontend/src/pages/config.test.tsx`:**

Update test assertions to match the new response structure.

### Step 4: Update web_mocks config_dump

In `src/hassette/test_utils/web_mocks.py`, the `config_dump` dictionary (around line 133) that feeds `hassette.config.model_dump.return_value` needs to match the new nested structure.

### Step 5: Verify

Run frontend build and tests:
```bash
cd frontend && npm run build
cd frontend && npm run test
```

Run the config endpoint integration tests:
```bash
timeout 300 uv run pytest tests/integration/test_web_api.py -v -k config
```

## Focus

- `src/hassette/web/routes/config.py` (48 lines) — small file, complete rewrite of the route logic. The current `_CONFIG_SAFE_FIELDS` set has 24 entries. After migration, use exclude-based approach or restructured include set.
- `src/hassette/web/models.py:376-405` — `ConfigResponse` is currently 26 flat fields with defaults. Restructure into nested sub-models.
- `frontend/src/pages/config.tsx` (129 lines) — hardcodes 6 display groups with 28 field accesses. All field access patterns change.
- `frontend/src/test/factories.ts` — `createSystemConfig()` produces flat config mock data.
- `frontend/src/pages/config.test.tsx` — tests for the config page.
- The frontend uses Preact with TypeScript. Types are generated from OpenAPI spec via `openapi-typescript`. After schema regeneration, the `ConfigResponse` type in `generated-types.ts` will be nested, and all consumers must be updated.
- Run `uv run python tools/check_schemas_fresh.py` to verify schema freshness — CI checks this.
- The four CSS lint tools (`check_global_css_allowlist.py`, `check_dead_global_css.py`, `check_css_module_globals.py`, `check_undefined_css_refs.py`) should still pass — this change doesn't affect CSS.

## Verify
- [ ] AC#8: Config endpoint integration tests pass (`timeout 300 uv run pytest tests/integration/test_web_api.py -v -k config` exits 0)
- [ ] AC#8: Frontend build succeeds (`cd frontend && npm run build` exits 0)
- [ ] AC#8: Frontend tests pass (`cd frontend && npm run test` exits 0)
- [ ] AC#8: Schema freshness check passes (`uv run python tools/check_schemas_fresh.py` exits 0)
