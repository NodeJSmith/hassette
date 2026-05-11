---
task_id: "T04"
title: "Wire WS signal subscriptions to app detail page and migrate existing call sites"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3"]
---

## Summary
Add parent-level WS signal subscriptions to `app-detail.tsx` so handler/job counts, last-fired timestamps, and health metrics auto-refresh. Add a subscription to `RecentLogsSection` in the overview tab. Migrate all 4 existing `useDebouncedEffect(signal.value, ...)` call sites to the new `useFilteredSignalRefetch` hook. Update the activity feed key to use `row_id` and add `aria-live` to the activity feed.

## Prompt
Wire WS events to the app detail page using the `useFilteredSignalRefetch` hook created in T02.

**1. Parent-level refetch in `frontend/src/pages/app-detail.tsx`:**

Import `useFilteredSignalRefetch` and `WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS` from `../hooks/use-filtered-signal-refetch`.

Access the signals: `const { invocationCompleted, executionCompleted } = useAppState();`

Add two `useFilteredSignalRefetch` subscriptions:
```typescript
useFilteredSignalRefetch(
  invocationCompleted,
  (events) => events?.some(e => e.app_key === appKey) ?? false,
  () => { listenersApi.refetch(); jobsApi.refetch(); },
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```
Same pattern for `executionCompleted`. The `listenersApi` and `jobsApi` are the return values from `useScopedApi` — use their `refetch` methods (check the exact variable names in `app-detail.tsx` around lines 164–171).

**2. Migrate existing call sites to `useFilteredSignalRefetch`:**

Replace the 4 existing `useDebouncedEffect(() => signal.value, ...)` patterns:

- `frontend/src/components/app-detail/overview-tab.tsx:262–270` — `RecentActivitySection`'s `invocationCompleted` subscription. Replace with `useFilteredSignalRefetch(invocationCompleted, filterFn, refetch, WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS)` where `filterFn = (events) => events?.some(e => e.app_key === appKey) ?? false`.
- `overview-tab.tsx:273–281` — same for `executionCompleted`.
- `frontend/src/components/app-detail/handlers-tab.tsx:141–149` — `ListenerDetail`'s `invocationCompleted` subscription. Replace with `useFilteredSignalRefetch` using the same filter pattern with the listener's `app_key`.
- `handlers-tab.tsx:256–264` — `JobDetail`'s `executionCompleted` subscription. Same.

After migration, remove the `useDebouncedEffect` import from these files if no other call sites remain.

**3. Overview tab `RecentLogsSection` subscription (`overview-tab.tsx`):**

In `RecentLogsSection`, add `useFilteredSignalRefetch` subscriptions for both `invocationCompleted` and `executionCompleted`, matching the `RecentActivitySection` pattern. Filter by `appKey`, debounce and refetch logs.

**4. Activity feed key fix (`overview-tab.tsx`):**

In the `ActivityRow` rendering (around line 309), replace the key:
```diff
- <ActivityRow key={`${entry.kind}-${entry.handler_name}-${entry.timestamp}`} entry={entry} />
+ <ActivityRow key={entry.row_id} entry={entry} />
```

**5. Accessibility — `aria-live` on activity feed:**

Add `aria-live="polite"` and `aria-atomic="false"` to the activity feed `<tbody>` element in `RecentActivitySection`.

**Frontend test updates:**
- `frontend/src/components/app-detail/overview-tab.test.tsx` — update `ActivityFeedEntry` fixtures to include `row_id` field (e.g., `row_id: "h-1"`, `row_id: "h-2"`)
- `frontend/src/test/handlers.ts` — update MSW mock handler for activity feed to include `row_id` in response data

## Focus
- `app-detail.tsx` uses `useScopedApi` for fetching listeners and jobs — check exact return variable names for the `refetch` method. It's likely destructured as `{ data: listeners, ... }` — look for how to access `refetch`.
- The `RecentActivitySection` and `RecentLogsSection` are defined inside `overview-tab.tsx` as function components, not separate files.
- When migrating existing `useDebouncedEffect` calls, preserve the exact filter logic — the `app_key` check must remain.
- The `useDebouncedEffect` hook itself should NOT be removed — it's still used elsewhere (e.g., search debounce). Only remove the import from files that no longer use it.
- Verify the `appKey` variable is accessible in each component's scope where you add the filter function.
- Run `cd frontend && npx vitest run` to verify existing tests pass plus any new assertions.

## Verify
- [ ] FR#1: `app-detail.tsx` has `useFilteredSignalRefetch` subscriptions for both `invocationCompleted` and `executionCompleted` that call `refetch()` on listeners and jobs APIs when events match the current `appKey`
- [ ] FR#2: `RecentActivitySection` in `overview-tab.tsx` uses `useFilteredSignalRefetch` (not `useDebouncedEffect`) and the activity feed key uses `entry.row_id`
- [ ] FR#3: `ListenerDetail` and `JobDetail` in `handlers-tab.tsx` use `useFilteredSignalRefetch` (not `useDebouncedEffect`)
- [ ] AC#1: Parent-level refetch updates handler/job counts and last-fired timestamps when WS events arrive for the current app
- [ ] AC#2: Activity feed shows new entries after WS events without page refresh
- [ ] Accessibility: `aria-live="polite"` and `aria-atomic="false"` are set on the activity feed `<tbody>` element
- [ ] AC#3: Invocation/execution history tables in handlers tab refetch on matching WS events
