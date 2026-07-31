---
task_id: "T07"
title: "Update frontend for schedule status and Run Now feedback"
status: "planned"
depends_on: ["T06"]
implements: ["FR#26", "AC#8", "AC#9", "AC#13"]
---

## Summary

Update the frontend to render all four schedule statuses, add `schedule_status` to `UnifiedRow` with a status-aware sort comparator, and implement post-submission Run Now feedback (success toast or timeout fallback). Add a manual-only job to the E2E fixtures. Regenerate TypeScript types from the updated OpenAPI schema.

## Target Files

- modify: `frontend/src/utils/handler-rows.ts`
- modify: `frontend/src/utils/handler-rows.test.ts`
- modify: `frontend/src/pages/handlers-rows.tsx`
- modify: `frontend/src/pages/handlers-rows.test.tsx`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- modify: `frontend/src/components/app-detail/handlers-tab.job.test.tsx`
- modify: `frontend/src/components/app-detail/unified-handler-row.tsx`
- modify: `frontend/src/components/app-detail/unified-handler-row.test.tsx`
- modify: `frontend/src/api/endpoints.ts`
- modify: `frontend/src/api/generated-types.ts`
- modify: `frontend/src/test/factories.ts`
- read: `design/specs/090-registered-manual-jobs/design.md` (Architecture > Operator Surfaces, FR#26, AC#8, AC#9, AC#13)
- modify: `tests/e2e/conftest.py`

## Prompt

**Regenerate TypeScript types first:**
```bash
cd frontend && npm run types && npm run ws-types
```

**Add `schedule_status` to `UnifiedRow`** in `frontend/src/utils/handler-rows.ts`:
- Add `schedule_status: string | null` field.
- Update `jobToRow()` to populate it from the API response.
- Update the sort comparator: when `next_run_ts` is null, use `schedule_status` as a secondary sort key. Define a sort order: `manual` → `waiting` → `completed` → null (unknown/degraded).

**Update job detail rendering** in `frontend/src/components/app-detail/job-detail.tsx`:
- Render status-specific text for each `schedule_status`:
  - `scheduled`: next relative time (existing behavior).
  - `scheduled` + null timing (degraded): "Timing unavailable."
  - `scheduled` + `legacy_unknown`: "Legacy status unknown."
  - `waiting`: "Waiting for entity time."
  - `completed` (no reason): "Schedule completed."
  - `completed` + `trigger_error`: "Schedule stopped after trigger error."
  - `manual`: "Manual only."
- Run Now remains available for every live status.

**Update unified handler row** in `frontend/src/components/app-detail/unified-handler-row.tsx`:
- Show a schedule status badge/indicator. Use existing badge patterns — no new visual system.

**Implement Run Now post-submission feedback:**
- After clicking Run Now and receiving 202, poll for a new execution record for the job.
- On success: show a brief success toast.
- On timeout (no new record within ~5-10s): show "No execution recorded" toast.
- The `triggerJob()` endpoint in `frontend/src/api/endpoints.ts` should return the 202 response. Remove any 409 error handling for "already running" or "already fired" — those responses no longer exist.

**Update frontend tests:**
- `handler-rows.test.ts`: test `schedule_status` field population and sort comparator with all four statuses.
- `handlers-tab.job.test.tsx`: test distinct rendering for each status.
- `unified-handler-row.test.tsx`: test status badge rendering.
- `handlers-rows.test.tsx`: test list-level rendering with mixed statuses.
- `frontend/src/test/factories.ts`: update job factory to include `schedule_status` and `schedule_status_reason` fields.

**Add E2E fixture:**
- In `tests/e2e/conftest.py` or the relevant E2E app fixture, add a manual-only job so the E2E suite can discover and submit it through the live UI.

**Run `npm run build`** to verify the frontend compiles after all changes.

See design doc: Architecture > Operator Surfaces, FR#26, AC#8, AC#9, AC#13.

## Focus

- `frontend/src/utils/handler-rows.ts` has a `cancelled: number` field — this is an execution-outcome count (FR#23 says "continue using `cancelled` only for interrupted executions"), NOT the registration `cancelled_at` column. Do NOT rename it.
- `frontend/src/api/endpoints.ts` has `triggerJob` — the endpoint path likely stays the same, but the response contract changes (always 202, never 409 for overlap/completion reasons).
- `frontend/src/api/generated-types.ts` is git-tracked and regenerated — don't hand-edit it.
- Follow existing Tailwind/shadcn patterns for the status badge. Check `design/context.md` for design tokens.
- The E2E fixture needs to register a manual-only job via `scheduler.register()` — this depends on the backend work in T03 being complete.
- Run `npm install` first if this is a fresh worktree (see `.claude/rules/frontend-worktree.md`).

## Verify

- [ ] FR#26: Run Now button shows a success toast when execution completes, and "No execution recorded" after timeout.
- [ ] AC#8: Frontend tests demonstrate distinct scheduled/waiting/completed/manual rendering and Run Now availability for every live status.
- [ ] AC#9: Playwright E2E demonstrates a manual-only job displayed and submitted through the live UI with execution activity subsequently visible.
- [ ] AC#13: Frontend tests demonstrate success toast and timeout fallback toast for all live statuses.
