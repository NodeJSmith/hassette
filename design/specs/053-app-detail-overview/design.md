# Design: App Detail Overview Tab

**Date:** 2026-05-10
**Status:** approved
**Scope-mode:** expand
**Research:** /tmp/claude-mine-define-research-oMeZG0/brief.md

## Problem

The app detail page lands on the handlers tab with an empty right panel. There is no at-a-glance summary of how an app is doing — the user must click into individual handlers to see invocation history or errors. The page feels unfinished and disjointed. Users arrive with a question ("is this app healthy? what went wrong?") and must navigate through handler-by-handler views to answer it.

## Goals

- A user landing on any app sees its health, recent errors, and activity without clicking anything
- Failing handlers are surfaced prominently with error details and a one-click path to the handler detail view
- The overview is useful in all three common scenarios: error investigation, healthy-state check, and post-reload verification
- Recent activity across all handlers provides a timeline of what the app has been doing

## Non-Goals

- Lifecycle timeline (started/reloaded/crashed events) — natural follow-on but not phase 1
- Per-handler sparklines or activity visualization — deferred to a future enhancement
- Config preview on the overview — config tab is one click away
- Replacing the handlers tab — overview is a complement, not a replacement

## User Scenarios

### Jessica: Home automation hobbyist

- **Goal:** Quickly assess whether an app is healthy and investigate if something failed
- **Context:** Opens the hassette UI after something unexpected happened (a light didn't turn on, a notification didn't fire), or during a routine check after restarting the system

#### Error investigation

1. **Opens the apps page**
   - Sees: apps table with status column — garage_proximity shows an error in LAST ERROR
   - Decides: clicks garage_proximity to investigate
   - Then: navigates to `/apps/garage_proximity`

2. **Lands on the overview tab (default)**
   - Sees: error spotlight at top showing the failing handler with error type, message, and a link; handler health grid below showing all 8 handlers with status; recent activity timeline; recent logs
   - Decides: the error message tells her what happened — clicks the failing handler link to see the full traceback
   - Then: navigates to `/apps/garage_proximity/handlers/h-42` (handlers tab with handler pre-selected)

3. **Reviews handler detail**
   - Sees: full error banner with traceback, invocation history, stats
   - Decides: understands the root cause
   - Then: closes the tab

#### Healthy check

1. **Opens an app that's running fine**
   - Sees: overview tab with no error spotlight section (absent, not "no errors"), handler health grid all green, recent activity showing normal invocations, recent logs showing INFO entries
   - Decides: everything looks good
   - Then: closes the tab

#### Post-reload check

1. **Reloads an app and checks it's working**
   - Sees: overview tab showing recent activity — new invocations appearing since the reload, all successful
   - Decides: the reload worked
   - Then: moves on

## Functional Requirements

- **FR#1** The app detail page defaults to the overview tab when no tab is specified in the URL
- **FR#2** The overview tab displays an error spotlight section listing handlers and jobs that have failures or timeouts in the current time window
- **FR#3** The error spotlight shows up to 3 failing items expanded (with error type, error message, and handler/job name), with remaining items collapsed behind a "show N more" control
- **FR#4** Each error spotlight entry links to the handlers tab with that handler or job pre-selected in the URL
- **FR#5** The error spotlight section is absent (not rendered) when no handlers or jobs are failing
- **FR#6** The overview tab displays a handler health grid showing all handlers and jobs with their status, run count, and last error information
- **FR#7** The handler health grid orders failing items first, then items sorted by most recent activity
- **FR#8** Each handler health grid entry links to the handlers tab with that handler or job pre-selected
- **FR#9** The overview tab displays recent activity (invocations and executions) across all of the app's handlers and jobs, merged and sorted by time
- **FR#10** The recent activity data is provided by a new backend endpoint that accepts limit, since, and source_tier parameters
- **FR#11** The overview tab displays recent app-scoped log entries
- **FR#12** The overview tab updates in real time when invocation_completed or execution_completed events arrive for the app via WebSocket
- **FR#13** The tab bar order is: overview, handlers, code, logs, config
- **FR#14** The overview tab renders a mobile-appropriate layout below the mobile breakpoint

## Edge Cases

- **App with no handlers or jobs:** Overview shows empty state ("no handlers registered") — same as current handlers tab empty state
- **App with 20+ failing handlers:** Only 3 expanded in error spotlight, rest behind "show N more" — prevents page explosion
- **App with zero invocations (newly registered):** Activity section shows empty state; handler health grid shows all items with 0 runs
- **Time window change:** Overview refetches when the time preset selector changes (Since restart / 1h / 24h / 7d)
- **Multi-instance app:** Overview accepts instance_index parameter to scope data to a specific instance, consistent with existing tabs
- **WebSocket disconnection:** Overview displays stale data at reduced opacity, consistent with existing stale-data pattern
- **Very long error messages:** Error text in spotlight is truncated with ellipsis; full text visible in handler detail view

## Acceptance Criteria

- **AC#1** Navigating to `/apps/{appKey}` loads the overview tab (FR#1)
- **AC#2** When an app has failing handlers, the error spotlight section is visible with error details and links to handler detail (FR#2, FR#3, FR#4)
- **AC#3** When an app has no failing handlers, the error spotlight section is not rendered (FR#5)
- **AC#4** All handlers and jobs are visible in the handler health grid with status indicators and links (FR#6, FR#7, FR#8)
- **AC#5** Recent invocations and executions appear in the activity section, sourced from the new backend endpoint (FR#9, FR#10)
- **AC#6** Recent app-scoped logs appear in the logs section (FR#11)
- **AC#7** New invocations/executions appear automatically via WebSocket without manual refresh (FR#12)
- **AC#8** Tab bar shows overview as the first tab (FR#13)
- **AC#9** Overview renders appropriately on mobile viewports (FR#14)

## Key Constraints

- Error spotlight must cap expanded items at 3 to prevent page explosion with many failures
- No status colors on non-status elements — `--ok`/`--warn`/`--err` reserved for state communication only
- No left-border accents on error entries — use StatusShape + indentation per design context
- Error spotlight section is absent when nothing is failing (not "no errors found" — just absent)
- Backend endpoint must accept `limit`, `since`, and `source_tier` parameters consistent with existing telemetry endpoints
- Frontend must use `useScopedApi` for data fetching to integrate with time-preset and reconnect-version patterns

## Dependencies and Assumptions

- Existing `ActivityFeedEntry` Pydantic model in `telemetry_models.py` provides the response shape for the activity endpoint
- Existing `HandlerErrorRecord` and `JobErrorRecord` models provide error data for the spotlight
- Listeners and jobs data is already fetched at the app-detail page level — overview tab receives it as props
- WebSocket `invocation_completed` and `execution_completed` events carry `app_key` for filtering
- The `TelemetryQueryService` UNION ALL pattern (used by `get_per_app_activity_buckets`) is reusable for the new activity query
- Existing indexes (`idx_hi_time`, `idx_je_time`, `idx_listeners_app`, `idx_scheduled_jobs_app`) support the new query without migration

## Architecture

### Backend

**New method on `TelemetryQueryService`** (`src/hassette/core/telemetry_query_service.py`):

`get_app_recent_activity(app_key, instance_index, limit, since, source_tier)` — returns `list[ActivityFeedEntry]`. Uses the proven UNION ALL pattern from `get_per_app_activity_buckets()` with different SELECT columns and `ORDER BY timestamp DESC LIMIT :limit` instead of bucket aggregation. The `ActivityFeedEntry` model already exists in `telemetry_models.py`.

**New route** (`src/hassette/web/routes/telemetry.py`):

`GET /telemetry/app/{app_key}/activity` — query params: `instance_index: int | None`, `limit: int = Query(default=50, ge=1, le=500)`, `since: float | None`, `source_tier: str | None`. Response model: `list[ActivityFeedEntry]`. Follows the exact pattern of existing endpoints in the same file.

**Error data**: The error spotlight reuses error fields already present on `ListenerData` and `JobData` (`last_error_type`, `last_error_message`, `last_error_traceback`). No additional error endpoint needed — the data is already fetched at the page level and passed as props.

### Frontend

**New component** (`frontend/src/components/app-detail/overview-tab.tsx`):

Receives `listeners`, `jobs`, `appKey`, `instanceQs` as props (same data already fetched by `app-detail.tsx`). Fetches activity data via `useScopedApi` with the new endpoint. Fetches recent logs via `getRecentLogs({ app_key, limit })`.

Three sections:
1. **Error spotlight**: Filters `listeners` and `jobs` props for items with `failed > 0 || timed_out > 0`. Renders up to 3 expanded with error details, remainder collapsed. Each links to `/apps/{appKey}/handlers/{h|j}-{id}`.
2. **Handler health grid**: Renders all handlers and jobs from props in a compact grid using `StatusShape` + name + run count. Failing items sorted first. Each links to handlers tab.
3. **Recent activity + logs**: Two sub-sections using the new activity endpoint data and `getRecentLogs` data.

Real-time updates: `useDebouncedEffect` on `invocationCompleted` and `executionCompleted` signals from `useAppState()`, filtered by `app_key` match, triggering refetch of the activity endpoint.

**Route changes** (`app.tsx`): Add `/apps/:key/overview` route. Add `/apps/:key` default to `overview` instead of `handlers`.

**Tab changes** (`app-detail.tsx`): Add `"overview"` to `TabId` union. Change default from `"handlers"` to `"overview"`. Add `<Tab id="overview" label="overview" />` as first tab. Add conditional render branch for overview content.

**Schema regeneration**: `uv run python scripts/export_schemas.py` + `npx openapi-typescript openapi.json -o src/api/generated-types.ts` after backend endpoint is added.

## Alternatives Considered

**Auto-select first handler instead of overview tab**: Fills the empty panel but doesn't add diagnostic value. The user still has to mentally assemble the app's health picture from individual handler views. Rejected because it solves the symptom (empty panel) not the problem (no at-a-glance summary).

**Summary panel in the handler tab's empty state**: Make the unselected right panel show a summary instead of "Select a handler." Lighter-weight than a new tab but conflates two purposes — the handlers tab is for drill-down investigation, and mixing in overview content makes neither job well.

**Dashboard-style overview with charts**: KPI cards, sparklines, activity charts. More visually rich but risks the "monitoring dashboard" anti-pattern called out in the design context. The overview should answer diagnostic questions, not display ambient metrics.

## Test Strategy

**Backend**: Unit test for `get_app_recent_activity` using the existing `TelemetryQueryService` test pattern — seed the database with invocations and executions across multiple handlers, verify the merged/sorted output respects limit, since, and source_tier parameters.

**Frontend**: Unit tests for the overview tab component using the existing `HassetteHarness` test pattern — verify error spotlight rendering with varying failure counts (0, 1, 3, 5+), verify handler health grid ordering (failing first), verify activity and logs sections render data. Test the "show N more" expansion behavior. Test the empty state (no handlers registered).

**E2E**: Playwright test navigating to an app detail page, verifying the overview tab loads by default, error spotlight shows failing handlers, and clicking an error link navigates to the handlers tab with the handler selected.

## Documentation Updates

- Update `design/context.md` Component Inventory section to add the Overview Tab description
- Update `CLAUDE.md` if the tab order or default landing page is referenced

## Impact

**Files modified:**
- `src/hassette/core/telemetry_query_service.py` — new `get_app_recent_activity` method
- `src/hassette/web/routes/telemetry.py` — new `/telemetry/app/{app_key}/activity` route
- `frontend/src/app.tsx` — new route for `/apps/:key/overview`, default change
- `frontend/src/pages/app-detail.tsx` — `TabId` union, default tab, tab bar order, render branch
- `frontend/src/api/endpoints.ts` — new `getAppActivity` function

**Files created:**
- `frontend/src/components/app-detail/overview-tab.tsx` — new component
- `frontend/src/components/app-detail/overview-tab.test.tsx` — unit tests

**Regenerated:**
- `frontend/openapi.json` — updated OpenAPI spec
- `frontend/src/api/generated-types.ts` — updated TypeScript types

<!-- Gap check 2026-05-10: 1 gap included — app-detail.test.tsx:391 default tab assertion → T02 test updates -->

**Blast radius:** Low-medium. The default tab change affects all app detail navigation but is a URL-level change (existing bookmarks to `/apps/{key}/handlers` still work). No existing functionality is removed or modified.

## Open Questions

None — all questions resolved during discovery.
