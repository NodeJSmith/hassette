---
task_id: "T13"
title: "Merge frontend WS signals and remove droppedNoSession"
status: "done"
depends_on: ["T11", "T12"]
implements: ["FR#11", "FR#16", "AC#3"]
---

## Summary
Merge the two WS completion signals into one, update predicate closures to narrow by `kind`, and remove the `droppedNoSession` signal and badge from the frontend.

## Prompt
**Step 1: Merge WS signals** — in `state/create-app-state.ts`:
- Replace `invocationCompleted` and `executionCompleted` signals with a single `executionCompleted` signal typed to the new `ExecutionCompletedData`.
- Remove `droppedNoSession` signal.

**Step 2: Merge WS handler** — in `hooks/use-websocket.ts`:
- Merge the two `case` branches (`invocation_completed`, `execution_completed`) into one `case "execution_completed"`. The `msg.data.app_key` dynamic dict key is unchanged (no rename).

**Step 3: Update predicate closures** — in `components/app-detail/listener-detail.tsx` and `job-detail.tsx`:
- Current: predicates access `e.listener_id` or `e.job_id` on a single-kind signal.
- New: predicates must narrow by kind first: `e.kind === 'handler' && e.listener_id === targetId`.
- Without narrowing, `e.listener_id` is `null` on job rows — the comparison silently fails.

**Step 4: Update `components/app-detail/recent-activity-section.tsx`:**
- Merge the two signal entries into one with the unified predicate.

**Step 5: Remove `droppedNoSession`** from:
- `hooks/use-telemetry-health.ts` — remove from health signal
- `components/layout/alert-banner.tsx` — remove badge/reference
- `components/layout/status-bar.tsx` — remove badge/reference
- `pages/diagnostics.tsx` — remove 5 references

**Step 6: Verify** — run `cd frontend && npm run build` to confirm no type errors.

## Focus
- The TypeScript narrowing pattern is critical — `e.kind === 'handler' && e.listener_id === targetId`. Without the kind guard, the comparison silently produces wrong results (no crash).
- `diagnostics.tsx` has 5 distinct `droppedNoSession` references — don't miss any.
- `status-bar.tsx` and `alert-banner.tsx` are in the `components/layout/` directory.

## Verify
- [ ] FR#11: Frontend subscribes to unified `execution_completed` WS message
- [ ] FR#16: No `droppedNoSession` references in frontend (`grep -r droppedNoSession frontend/src/` returns zero)
- [ ] AC#3: Frontend builds without type errors; full e2e verification in T15
