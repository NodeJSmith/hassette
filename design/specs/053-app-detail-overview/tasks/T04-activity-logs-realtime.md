---
task_id: "T04"
title: "Add activity feed, logs section, and real-time updates"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#9", "FR#11", "FR#12", "AC#5", "AC#6", "AC#7"]
---

## Summary
Implement the recent activity and recent logs sections of the overview tab, and wire up real-time WebSocket updates. The activity section uses the new endpoint from T01 via `useScopedApi`. The logs section reuses the existing `getRecentLogs` endpoint. Real-time updates follow the established `useDebouncedEffect` pattern from the handlers tab.

## Prompt
Add the activity and logs sections to the overview tab component at `frontend/src/components/app-detail/overview-tab.tsx`.

### Recent Activity Section

Fetch data using `useScopedApi` with the `getAppActivity` endpoint function added in T01:

Note: The overview tab receives `instanceQs` (a query string like `?instance=0`) from the parent. Parse the instance index from this or receive it as a separate prop from `app-detail.tsx` (check how the handlers tab resolves `resolvedInstanceIndex` — it's derived in the parent and can be passed directly).

```
const activityApi = useScopedApi(
  (since) => getAppActivity(appKey, resolvedInstanceIndex, limit, since),
  { deps: [appKey, resolvedInstanceIndex] },
);
```

Render a compact table or list of recent invocations/executions. Each row: StatusShape (ok/err/warn based on status) + handler name (monospace) + duration + relative timestamp. Use `formatRelativeTime` and `formatDurationOrDash` from `../../utils/format` — do NOT rewrite these formatters.

**Reuse** `StatusShape` for status indicators. **Reuse** the status-to-kind mapping from `../../utils/status`.

Empty state: when there are no activity entries, render something minimal like "no recent activity" in muted text — NOT a full `EmptyState` component (that would be too heavy for a subsection).

### Recent Logs Section

**Reuse** the existing `getRecentLogs` endpoint with `{ app_key: appKey, limit: N }`. Fetch via `useScopedApi` or `useApi` (check which pattern the logs tab uses for app-scoped logs and follow it).

For rendering, evaluate whether `LogTable` from `../shared/log-table.tsx` can be used directly with a `limit` or `compact` mode. `LogTable` already accepts `appKey` and `showAppColumn` props. If `LogTable` is too full-featured for a subsection (it includes toolbar, filters, sorting), create a compact read-only variant that renders the same table markup without the toolbar chrome. Do NOT duplicate the row rendering logic — extract it or call `LogTable` with a prop that hides the toolbar.

If creating a compact variant is too invasive to `LogTable`, just render a simple table with the log data directly — level badge, timestamp, message. The logs tab is one click away for the full experience.

### Real-Time Updates

Wire up WebSocket-driven refetches following the exact pattern in `handlers-tab.tsx` lines 141-150:

```
const { invocationCompleted, executionCompleted } = useAppState();

useDebouncedEffect(
  () => invocationCompleted.value,
  500,
  () => {
    const events = invocationCompleted.value;
    if (!events) return;
    const matches = events.some((e) => e.app_key === appKey);
    if (matches) void activityApi.refetch();
  },
);
```

Do the same for `executionCompleted`. This ensures the activity feed updates in real time when new invocations/executions arrive for this app.

**Do NOT create new hooks or event handling patterns.** The `useDebouncedEffect` + `useAppState` signals are the established pattern.

### CSS

Add any needed CSS to `frontend/src/global.css` under the `ht-overview-*` namespace. Activity rows should use compact spacing (`--sp-2` vertical padding). Use `--font-mono` and `--fs-mono-sm` for data content. Use design tokens throughout — no raw values.

### Tests

Add to `frontend/src/components/app-detail/overview-tab.test.tsx`:
- Activity section renders data from the activity endpoint
- Activity section handles empty state
- Logs section renders recent log entries
- Logs section handles empty state
- Real-time refetch is triggered when invocationCompleted events match the app_key

Use MSW for endpoint mocking (the project standard per `project_msw_adoption` memory).

## Focus
**Critical reuse points:**
- `useScopedApi` — handles time-window scoping and reconnect-version refetching
- `useDebouncedEffect` — handles WebSocket event batching and debounced refetch
- `useAppState()` — provides `invocationCompleted` and `executionCompleted` signals
- `getRecentLogs` — existing endpoint, no new log fetching needed
- `formatRelativeTime`, `formatDurationOrDash` — existing formatters
- `StatusShape` — existing status indicator component

**Pattern to follow**: `ListenerDetail` in `handlers-tab.tsx` shows the exact `useScopedApi` + `useDebouncedEffect` wiring pattern — find the `function ListenerDetail` block where it calls `useScopedApi` for `getHandlerInvocations` and wires `useDebouncedEffect` on `invocationCompleted`. Copy it, adapted for the activity endpoint and app-level filtering (match on `app_key` instead of `listener_id`).

**LogTable consideration**: Check `log-table.tsx` carefully before deciding whether to reuse it directly or create a compact version. It renders toolbar, filters, and sorting chrome that may be too much for a subsection. If reusing, pass props that suppress the toolbar. If not reusing, keep the row rendering minimal — 3-4 columns, no interactivity.

## Verify
- [ ] FR#9: Recent activity section shows invocations and executions across all handlers, merged and sorted by time
- [ ] FR#11: Recent logs section shows app-scoped log entries
- [ ] FR#12 (invocations): Activity section refetches when `invocation_completed` WebSocket events arrive matching this app's `app_key`
- [ ] FR#12 (executions): Activity section refetches when `execution_completed` WebSocket events arrive matching this app's `app_key`
- [ ] AC#5: Recent invocations/executions appear in the activity section from the new backend endpoint
- [ ] AC#6: Recent app-scoped logs appear in the logs section
- [ ] AC#7: New invocations/executions appear automatically via WebSocket without manual refresh
