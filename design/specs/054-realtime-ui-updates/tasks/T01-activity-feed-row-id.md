---
task_id: "T01"
title: "Add row_id to activity feed backend query and regenerate types"
status: "planned"
depends_on: []
implements: ["FR#6", "AC#6"]
---

## Summary
Add a unique `row_id` field to the activity feed backend query and response model. The SQLite `rowid` is unique per table but not across the UNION ALL — prefix with `'h-'` for handler invocations and `'j-'` for job executions. Regenerate the OpenAPI spec and frontend TypeScript types. Add a backend test verifying `row_id` uniqueness.

## Prompt
Modify the activity feed SQL query and response model to include a stable unique identifier for each row.

**Backend changes:**

1. In `src/hassette/core/telemetry_query_service.py`, find `get_app_recent_activity()` (around line 802–892). Add `row_id` to both sides of the UNION ALL:
   - Handler invocations: `'h-' || CAST(hi.rowid AS TEXT) AS row_id`
   - Job executions: `'j-' || CAST(je.rowid AS TEXT) AS row_id`
   - Add `row_id` to the outer SELECT and the column list

2. In `src/hassette/core/telemetry_models.py`, add `row_id: str` to the `ActivityFeedEntry` model (around line 275).

3. In `src/hassette/web/routes/telemetry.py`, no route changes needed — the endpoint already returns `list[ActivityFeedEntry]` and the new field will be included automatically.

**Schema regeneration:**
```bash
uv run python scripts/export_schemas.py
cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts
```

**Backend test:**
In `tests/integration/test_telemetry_query_service.py` (around line 1463 where `ActivityFeedEntry` is validated), add a test that:
- Creates two handler invocations with the same `execution_start_ts` for the same listener
- Calls `get_app_recent_activity` and verifies both rows have different `row_id` values
- Verifies handler invocation rows have `row_id` starting with `h-` and job rows with `j-`

**Frontend test fixture updates:**
- `frontend/src/test/handlers.ts:95` — add `row_id: "h-1"` (or similar) to the MSW mock response for activity feed
- `frontend/src/components/app-detail/overview-tab.test.tsx` — update test fixtures that construct `ActivityFeedEntry` objects to include `row_id`

## Focus
- The SQL query uses `_row_to_dict(row)` → `ActivityFeedEntry.model_validate()` to construct results. Make sure the new column name `row_id` matches the model field name.
- SQLite `rowid` is an implicit column available on all tables without ROWID. No migration needed.
- The CAST to TEXT is needed because `rowid` is an integer and we're concatenating with a string prefix.
- Run `uv run nox -s dev -- -n 2` after changes to verify existing tests still pass alongside the new test.
- The `overview-tab.test.tsx` fixtures at lines ~318–372 construct `ActivityFeedEntry` objects — these will fail type checks after regeneration if `row_id` is missing.

## Verify
- [ ] FR#6: `get_app_recent_activity` returns entries with `row_id` field present; two entries with identical handler name and timestamp have different `row_id` values
- [ ] AC#6: Backend test confirms `row_id` uniqueness across handler and job entries with same timestamp; handler rows prefixed `h-`, job rows prefixed `j-`
