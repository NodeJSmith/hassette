# Design: Real-Time UI Updates

**Date:** 2026-05-11
**Status:** archived
**Scope-mode:** hold

## Problem

The monitoring UI shows stale data once rendered. Handler invocation counts, job execution counts, health metrics, "last fired" timestamps, and activity tables freeze at their initial values and never update until the user manually refreshes the page. Relative timestamps like "5m ago" remain frozen indefinitely instead of ticking forward.

This is especially harmful when a user is monitoring after a deploy or watching during known activity — the UI appears inert, making it seem like nothing is firing. A monitoring UI that lies about system state erodes trust in its core purpose and forces users into a refresh-and-hope workflow.

## Goals

- Handler and job activity updates are visible in the UI within one second of occurrence, without page refresh
- Relative timestamps tick forward naturally on a periodic interval
- No degradation on busy systems — high event throughput must not cause render storms or excessive API calls
- Browser tabs left idle for hours recover to current state when the user returns

## Non-Goals

- No new WebSocket message types — the existing `invocation_completed`, `execution_completed`, and `app_status_changed` broadcasts carry sufficient data
- No changes to the WebSocket connection/reconnection infrastructure

## User Scenarios

### Operator: Home automation hobbyist

- **Goal:** Confirm handlers are firing correctly after deploying a configuration change
- **Context:** Just edited app config YAML and restarted; opens the app detail page to watch

#### Post-deploy monitoring

1. **Opens the app detail page for their app**
   - Sees: current handler list, invocation counts, health metrics, last-fired times
   - Then: waits for a triggering event (e.g., a light turns on)

2. **A handler fires in response to an entity state change**
   - Sees: invocation count increments, "last fired" updates to "just now", activity feed shows the new entry at the top
   - Decides: whether the handler behaved correctly (checks status, duration)
   - Then: either closes the tab (satisfied) or drills into the handler detail

3. **Continues watching for several minutes**
   - Sees: "just now" becomes "1m ago", then "2m ago" — timestamps tick naturally
   - Sees: subsequent handler fires appear in real time without interaction
   - Then: closes the tab when confident everything is working

#### Returning to a stale tab

1. **Left the app detail page open overnight**
   - Sees: after switching back to the tab, relative timestamps recalculate ("8h ago" instead of frozen "just now")
   - Sees: data refetches automatically on WebSocket reconnection
   - Then: current state is accurate without a manual refresh

## Functional Requirements

- **FR#1** When an invocation or execution event arrives via WebSocket for the currently viewed app, the app detail page refetches handler and job summary data (counts, last-fired timestamps, health metrics)
- **FR#9** When invocation or execution events arrive via WebSocket, the apps landing page refetches dashboard grid data (invocation counts, total runs, last activity timestamps, sparklines, error summaries)
- **FR#2** The activity feed on the overview tab appends new entries when matching invocation or execution events arrive
- **FR#3** The handlers tab detail tables (invocation history, execution history) refetch when matching events arrive
- **FR#4** All relative timestamps displayed in the UI re-render on a periodic interval so that displayed values like "5m ago" advance to "6m ago" without user interaction
- **FR#5** Components subscribing to WebSocket completion signals only re-render when the event matches the currently viewed app, not on every event from any app
- **FR#6** Activity feed entries have unique keys even when two entries share the same handler name and timestamp
- **FR#7** Refetches triggered by WebSocket events are debounced to prevent API hammering during rapid event bursts
- **FR#8** When the browser tab returns from a hidden/background state, relative timestamps immediately recalculate to reflect elapsed time

## Edge Cases

- Two invocations of the same handler complete within the same millisecond — activity feed keys must not collide
- A handler fires every second for an extended period — debouncing must cap refetch frequency, not queue unbounded requests
- WebSocket disconnects and reconnects — the existing `reconnectVersion` signal already triggers immediate refetches; the new signal subscriptions must not conflict with this path
- Browser tab hidden for hours — the relative time ticker pauses (existing behavior), but on return must immediately recalculate all visible timestamps
- Multiple app detail tabs open for different apps — each tab must only react to its own app's events

## Acceptance Criteria

- **AC#1** (FR#1) Handler invocation count, last-fired timestamp, and health metrics update within 1 second of a handler firing, without page refresh
- **AC#2** (FR#2) A new activity feed row appears at the top of the overview tab within 1 second of a handler firing
- **AC#3** (FR#3) The invocation/execution history table in the handlers tab shows new entries within 1 second
- **AC#4** (FR#4) A relative timestamp displayed as "5m ago" advances to "6m ago" within 60 seconds, without any user interaction
- **AC#5** (FR#5) On a system with 10 apps, a handler firing in App A does not cause a re-render in App B's detail page
- **AC#6** (FR#6) Two invocations of the same handler completing at the same Unix timestamp render as separate rows with no console key-collision warning
- **AC#7** (FR#7) During a burst of 50 handler firings in 5 seconds, the frontend makes at most 4 API refetch calls (debounced at 500ms with 1500ms max-wait)
- **AC#8** (FR#8) A browser tab left hidden for 30 minutes shows correct relative timestamps immediately upon returning to the foreground
- **AC#9** (FR#9) The apps landing page grid updates invocation counts, last activity timestamps, and sparklines within 1 second of a handler firing in any app

## Key Constraints

- Do not introduce new WebSocket message types — the existing `invocation_completed` and `execution_completed` payloads already contain `app_key` and are sufficient for filtering
- The `useDebouncedEffect` hook must not read signal `.value` in its `getValue()` callback at render time — this is the root cause of the re-render blast radius problem. The fix must avoid auto-subscribing to signals outside the debounce callback
- The `useRelativeTime` hook already exists and is wired to the tick signal — adopt it everywhere rather than building a new mechanism. Do not call `formatRelativeTime` directly from components
- The activity feed `rowid` must come from the database, not be synthesized client-side — client-side counters would reset on refetch and produce collisions

## Dependencies and Assumptions

- The backend `get_app_recent_activity` SQL query must be modified to include `rowid` in the SELECT clause
- The `ActivityFeedEntry` Pydantic model and generated TypeScript types must be extended with a `row_id` field
- The OpenAPI spec and frontend types must be regenerated after backend model changes
- Assumes the existing 30-second tick interval is acceptable for relative timestamp granularity (design/context.md specifies relative times as "4m ago", not "4m 23s ago")

## Architecture

### 1. Activity feed unique keys (#715)

**Backend:** Add `rowid` to the `UNION ALL` query in `telemetry_query_service.py:get_app_recent_activity()`. The SQLite `rowid` is unique per table but not across the UNION — prefix with kind to ensure uniqueness: `'h-' || hi.rowid` for handler invocations, `'j-' || je.rowid` for job executions. Add `row_id: str` field to `ActivityFeedEntry` in `telemetry_models.py`.

**Frontend:** After regenerating types, use `entry.row_id` as the React key in `overview-tab.tsx:309` instead of the composite `${kind}-${handler_name}-${timestamp}`.

**Accessibility:** Add `aria-live="polite"` and `aria-atomic="false"` to the activity feed `<tbody>` so screen readers announce new entries as they appear. This follows the existing pattern in `log-table.tsx:302` and `table-card.tsx:23`.

### 2. Relative timestamp ticking (#725)

**Adopt `useRelativeTime` everywhere.** Replace all direct `formatRelativeTime(ts)` calls in components with `useRelativeTime(ts)`. The hook already subscribes to `state.tick` via `useSubscribe`.

**Per-location migration plan** (hooks must be called at component top level, not inside plain functions or map callbacks):

- **`components/app-detail/handlers-tab.tsx`** — `handlerStatsCells()` (line 98) and `jobStatsCells()` (line 115) are pure helper functions, not components. Call `useRelativeTime(listener.last_invoked_at)` / `useRelativeTime(job.last_executed_at)` at the top of `ListenerDetail` / `JobDetail` respectively, and pass the resulting string into the stats cells function as a parameter. For `JobDetail` lines 271–273 (next run / fire at), call `useRelativeTime` at the top of `JobDetail` for both timestamps and use the computed strings in the conditional.
- **`components/app-detail/overview-tab.tsx`** (line 244) — `ActivityRow` is already a component; call `useRelativeTime(entry.timestamp)` at its top level.
- **`components/app-detail/overview-tab.tsx`** (line 334) — `LogRow` is already a component; call `useRelativeTime(entry.timestamp)` at its top level.
- **`components/app-detail/unified-handler-row.tsx`** (lines 64, 67) — already a component; call `useRelativeTime` at the top level for `next_run` and `fire_at` timestamps instead of computing inline.
- **`pages/apps.tsx`** (lines 159, 172) — row rendering is inline in a map; extract an `AppRow` component that calls `useRelativeTime` for `last_error_ts` and `last_activity_ts`.
- **`pages/handlers.tsx`** (line 79) — `formatNextRunValue()` is a data-mapping helper called during `jobToRow()`. The `UnifiedRow` type already has `next_run_ts: number | null`. Remove the pre-computed string and instead call `useRelativeTime(row.next_run_ts)` inside the row component (`UnifiedHandlerRow`) which already receives the raw timestamp.
- **`pages/diagnostics.tsx`** (line 111) — currently uses a `tick` prop threading workaround (`void _tick` to force re-render). Migrate to `useRelativeTime(service.retry_at)` and remove the tick-prop pattern.
- **`components/shared/log-table.tsx`** (line 418) — row rendering; call `useRelativeTime` in the row component.

**Tab visibility recovery:** The existing ticker in `App.tsx` already checks `document.hidden` before incrementing. Add a `visibilitychange` event listener in the same `useEffect` as the interval timer (with `removeEventListener` in the cleanup) that increments `state.tick` immediately when the document becomes visible, ensuring timestamps recalculate on tab return without waiting up to 30 seconds.

### 3. App detail page auto-refresh (#387)

**Parent-level refetch in `app-detail.tsx`:** Add `useDebouncedEffect` subscriptions to `invocationCompleted` and `executionCompleted` signals. When an event matches the current `appKey`, call `refetch()` on the listeners and jobs API calls. This updates the handler list sidebar (counts, last-fired timestamps) and propagates fresh data to all child tabs.

**Health strip:** Already derives from parent data — no separate subscription needed. When the parent refetches listeners/jobs, the health strip re-renders with fresh metrics.

**Overview tab activity feed:** Already has `useDebouncedEffect` subscriptions — no changes needed beyond the key fix (#715) and timestamp ticking (#725).

**Overview tab recent logs:** `RecentLogsSection` currently has no WS signal subscriptions. Add `invocationCompleted` and `executionCompleted` subscriptions calling `refetch()`, matching the `RecentActivitySection` pattern, so logs update alongside the activity feed.

**Handlers tab detail tables:** Already have `useDebouncedEffect` subscriptions for invocation/execution detail refetch — no changes needed.

### 4. Reduce re-render blast radius (#714)

**Problem:** `useDebouncedEffect(() => invocationCompleted.value, ...)` reads the signal value inside `getValue()`, which Preact's signal system auto-tracks at render time. Every WS event from any app triggers a re-render of every component using this pattern.

**Fix:** Refactor `useDebouncedEffect` to accept a signal directly rather than a `getValue()` function, using `effect()` from `@preact/signals` to subscribe outside the render cycle. Alternatively, use `useSignalEffect` (which runs outside render) to watch the signal and only trigger the debounced callback when the `app_key` filter matches.

The preferred approach: replace the `getValue()` pattern with a `useSignalEffect`-based wrapper that:
1. Subscribes to the signal via `useSignalEffect` (runs outside render — no re-render on every event)
2. Checks the `app_key` filter immediately inside the effect
3. Only schedules the debounced refetch callback if the filter matches
4. Maintains the existing debounce + max-wait semantics

Define a named constant `WS_DEBOUNCE_MAX_WAIT_MS = 1500` alongside the existing debounce delay. Extract a shared hook `useFilteredSignalRefetch(signal, filterFn, refetchFn, delayMs, maxWaitMs)`. All WS-triggered debounce subscriptions — both new and existing — must use this hook with `maxWaitMs` set to `WS_DEBOUNCE_MAX_WAIT_MS`. Without `maxWaitMs`, events arriving every 400ms reset the 500ms trailing timer indefinitely, causing zero refetches during sustained bursts. No inline patterns.

**Mandatory migration of existing call sites:** The following `useDebouncedEffect(() => signal.value, ...)` call sites must be replaced with `useFilteredSignalRefetch`:
- `overview-tab.tsx:262–270` — `invocationCompleted` subscription in `RecentActivitySection`
- `overview-tab.tsx:273–281` — `executionCompleted` subscription in `RecentActivitySection`
- `handlers-tab.tsx:141–149` — `invocationCompleted` subscription in `ListenerDetail`
- `handlers-tab.tsx:256–264` — `executionCompleted` subscription in `JobDetail`

### 5. Apps landing page auto-refresh (#387)

**Add the filtered-signal hook to `apps.tsx`:** Subscribe to `invocationCompleted` and `executionCompleted` signals. On any event (no app_key filter — the dashboard shows all apps), debounce and refetch `getDashboardAppGrid`. This updates invocation counts, total runs, last activity timestamps, sparklines, and error summaries.

The existing `appStatus` signal subscription for live status badges remains unchanged.

## Alternatives Considered

### Polling instead of WS-triggered refetch

Periodically poll the API (e.g., every 5 seconds) instead of reacting to WS events. Simpler but wasteful — most polls return unchanged data. The WS infrastructure already exists and carries the needed information. Rejected.

### Optimistic client-side updates from WS payload

Instead of refetching from the API after a WS event, update counts and timestamps directly from the WS payload data. Faster (no API round-trip) but fragile — the WS payload is a summary, not a complete state snapshot. Counts would drift if any event is missed. The debounced-refetch approach is more reliable and the 500ms latency is acceptable per the user's requirements. Rejected for now; could be layered on later as an optimization.

### Client-side unique IDs for activity feed keys

Generate unique keys client-side (e.g., `crypto.randomUUID()` or an incrementing counter) instead of adding `rowid` to the backend query. Simpler backend change (none), but keys would change on every refetch, causing unnecessary DOM reconciliation. Database `rowid` is stable across refetches. Rejected.

## Test Strategy

**Frontend unit tests:**
- `useRelativeTime` hook: verify it returns updated strings when `state.tick` increments
- Activity feed key uniqueness: verify `row_id` is used as key (snapshot or render test)
- `useFilteredSignalRefetch` hook (if extracted): verify it only fires callback when filter matches

**Integration tests:**
- Mock WS events with matching/non-matching `app_key` and verify refetch is called only for matches
- Verify debounce behavior: rapid events produce bounded refetch calls

**Backend tests:**
- `get_app_recent_activity`: verify `row_id` field is present and unique across handler and job entries with identical timestamps

**E2E tests:**
- Existing e2e suite covers app detail navigation — verify no regressions
- Manual verification: trigger a handler and observe the UI updating without refresh

## Documentation Updates

None — these are bug fixes and internal behavioral improvements. No new user-facing API surface.

## Impact

**Frontend files modified:**
- `frontend/src/hooks/use-debounced-effect.ts` — refactor or add filtered-signal variant
- `frontend/src/pages/app-detail.tsx` — add WS signal subscriptions for parent-level refetch
- `frontend/src/components/app-detail/overview-tab.tsx` — update activity key, replace `formatRelativeTime`
- `frontend/src/components/app-detail/handlers-tab.tsx` — replace `formatRelativeTime`
- `frontend/src/components/app-detail/unified-handler-row.tsx` — replace `formatRelativeTime`
- `frontend/src/components/shared/log-table.tsx` — replace `formatRelativeTime`
- `frontend/src/pages/apps.tsx` — replace `formatRelativeTime`
- `frontend/src/pages/handlers.tsx` — replace `formatRelativeTime`
- `frontend/src/pages/diagnostics.tsx` — replace `formatRelativeTime`
- `frontend/src/pages/apps.tsx` — add WS signal subscriptions for dashboard grid refetch, replace `formatRelativeTime`
- `frontend/src/App.tsx` — add `visibilitychange` listener for immediate tick on tab return

**Backend files modified:**
- `src/hassette/core/telemetry_query_service.py` — add `row_id` to activity feed query
- `src/hassette/core/telemetry_models.py` — add `row_id` field to `ActivityFeedEntry`

**Generated files (regenerated):**
- `frontend/openapi.json`
- `frontend/src/api/generated-types.ts`

<!-- Gap check 2026-05-11: 4 gaps included — overview-tab.test.tsx ActivityFeedEntry fixtures → T01/T04 Focus, test/handlers.ts MSW mock → T01/T04 Focus, use-debounced-effect.test.ts → T02 (new hook gets own tests), test_telemetry_query_service.py → T01 backend test -->

**Blast radius:** Low to moderate. Frontend changes are additive (new subscriptions, hook adoption). Backend change is a single query + model field addition. No database migrations needed (`rowid` is an implicit SQLite column).

## Open Questions

None.
