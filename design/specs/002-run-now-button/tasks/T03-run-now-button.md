---
task_id: "T03"
title: "Add Run Now button to job detail panel"
status: "done"
depends_on: ["T02"]
implements: ["FR#8", "FR#11", "AC#7", "AC#8"]
---

## Summary
Add the frontend "Run Now" button to the job detail panel on the app detail page's handlers tab. This includes the API endpoint function, the button component with loading/error state, and the MSW test handler for frontend tests. The button follows the established `ActionButtons` loading pattern.

## Target Files
- modify: `frontend/src/api/endpoints.ts`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- modify: `frontend/src/test/handlers.ts`
- read: `frontend/src/api/client.ts`
- read: `frontend/src/components/shared/action-buttons.tsx`
- read: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- modify: `frontend/src/components/app-detail/handlers-tab.test.tsx`

## Prompt
### API endpoint function

Add `triggerJob` to `frontend/src/api/endpoints.ts`:

```typescript
export const triggerJob = (jobId: number) =>
  apiPost<{ status: string; job_id: number; job_name: string }>(`/scheduler/jobs/${jobId}/trigger`);
```

Follow the pattern of `startApp`/`stopApp`/`reloadApp` (lines 48-50). Use `apiPost` from `client.ts` (line 41).

### Run Now button in JobDetail

In `frontend/src/components/app-detail/job-detail.tsx` (line 61), add a "Run Now" button to the `extras` prop of `HandlerDetailLayout`. The button sits alongside the existing `nextRunText` content (lines 100-106) — wrap both in a fragment or container.

Follow the `ActionButtons` loading/error pattern from `frontend/src/components/shared/action-buttons.tsx` (lines 18-33):

1. `useSignal(false)` for loading state
2. `useSignal<string | null>(null)` for error state
3. An `exec` wrapper that sets loading, calls `triggerJob(job.job_id)`, catches errors, clears loading in `finally`
4. Button is disabled while `loading.value` is true
5. Error displayed inline below the button when `error.value` is non-null

The button should use the `Button` shared component (`frontend/src/components/shared/button.tsx`) with appropriate variant and size. Show a spinner icon or text change while loading.

The `extras` prop on `HandlerDetailLayout` (line 33 of `handler-detail-layout.tsx`) accepts `ComponentChildren` and renders between `chips` and `sourceLocation` (line 112).

### MSW test handler

Add a POST handler for `/api/scheduler/jobs/:id/trigger` to `frontend/src/test/handlers.ts`. Follow the pattern of the existing app action handlers (lines 47-71). Return a 202 response with `{ status: "accepted", job_id: <id>, job_name: "test-job" }`.

### Frontend tests

Add or extend tests in `frontend/src/components/app-detail/handlers-tab.test.tsx` (which already tests `JobDetail` rendering via `handlers-tab`). Test:

- "Run Now" button renders in the job detail panel
- Button enters loading state on click and is disabled
- Error message renders inline on 409 response
- Button re-enables after request completes

Use MSW request interception to simulate success and error responses.

## Focus
- `JobDetail` receives a `job` prop with `db_id` field — use `job.job_id` as the argument to `triggerJob()`.
- The `extras` prop currently renders a `<div>` with `nextRunText` (lines 100-106 of `job-detail.tsx`). Compose the Run Now button alongside this — don't replace it. A fragment `<>{nextRunContent}{runNowButton}</>` or a wrapper div works.
- `apiPost` (line 41 of `client.ts`) throws on non-2xx responses — the error message from the 409/500 response body's `detail` field is available via `err.message`. The `apiFetch` function (line 16) reads the JSON error and throws an `Error` with the detail text.
- The MSW handlers in `frontend/src/test/handlers.ts` use `http.post()` from `msw`. Existing POST handlers (lines 47-71) use `HttpResponse.json()` with a status code.
- There is no standalone `job-detail.test.tsx` — `JobDetail` is tested via `handlers-tab.test.tsx` which renders it within the `HandlersTab` component. Follow the existing test patterns there (e.g., `job-detail-20`, `job-detail-8` test IDs).
- The `Button` component has variants: `default`, `primary`, `success`, `warning`, `info`, `danger`. Size options: `default`, `sm`, `xs`. A `default` or `primary` variant at `sm` size is appropriate for "Run Now".

## Verify
- [ ] FR#8: "Run Now" button appears in the job detail panel on the handlers tab
- [ ] FR#11: Button is disabled while a trigger request is in flight
- [ ] AC#7: Button shows loading spinner during request and is disabled until complete
- [ ] AC#8: Error message displays inline below button on 409 response
