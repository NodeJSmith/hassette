---
task_id: "T07"
title: "Add inline invocation log table on app detail page"
status: "planned"
depends_on: ["T06"]
implements: ["FR#17", "AC#8"]
---

## Summary
Add a full inline log table inside expanded invocation/job execution rows on the app detail page. When a user expands an invocation row, the system lazy-fetches that execution's log records and renders a LogTable in historical mode with local state. Handles empty states including retention-expired disambiguation.

## Prompt
1. In `frontend/src/components/app-detail/handler-invocations.tsx`, modify `InvocationDetail`:
   - Add a "Logs" section below the existing invocation metadata
   - Lazy-fetch: call `getLogsByExecution(inv.execution_id)` only when the row is expanded AND `inv.execution_id` is non-null
   - Render a `<LogTable>` with props:
     - `mode="historical"`
     - `useLocalState={true}` (prevents URL param clobbering with the main logs page)
     - `fetcher` — a function that calls `getLogsByExecution(inv.execution_id)`
     - `showAppColumn={false}` (redundant — we're already on the app detail page)
   - Show a loading state while fetching

2. Handle empty states:
   - If `inv.execution_id` is null: show "No execution ID — logs unavailable" (edge case: very old invocations before execution_id was added)
   - If the response has `retention_expired=true`: show "Logs for this execution were deleted by retention policy"
   - If the response has zero records and `retention_expired=false`: show "No logs recorded for this invocation"
   - If the response has `truncated=true`: show "Showing first {limit} of more records" with a link to `/logs?execution_id={id}` for the full view

3. Apply the same pattern to job execution rows if they have an `InvocationDetail`-equivalent expand view. Check `frontend/src/components/app-detail/` for job execution components and apply consistently.

4. Add a "View all logs" link that navigates to `/logs?execution_id={id}` — this is a secondary path alongside the inline table, useful for users who want the full logs page experience (sorting by different columns, wider view, etc.).

5. Update E2E tests in `tests/e2e/test_logs.py`:
   - Test expanding an invocation row shows the inline log table
   - Test that the log table contains records matching the execution_id
   - Test empty state when no logs exist
   - Test "View all logs" link navigates to the logs page with the correct filter

## Focus
- `InvocationDetail` at `handler-invocations.tsx:107` is a function component that receives `{ inv }` prop. The `inv` object has `execution_id` at line 130 (rendered as a `<pre>` element).
- The expand row pattern in this file (around line 51) uses `rowKey = inv.execution_id ?? "inv-{i}"`. Expansion state is managed by the parent `HandlerInvocations` component.
- `LogTable` needs `useLocalState={true}` to avoid two LogTable instances (the inline one and any on the logs page) from fighting over URL query params.
- The `getLogsByExecution` response is NOT a flat `LogEntry[]` — it's a wrapper with `{ records, truncated, retention_expired }`. The fetcher passed to LogTable needs to extract `records` and handle the metadata separately.
- Look at how other app-detail tabs handle lazy-fetching on expand — there may be an existing pattern to follow.

## Verify
- [ ] FR#17: Expanding an invocation row shows a full inline log table filtered to that execution, with sorting and level filtering
- [ ] AC#8: The log table appears with correct records; supports sorting and level filtering; handles empty/truncated/retention-expired states
