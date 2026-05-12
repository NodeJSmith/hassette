---
task_id: "T06"
title: "Add LogTable modal interface and execution_id filtering"
status: "planned"
depends_on: ["T05"]
implements: ["FR#16", "AC#7"]
---

## Summary
Extend the LogTable component to support three modes: live streaming (current), execution-filtered (logs page with URL param), and historical inline (for T07's app detail integration). Add execution_id URL param filtering to the logs page. Wire useScopedApi for time-range filtering on historical data. Fix several performance issues identified during review.

## Prompt
1. Add modal interface to `frontend/src/components/shared/log-table.tsx`:
   - New props: `fetcher?: (params: LogFetchParams) => Promise<LogEntry[]>`, `mode?: "live" | "historical"` (default "live"), `useLocalState?: boolean` (default false)
   - In `historical` mode:
     a. Use `fetcher` instead of `getRecentLogs` for initial data fetch
     b. Skip WS merge entirely — do not subscribe to `logs.version`
     c. Skip `updateLogSubscription()` call on level filter changes
     d. If `useLocalState=true`, use component-local signals for filter/sort state instead of URL query params (`useQueryParams`)
   - In `live` mode: existing behavior (REST fetch + WS merge, URL params)

2. Add `execution_id` URL param support to `frontend/src/pages/logs.tsx`:
   - Read `execution_id` from URL query params
   - When present: render LogTable in `historical` mode with a fetcher calling `getLogsByExecution(executionId)`. Show a "Viewing logs for execution {executionId}" banner with a "Clear filter" link that removes the param. Hide the execution_id column (redundant when filtering).
   - When absent: render LogTable in `live` mode (existing behavior). Show the execution_id column.

3. Wire `useScopedApi` time-window preset to the logs page REST fetch:
   - Add the time-window preset control (the dropdown used on other telemetry pages like handler invocations and job executions) to the logs page toolbar
   - When in live mode (no execution_id filter), pass the `since` param from `useScopedApi` to `getRecentLogs`
   - This enables the post-restart investigation scenario where historical logs older than the last restart are visible by changing the time window preset
   - Consider defaulting to "24h" instead of "since-restart" on the logs page specifically, since the primary use case is post-restart investigation (overflow finding from challenge review)

4. Add the conditional `execution_id` column to the table:
   - Show when not filtering by execution_id (live mode or filtered by other params)
   - Hide when filtering by execution_id (redundant)
   - Update `colCount` arithmetic in both the empty-state colSpan and expanded-row colSpan to account for the conditional column

5. Add "showing N of M" truncation indicator:
   - When `sorted.length > 500` (the render cap), show "showing 500 of {sorted.length}" in the toolbar instead of just `pluralize(filtered.length, ...)`

6. Performance fixes (non-required enhancements from challenge review — not needed for FR#16/AC#7 to pass, but should be done while the component is being modified):
   - Move `LogSortHeader` component definition outside of `LogTable` function body — it's currently defined as an arrow function inside the render scope, causing remounts on every WS message
   - Add 150ms debounce to the search input's `onInput` handler — currently every keystroke triggers URL navigation and full re-render. Use a local signal for the input value, debounce before `qp.set()`
   - Change `recheckTruncation` useEffect deps from `[sorted.length, sorted[0]?.seq, sorted[sorted.length-1]?.seq, recheckTruncation]` to `[sorted.length, recheckTruncation]` — avoids DOM scans on every WS append at the 500-row cap

7. Update `frontend/src/components/shared/log-table.test.tsx`:
   - Test historical mode: passes a custom fetcher, no WS merge, no URL params
   - Test execution_id column visibility toggle
   - Test truncation indicator when >500 entries
   - Update mock WsLogPayload data with new fields (execution_id, source_tier, instance_name, instance_index)

8. Update `frontend/src/pages/logs.test.tsx`:
   - Test execution_id URL param renders historical mode with banner
   - Test clearing the filter returns to live mode

## Focus
- `log-table.tsx` is 517 lines. The modal interface adds conditional logic but should not restructure the component — the rendering stays the same, only the data source and state management change.
- `useQueryParams()` at `log-table.tsx:177` is the URL state hook. In `useLocalState` mode, replace with `useSignal()` for each filter/sort param.
- `getRecentLogs` at `endpoints.ts:82-88` accepts `since?: number | null`. The `useScopedApi` hook resolves `since` from the time-window preset. Wire this through.
- `updateLogSubscription` at `log-table.tsx:211-213` sends a WS message to change the server's min_log_level for broadcast filtering. In historical mode, this must NOT fire — there's no live stream.
- `LogSortHeader` at `log-table.tsx:368` is the inner component to move out. It needs `sortConfig` and `handleSort` as props.
- The search debounce target is `log-table.tsx:449-455` — the `onInput` handler that calls `qp.set({ search: value || null })`.
- `recheckTruncation` deps are at `log-table.tsx:360-366`.

## Verify
- [ ] FR#16: Navigating to /logs?execution_id=<uuid> shows only that execution's log records in historical mode
- [ ] AC#7: Filtered view contains only matching records; clearing the filter returns to live mode
