---
task_id: "T12"
title: "Update frontend types, endpoints, and routing"
status: "done"
depends_on: ["T11"]
implements: ["AC#3"]
---

## Summary
Regenerate frontend types from the updated OpenAPI and WS schemas. Update endpoint paths, query keys, and routing to use the new unified API. Delete `handler-ids.ts`.

## Prompt
**Step 1: Regenerate types:**
- Verify `uv run python scripts/export_schemas.py --types` was run in T11 — if not, run it now.
- Rebuild frontend: `cd frontend && npm run build` — fix any type errors.

**Step 2: Update `api/endpoints.ts`:**
- Add combined list endpoint: `/telemetry/executions`
- Rename detail endpoints: `/telemetry/listener/${id}/executions`, `/telemetry/job/${id}/executions`
- Remove old `/telemetry/handler/${id}/invocations` path

**Step 3: Update `lib/query-keys.ts`:**
- Merge `handlerInvocations`/`jobExecutions` keys or rename to match new endpoint structure.

**Step 4: Update routing** — in `components/app-detail/handlers-tab.tsx`:
- Switch to `/listener/:id` and `/job/:id` path-based routing.
- Delete `frontend/src/utils/handler-ids.ts` (the `h-`/`j-` prefix convention).
- Update `components/layout/palette-items.ts` navigation URLs.

**Step 5: Update detail pages:**
- `components/app-detail/listener-detail.tsx` — update API call to new endpoint path.
- `components/app-detail/job-detail.tsx` — update API call to new endpoint path.

**Step 6: Update `components/app-detail/recent-activity-section.tsx`:**
- Update React key to use `execution_id` instead of `row_id` with `h-`/`j-` prefix.

## Focus
- `handler-ids.ts` exports `parseHandlerId` and prefix constants — grep for all imports before deleting.
- `handlers-tab.tsx` and `palette-items.ts` both construct URLs using the old prefix convention.
- The `row_id` field in activity feed entries changes from `'h-123'` / `'j-456'` to UUID format.

## Verify
- [ ] AC#3: Frontend builds without type errors (`cd frontend && npm run build`); full e2e verification in T15
