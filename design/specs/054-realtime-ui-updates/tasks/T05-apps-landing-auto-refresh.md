---
task_id: "T05"
title: "Wire WS signal subscriptions to apps landing page dashboard grid"
status: "planned"
depends_on: ["T02"]
implements: ["FR#9", "AC#9"]
---

## Summary
Add `useFilteredSignalRefetch` subscriptions to `apps.tsx` so the dashboard grid (invocation counts, total runs, last activity timestamps, sparklines, error summaries) auto-refreshes when any handler fires. Unlike the app detail page, the dashboard shows all apps, so the filter passes all non-null events.

## Prompt
Wire WS events to the apps landing page grid refetch.

**In `frontend/src/pages/apps.tsx`:**

Import `useFilteredSignalRefetch` and `WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS` from `../hooks/use-filtered-signal-refetch`.

Access the signals from `useAppState()` — it already destructures several signals around line 210. Add `invocationCompleted` and `executionCompleted` to the destructuring.

Add two `useFilteredSignalRefetch` subscriptions:
```typescript
useFilteredSignalRefetch(
  invocationCompleted,
  (events) => events !== null,
  () => void gridApi.refetch(),
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```
Same for `executionCompleted`. The `gridApi` is the return value from `useScopedApi((since) => getDashboardAppGrid(since))` — check the exact variable name at line ~214.

**Filter logic:** The dashboard shows all apps, so the filter is `(events) => events !== null` — any non-null event triggers a debounced refetch. This is deliberate: unlike app-detail which filters by `appKey`, the dashboard needs to update for any app's activity.

**No other changes needed in this file** — the `useRelativeTime` migration for `apps.tsx` is handled by T03 (extract `AppRow` component), and is independent of this task.

## Focus
- The `useScopedApi` return value in `apps.tsx` is destructured around line 214 as `const { data: gridData } = useScopedApi(...)`. Check if `refetch` is available in the destructured result — the `useScopedApi` hook at `hooks/use-scoped-api.ts` may return it as part of the API object.
- The existing `appStatus` signal subscription for live status badges is separate and must remain unchanged.
- This page may receive high event volume on busy systems (events from all apps). The `maxWaitMs: 1500` cap ensures the grid refetches at most every 1.5 seconds during sustained activity.
- Run `cd frontend && npx vitest run` after changes.

## Verify
- [ ] FR#9: `apps.tsx` has `useFilteredSignalRefetch` subscriptions for `invocationCompleted` and `executionCompleted` that trigger `refetch()` on the dashboard grid API
- [ ] AC#9: Dashboard grid data (invocation counts, last activity timestamps, sparklines) updates after WS events without page refresh
