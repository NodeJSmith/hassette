---
task_id: "T05"
title: "Remove nameAutoHint from frontend and regenerate types"
status: "planned"
depends_on: ["T01"]
implements: ["FR#8", "AC#8"]
---

## Summary
Remove the `nameAutoHint` prop and its render block from the frontend components, remove the `.nameAutoHint` CSS class, remove `name_auto` from frontend test factories and test assertions, and regenerate TypeScript types from the updated OpenAPI spec (which no longer includes `name_auto` on `JobSummary` after T01).

## Target Files
- modify: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- modify: `frontend/src/components/app-detail/handler-detail-layout.module.css`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- modify: `frontend/src/test/factories.ts`
- modify: `frontend/src/components/app-detail/handlers-tab.test.tsx`
- regenerate: `frontend/src/api/generated-types.ts`

## Prompt
**1. Remove `nameAutoHint` from `handler-detail-layout.tsx`:**
- Remove `nameAutoHint?: boolean` from the `Props` interface (~line 29)
- Remove `nameAutoHint` from the destructuring (~line 53)
- Remove the entire conditional render block (~lines 83-90) that shows the `ⓘ` hint span
- Remove the associated `title` and `aria-label` attributes

**2. Remove `.nameAutoHint` class from `handler-detail-layout.module.css`** (~line 29).

**3. Remove `nameAutoHint` prop from `job-detail.tsx`:**
- Remove `nameAutoHint={job.name_auto}` (~line 129)

**4. Remove `name_auto` from `frontend/src/test/factories.ts`:**
- Remove the `name_auto` property from the job factory (~line 177)

**5. Remove `name_auto` assertions from `frontend/src/components/app-detail/handlers-tab.test.tsx`:**
- Remove any assertions or test data references to `name_auto` (~lines 443-444)

**6. Regenerate TypeScript types:**
```bash
uv run python scripts/export_schemas.py --types
```
This regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts`. Verify `name_auto` no longer appears in `generated-types.ts`.

**7. Rebuild frontend** to verify:
```bash
cd frontend && npm run build
```

## Focus
Install frontend dependencies first if in a worktree: `cd frontend && npm install`.

The `nameAutoHint` prop is optional (`?:`) so removing it won't break any callers — `job-detail.tsx` is the only place that passes it.

After removing `name_auto` from `JobSummary` (T01) and regenerating types, any remaining TypeScript references to `name_auto` will fail the build — use that as a verification step.

## Verify
- [ ] FR#8: `nameAutoHint` does not appear anywhere in `frontend/src/`
- [ ] AC#8: `grep -r 'nameAutoHint' frontend/src/` returns no results; `grep -r 'name_auto' frontend/src/api/generated-types.ts` returns no results
