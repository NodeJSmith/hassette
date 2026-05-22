---
task_id: "T06"
title: "Migrate scoped pages (Handlers, Apps, AppDetail)"
status: "planned"
depends_on: ["T02", "T05"]
implements: ["FR#2", "FR#4", "AC#2", "AC#9"]
---

## Summary

Migrate the three page-level consumers of `useScopedApi` + `useFilteredSignalRefetch` to `useScopedQuery` + `useQueryInvalidator`. HandlersPage and AppsPage are straightforward replacements. AppDetailPage also replaces the hand-rolled stale-ref pattern with `placeholderData: keepPreviousData`. These are the highest-traffic pages and validate caching, cancellation, and debounced invalidation end-to-end.

## Prompt

### 1. Migrate `frontend/src/pages/handlers.tsx`

Read the full file. Current pattern (lines 52-71):
- Two `useScopedApi` calls: listeners and jobs
- Two `useFilteredSignalRefetch` calls: one for `invocationCompleted` → listeners, one for `executionCompleted` → jobs

Replace with:
```tsx
const { data: listeners, isPending: listenersLoading, error: listenersError } = useScopedQuery(
  ["all-listeners"],
  (since) => getAllListeners(since),
);
const { data: jobs, isPending: jobsLoading, error: jobsError } = useScopedQuery(
  ["all-jobs"],
  (since) => getAllJobs(since),
);

useQueryInvalidator(invocationCompleted, () => true, ["all-listeners"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS);
useQueryInvalidator(executionCompleted, () => true, ["all-jobs"], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS);
```

Update imports:
- Remove: `useScopedApi` from `../hooks/use-scoped-api`
- Remove: `useFilteredSignalRefetch`, `WS_DEBOUNCE_DELAY_MS`, `WS_DEBOUNCE_MAX_WAIT_MS` from `../hooks/use-filtered-signal-refetch`
- Add: `useScopedQuery` from `../hooks/use-scoped-query`
- Add: `useQueryInvalidator`, `WS_DEBOUNCE_DELAY_MS`, `WS_DEBOUNCE_MAX_WAIT_MS` from `../hooks/use-query-invalidator`

Update all `.value` reads and error displays throughout the file. The return type changes from signals to plain values.

### 2. Migrate `frontend/src/pages/apps.tsx`

Read the full file. Current pattern:
- One `useScopedApi` call for dashboard grid (line 132)
- Two `useFilteredSignalRefetch` calls (lines 134-148)
- Also imports `PRESET_WINDOW_SECONDS` from `use-scoped-api` (line 22)

Replace the scoped query and invalidation following the same pattern as handlers.tsx. Query key: `["dashboard-grid"]`.

Update the `PRESET_WINDOW_SECONDS` import to come from `../utils/time-window` instead of `../hooks/use-scoped-api`.

Note: this file's manifest access was already migrated in T05. Only the scoped query + invalidation changes here.

### 3. Migrate `frontend/src/pages/app-detail.tsx`

Read the full file. Current pattern:
- Two `useScopedApi` calls with `deps: [appKey, resolvedInstanceIndex]` (lines 78-83)
- Two `useFilteredSignalRefetch` calls with app-key filtering (lines 85-104)
- Stale-ref pattern with `useRef` (lines 106-111)

Replace scoped queries:
```tsx
const { data: listeners, isPending: listenersLoading } = useScopedQuery(
  ["app-listeners", appKey, resolvedInstanceIndex],
  (since) => getAppListeners(appKey, resolvedInstanceIndex, since),
  { placeholderData: keepPreviousData },
);
const { data: jobs, isPending: jobsLoading } = useScopedQuery(
  ["app-jobs", appKey, resolvedInstanceIndex],
  (since) => getAppJobs(appKey, resolvedInstanceIndex, since),
  { placeholderData: keepPreviousData },
);
```

Note: `useScopedQuery` may need an `options` parameter added to pass `placeholderData`. Read the T02 implementation of `useScopedQuery` to see if it supports forwarding extra `useQuery` options. If not, extend it to accept an optional `queryOptions` parameter that spreads into the `useQuery` call.

Replace invalidation:
```tsx
useQueryInvalidator(
  invocationCompleted,
  (events) => events?.some((e) => e.app_key === appKey) ?? false,
  ["app-listeners", appKey],
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
useQueryInvalidator(
  executionCompleted,
  (events) => events?.some((e) => e.app_key === appKey) ?? false,
  ["app-jobs", appKey],
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```

Remove the entire stale-ref block (lines 106-111). The `placeholderData: keepPreviousData` option provides the same UX — showing previous data while new data loads. Remove `useRef` import if no longer used.

Note: this file's manifest access was already migrated in T05. Only the scoped query + invalidation + stale-ref changes here.

### 4. Migrate test files

For each page test file (`handlers.test.tsx`, `apps.test.tsx`, `app-detail.test.tsx`):
- Read the full file
- Remove `vi.mock("../hooks/use-scoped-api")` and `vi.mock("../hooks/use-filtered-signal-refetch")` blocks
- Remove `fakeApiResult` helpers
- Use MSW handlers to control API responses
- Switch to async assertions (`await findByText(...)`, `waitFor(...)`)
- Test key scenarios: loading state, populated data, error display, empty state

## Focus

- `useScopedApi`'s `deps` option does NOT carry over. Dependencies (`appKey`, `resolvedInstanceIndex`) go into the query key — TanStack refetches automatically when any key segment changes.
- The invalidation key is SHORTER than the full query key. `["app-listeners", appKey]` invalidates all instance/preset variants via prefix matching. Do not include `resolvedInstanceIndex` or `preset` in the invalidation key.
- `apps.tsx` line 22 imports `PRESET_WINDOW_SECONDS` from `use-scoped-api` — update to import from `../utils/time-window`.
- `apps.tsx` line 184 uses `PRESET_WINDOW_SECONDS[effectiveTimePreset.value]` directly. After migration, `effectiveTimePreset` is still a signal read from `useAppState()` — the `.value` access stays for this usage (it's reading the signal directly, not via a hook return).
- AppDetailPage's `placeholderData: keepPreviousData` requires importing `keepPreviousData` from `@tanstack/preact-query`.
- If `useScopedQuery` (T02) doesn't accept extra options, extend it here. Add an optional third parameter: `options?: Partial<UseQueryOptions>` that spreads into the `useQuery` call. This is the only consumer that needs it.
- After this task, `useScopedApi` and `useFilteredSignalRefetch` still have component-level consumers (T07). Do NOT delete those hooks yet.

## Verify

- [ ] FR#2: navigating away from handlers/apps/app-detail and back within 30s serves cached data — verified by test asserting no additional MSW handler invocations on return navigation
- [ ] FR#4: changing `appKey` during an in-flight fetch aborts the previous request and only completes the new one — verified by test confirming no console errors and only the final query key's data is rendered
- [ ] AC#2: navigating apps → app-detail → apps shows cached data without network request — verified by test
- [ ] AC#9: navigating away during a fetch produces no errors or console warnings — verified by test
