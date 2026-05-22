---
task_id: "T07"
title: "Migrate scoped components (ListenerDetail, JobDetail, RecentActivity)"
status: "planned"
depends_on: ["T02"]
implements: ["FR#5"]
---

## Summary

Migrate the three component-level consumers of `useScopedApi` + `useFilteredSignalRefetch` to `useScopedQuery` + `useQueryInvalidator`. These are sub-components of the app detail page — they show invocation/execution history for individual handlers and jobs. The pattern is identical to T06 but with entity-specific filter functions. Also fix the `WS_DEBOUNCE_MAX_WAIT_MS` import in `overview-tab.test.tsx`.

## Prompt

### 1. Migrate `frontend/src/components/app-detail/listener-detail.tsx`

Read the full file. Current pattern:
- One `useScopedApi` call with `deps: [listener.listener_id]` (lines 77-79)
- One `useFilteredSignalRefetch` with listener-specific filter (lines 84-90)

Replace with:
```tsx
const { data: invocations, isPending: loading } = useScopedQuery(
  ["handler-invocations", listener.listener_id],
  (since) => getHandlerInvocations(listener.listener_id, DETAIL_FETCH_LIMIT, since),
);

useQueryInvalidator(
  invocationCompleted,
  (events) => events?.some((e) => e.listener_id === listener.listener_id) ?? false,
  ["handler-invocations", listener.listener_id],
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```

Update imports: remove `useScopedApi` and `useFilteredSignalRefetch` imports, add `useScopedQuery` and `useQueryInvalidator` imports. Constants import changes from `../../hooks/use-filtered-signal-refetch` to `../../hooks/use-query-invalidator`.

Update `.value` reads and error displays throughout.

### 2. Migrate `frontend/src/components/app-detail/job-detail.tsx`

Same pattern. Current code at lines 60-77.

Replace with:
```tsx
const { data: executions, isPending: loading } = useScopedQuery(
  ["job-executions", job.job_id],
  (since) => getJobExecutions(job.job_id, DETAIL_FETCH_LIMIT, since),
);

useQueryInvalidator(
  executionCompleted,
  (events) => events?.some((e) => e.job_id === job.job_id) ?? false,
  ["job-executions", job.job_id],
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```

### 3. Migrate `frontend/src/components/app-detail/recent-activity-section.tsx`

Read the full file. Current pattern:
- One `useScopedApi` call with `deps: [appKey, resolvedInstanceIndex]` (lines 116-123)
- Two `useFilteredSignalRefetch` calls — one for `invocationCompleted`, one for `executionCompleted` (lines 128-142)

Replace with:
```tsx
const { data: activity, isPending: loading, error: activityError } = useScopedQuery(
  ["app-activity", appKey, resolvedInstanceIndex],
  (since) => getAppActivity(appKey, resolvedInstanceIndex, ACTIVITY_LIMIT, since),
);

useQueryInvalidator(
  invocationCompleted,
  (events) => events?.some((e) => e.app_key === appKey) ?? false,
  ["app-activity", appKey],
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
useQueryInvalidator(
  executionCompleted,
  (events) => events?.some((e) => e.app_key === appKey) ?? false,
  ["app-activity", appKey],
  WS_DEBOUNCE_DELAY_MS,
  WS_DEBOUNCE_MAX_WAIT_MS,
);
```

Note: the invalidation key is `["app-activity", appKey]` (no `resolvedInstanceIndex`) — prefix matching covers all instance variants.

### 4. Fix import in `frontend/src/components/app-detail/overview-tab.test.tsx`

This test file imports `WS_DEBOUNCE_MAX_WAIT_MS` from the hook being deleted:
```tsx
import { WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-filtered-signal-refetch";
```

Change to:
```tsx
import { WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-query-invalidator";
```

## Focus

- These components use `../../hooks/...` imports (two levels up), not `../hooks/...` like pages.
- The invalidation key for listener-detail and job-detail includes the entity ID (`listener.listener_id`, `job.job_id`). This is correct — each detail view only invalidates its own data.
- `recent-activity-section.tsx` has the `activityError` signal (line 119) — update to `error` from the query result. Also update the error display at line 150.
- `DETAIL_FETCH_LIMIT` and `ACTIVITY_LIMIT` are local constants in each component — they don't change.
- `listener-detail.tsx`, `job-detail.tsx`, and `recent-activity-section.tsx` have NO existing test files — no test migration needed for these components.
- After this task, `useScopedApi` and `useFilteredSignalRefetch` have ZERO remaining consumers. They are deleted in T09.

## Verify

- [ ] FR#5: all three components use `useQueryInvalidator` with `WS_DEBOUNCE_DELAY_MS` (500ms) and `WS_DEBOUNCE_MAX_WAIT_MS` (1500ms) — verified by grep confirming each component passes the correct constants; debounce timing correctness is covered by T02's timer-based unit tests of the hook itself
