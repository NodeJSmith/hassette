# Design: Frontend Data Parity

**Date:** 2026-05-07
**Status:** approved
**Scope-mode:** hold

## Problem

The monitoring UI surfaces a fraction of the data the backend computes. Job detail panels lack error context that handler panels have. Duration breakdowns (min/max) and successful invocation counts are computed by the backend but invisible. There is no way to see all scheduled jobs across apps without clicking into each one. Internal service health, boot issue details, and telemetry drop counters are compressed into badges and banners with no drill-down.

An operator diagnosing a slow handler, a failing job, or a degraded service currently has to piece together information from multiple views or fall back to logs. The backend already has the answers — the frontend just doesn't ask for them.

## Goals

- Job detail panels display the same error and duration fields as handler detail panels (parity checklist: last_error_type/message/ts, min/max/avg duration, successful count, expandable traceback)
- All handlers and jobs are viewable on a single page without navigating to individual apps
- The system diagnostics page displays service status, boot issues, and drop counters from existing backend data
- An operator can identify which handler is slowest and which job is failing from the global view alone

## Non-Goals

- Activity feed redesign (separate future PR)
- Session history UI (concept being removed)
- New WebSocket subscription types (existing broadcasts are sufficient)
- Changes to the config page
- Surfacing `entity_id`, `topic`, `handler_summary`, or `predicate_description` on handler detail — these were deliberately cut as redundant with `registration_source` and `human_description`
- Surfacing `di_failures` count — too niche; the data is available in invocation history if needed

## User Scenarios

### Operator: Hassette user (technical hobbyist or developer)

- **Goal:** Diagnose and verify automation health from the browser
- **Context:** Arrives with a question already in mind, wants to find the answer and close the tab

#### Diagnosing a slow handler

1. **Opens the global handlers view**
   - Sees: all handlers across all apps, sorted by avg duration or filterable
   - Decides: which handler looks slow based on avg/max duration and invocation count
   - Then: clicks the handler row to see details

2. **Reviews handler duration breakdown**
   - Sees: min, avg, max duration alongside invocation count, success/fail/timeout split
   - Decides: whether the handler is consistently slow or occasionally spikes
   - Then: drills into invocation history if needed, or adjusts the automation

#### Investigating a failing job

1. **Opens the global jobs view**
   - Sees: all jobs across all apps with status, next run, error indicators
   - Decides: which job is failing based on error banner and fail/timeout counts
   - Then: clicks the job to see the last error without drilling into execution history

2. **Reviews job error context**
   - Sees: last error type, message, and expandable traceback directly on the job detail pane
   - Decides: whether this is a transient issue or a code bug
   - Then: navigates to the code tab or fixes the automation

#### Checking system health after a restart

1. **Opens the system diagnostics page**
   - Sees: each internal service with its current status and readiness phase
   - Decides: whether all services are healthy or something is stuck
   - Then: checks boot issues for warnings, reviews drop counters to see if telemetry was lost during startup

2. **Reviews a degraded service**
   - Sees: the service in cooling state with a relative retry timestamp ("retry in 3m")
   - Decides: whether to wait for the retry or investigate the root cause
   - Then: checks the service's exception details shown inline

## Functional Requirements

- **FR#1** Job detail panels display the last error type, message, and timestamp when the job has failed at least once
- **FR#2** Job detail panels display an expandable traceback for the last error
- **FR#3** The job data model includes minimum and maximum execution duration alongside the existing average
- **FR#4** Handler detail panels display the minimum and maximum invocation duration alongside the existing average
- **FR#5** Handler detail panels display the count of successful invocations
- **FR#6** Handler detail panels display the count of cancelled invocations when non-zero
- **FR#7** Job detail panels display the count of successful executions
- **FR#8** Job detail panels visually distinguish timed-out executions from failed executions in the stats row
- **FR#9** A global view exists showing all registered handlers across all apps, defaulting to app-tier with a toggle to include framework-tier
- **FR#10** A global view exists showing all scheduled jobs across all apps with live scheduling data (next run time, jitter, cancelled state), defaulting to app-tier with a toggle to include framework-tier
- **FR#11** The global handlers and jobs views support filtering by app and sorting by key metrics
- **FR#12** A system diagnostics page displays each internal service with its current status, readiness phase, and role
- **FR#13** Services in a cooling/retry state display the retry time as a relative timestamp that refreshes on WebSocket updates
- **FR#14** The diagnostics page displays all boot issues with severity, label, and full detail text
- **FR#15** The diagnostics page displays telemetry drop counters broken down by category (overflow, exhausted, no session, shutdown)
- **FR#16** The diagnostics page displays telemetry health status and error handler failure count
- **FR#17** Handler error banners on the detail pane include an expandable traceback section (currently shows type and message only)
- **FR#18** The dashboard system summary card always displays a dropped telemetry events count (zero or non-zero), linking to the diagnostics page for the category breakdown

## Edge Cases

- Jobs that have never executed have no error or duration data — detail pane should show "no executions yet" rather than zeros
- A job may be cancelled but still have historical error data — show the error context even on cancelled jobs if it exists
- Services may transition states rapidly during startup — the diagnostics page should handle rapid WebSocket updates without flickering
- Drop counters can be zero for all categories — show the section but with a "no drops" state rather than hiding it
- The global jobs endpoint needs to aggregate across apps without the per-app scheduler heap enrichment becoming a bottleneck — heap snapshot should be taken once, not per-app
- The global jobs endpoint has a brief inconsistency window between the DB query and heap snapshot (same race as the per-app endpoint at `telemetry.py:258-260`). A job cancelled between reads may appear active with a stale `next_run`. Accepted — millisecond window. The frontend must handle `next_run < now` on a non-cancelled job by showing "overdue" rather than a negative countdown
- The framework-tier toggle on the global view may return a large number of internal handlers — the table should handle 100+ rows without performance issues
- Boot issues may not exist (clean startup) — the diagnostics section should show a positive "clean startup" state
- Telemetry DB unavailable when diagnostics page loads — the telemetry health panel should show degraded state (existing pattern: catch `DB_ERRORS`, return 503 with `degraded: true`); boot issues and service status are independent of the DB and should still render
- Scheduler service unavailable when global jobs page loads — DB rows should still render without live heap enrichment (next_run/fire_at/jitter will be absent); this follows the existing per-app jobs endpoint pattern which logs a warning and returns DB-only data
- WebSocket disconnected while on diagnostics page — service status panel shows last known state with a stale indicator; reconnection resumes live updates automatically via the existing WebSocket reconnection logic

## Acceptance Criteria

- **AC#1** A job that has errored displays its last error type, message, and expandable traceback on the detail pane (FR#1, FR#2)
- **AC#2** Job detail stats rows show min, avg, and max duration when executions exist (FR#3)
- **AC#3** Handler detail stats rows show min, avg, and max duration (FR#4)
- **AC#4** Handler stats rows include successful and cancelled (when > 0) counts (FR#5, FR#6)
- **AC#5** Job stats rows include successful count and visually separate timed_out from failed (FR#7, FR#8)
- **AC#6** A "handlers" page exists at a navigable route with a handlers tab showing all handlers across apps, filterable by app, sortable by duration/invocations/errors, defaulting to app-tier with a framework toggle (FR#9, FR#11)
- **AC#7** The same page has a jobs tab showing all jobs across apps with live next_run/fire_at/jitter data, filterable and sortable, defaulting to app-tier with a framework toggle (FR#10, FR#11)
- **AC#8** The system diagnostics page shows all internal services with status, role, and readiness phase, updating in real time via WebSocket (FR#12)
- **AC#9** A service in cooling state shows a relative retry timestamp (e.g., "retry in 3m") that refreshes on WebSocket updates (FR#13)
- **AC#10** Boot issues are listed with severity, label, and full detail — or a "clean startup" indicator if none exist (FR#14)
- **AC#11** Drop counters are displayed per category with labels and counts (FR#15)
- **AC#12** Telemetry health and error handler failure count are displayed (FR#16)
- **AC#13** Handler error banners include an expandable traceback (FR#17)
- **AC#14** The dashboard System card shows "0 events dropped" when no drops have occurred, and "N events dropped" with warn styling when drops > 0, linking to the diagnostics page in both cases (FR#18)

## Key Constraints

- `entity_id`, `topic`, `handler_summary`, and `predicate_description` must NOT be surfaced on handler detail panes — these were deliberately removed as redundant with `registration_source` and `human_description` in prior work
- The session concept is being removed — do not build session history or session-dependent features
- All UI must follow `design/context.md` tokens: `--bg-surface` for cards, `--err`/`--err-bg` for error states, Geist Mono for all data values, compact density (10-12px vertical padding), no left-border accents, no emoji
- Status indicators use shape + color (filled circle for ok, triangle for warn, square for err) per the existing `StatusShape` component
- New pages must be added to the sidebar navigation and command palette

## Dependencies and Assumptions

- The `job_executions` database table already stores `error_type`, `error_message`, and `error_traceback` columns — no migration needed
- `ServiceStatusData` is already broadcast over WebSocket via `Topic.HASSETTE_EVENT_SERVICE_STATUS` — the diagnostics page subscribes to existing broadcasts
- The `GET /api/bus/listeners` endpoint already returns all listeners globally — no new endpoint needed for global handlers
- Drop counters are already exposed via `GET /api/telemetry/status` — the diagnostics page calls the existing endpoint
- `SystemStatusResponse` from `GET /api/health` already includes `services_running` — `ServiceInfoResponse` must be extended with `role`, `ready_phase`, and `retry_at` to support the diagnostics page cold-load; WebSocket broadcasts provide live updates afterward
- The design context file (`design/context.md`) provides all required design tokens

## Architecture

### Backend changes

**JobSummary model extension** (`src/hassette/core/telemetry_models.py`): Add `last_error_message`, `last_error_type`, `last_error_ts`, `min_duration_ms`, and `max_duration_ms` fields to `JobSummary`.

**Job summary query** (`src/hassette/core/telemetry_query_service.py`): Extend `get_job_summary()` with:
- A LEFT JOIN subquery on `job_executions` to fetch the most recent error (same pattern as `get_listener_summary()` lines 303-307)
- `MIN(duration_ms)` and `MAX(duration_ms)` aggregates alongside the existing `AVG` and `SUM`

**Handler summary query**: Add `MIN(duration_ms)` and `MAX(duration_ms)` to `get_listener_summary()` — the `ListenerWithSummary` model already has `min_duration_ms` and `max_duration_ms` fields but the query doesn't populate them (they default to 0.0). New min/max fields on both handlers and jobs must use `float | None = None` (no `COALESCE`) — `None` means "never executed," `0.0` means "executed in under 1ms." This follows the established `last_invoked_at: float | None` pattern. The existing `COALESCE(MIN(...), 0.0)` in handler queries should be updated to drop the COALESCE.

**Global jobs endpoint** (`src/hassette/web/routes/`): Create a new route (replacing the tombstoned `scheduler.py`) that:
1. Calls a new `get_all_jobs_summary()` method on `TelemetryQueryService` — a single query with no `app_key` filter, consistent with `get_all_app_summaries()`
2. Takes a single scheduler heap snapshot via `get_all_jobs()`
3. Enriches DB rows with live heap data (next_run, fire_at, jitter, cancelled) using the same pattern as the per-app endpoint in `telemetry.py:214-270`

**Handler traceback in summary**: Add `last_error_traceback` to `ListenerWithSummary` model and populate it from the existing LEFT JOIN subquery that already fetches `last_error_message` and `last_error_type`.

**Schema regeneration**: Run `export_schemas.py` and regenerate TypeScript types after model changes.

### Frontend changes

**Handler detail pane** (`frontend/src/components/app-detail/handlers-tab.tsx`):
- Add `successful` count to stats row
- Add `cancelled` count to stats row (conditional — only when > 0)
- Replace single "Avg" duration with min / avg / max display
- Add expandable traceback section to error banner

**Job detail pane** (same file, `JobDetail` component):
- Add error banner matching the handler pattern (last_error_type, last_error_message, expandable traceback)
- Add `successful` count to stats row
- Visually separate `timed_out` from `failed` (already shown separately, but clarify the distinction)
- Add min / avg / max duration display
- Handle "no executions yet" empty state

**Global handlers page** (`frontend/src/pages/handlers.tsx`): New page at `/handlers` with two tabs:
- **Handlers tab**: Calls `GET /api/bus/listeners` (existing), renders a sortable/filterable table with app name, handler method, invocation counts, error rate, avg/max duration. Click navigates to app detail with handler focused.
- **Jobs tab**: Calls the new global jobs endpoint, renders a sortable/filterable table with app name, job name, trigger type, execution counts, next run, status. Click navigates to app detail with job focused.

**Tier filtering** is client-side for both tabs: the endpoints return all tiers (both `ListenerWithSummary` and `JobSummary` already carry a `source_tier` field), and the component filters in-memory. Default: app-tier only; toggle includes framework-tier. This requires `gather_all_listeners()` in `utils.py` to drop its hardcoded `source_tier="app"` filter so it returns both tiers. The new global jobs endpoint similarly returns all tiers.

**System diagnostics page** (`frontend/src/pages/diagnostics.tsx`): New page at `/diagnostics` with sections:
- **Services panel**: Two-phase initialization — seeds from `GET /api/health` on mount (which returns `ServiceInfoResponse` with name, status, role, ready_phase, retry_at), then subscribes to `service_status` WebSocket broadcasts for live updates. This ensures the panel renders immediately even when all services are stable. `ServiceInfoResponse` must be extended with `role`, `ready_phase`, and `retry_at` fields (currently only has `name` + `status`). Renders each service with StatusShape, name, role, status, readiness phase. Services in cooling state show a relative retry timestamp ("retry in 3m") that refreshes when new WebSocket updates arrive.
- **Boot issues panel**: Calls `GET /api/health` (shared with the services panel fetch), renders boot issues with severity badge, label, and detail text. Shows "clean startup" when empty.
- **Telemetry health panel**: Reads drop counters from `useAppState()` signals (already populated by the global 30s poller in `useTelemetryHealth`). No additional fetch needed — the status bar already consumes these same signals.

**Dashboard System card** (`frontend/src/components/dashboard/service-status-panel.tsx`): Add a "dropped events" line that always renders — shows "0 events dropped" in muted styling or "N events dropped" in `--warn` when non-zero. Links to `/diagnostics` page. Reads from the existing `droppedOverflow`/`droppedExhausted`/`droppedNoSession`/`droppedShutdown` signals in app state.

**Navigation**: Add "handlers" and "diagnostics" to the sidebar nav (between existing entries: overview, apps, **handlers**, logs, **diagnostics**, config) and command palette registration.

**Routing**: Add routes in `app.tsx` using the existing `wouter` pattern.

## Alternatives Considered

**Embed diagnostics in the existing dashboard** — The dashboard overview panel already shows services as a summary card. Adding full service detail, boot issues, and drop counters would bloat the dashboard and conflict with its "answer the question fast" design principle. A separate diagnostics page keeps the dashboard focused on app health and gives system internals room to breathe.

**Separate pages for global handlers and global jobs** — Two distinct pages would mean two sidebar entries and two mental models. A single "handlers" page with tabs keeps the navigation compact and uses the term already established throughout the UI. Handlers and jobs are both "wiring" — the same operator question ("what's running across all my apps?") spans both.

**Add min/max duration to the backend but not the frontend** — Exposing the data without rendering it would be incomplete. Duration variance (high max with low avg = occasional spikes) is the most actionable insight from min/max; hiding it defeats the purpose.

## Test Strategy

**Backend**: Unit tests for the extended `get_job_summary()` query verifying last_error fields and min/max duration are populated correctly. Test the global jobs endpoint returns enriched data from all apps. Test edge cases: jobs with no executions, jobs with only successful executions (no error data), cancelled jobs with historical errors.

**Frontend**: Component tests for the new stats row fields (successful, cancelled, min/max duration). Test the error banner with traceback expansion on job detail. Test the global handlers page with tab switching, app filtering, tier toggle, and sorting. Test the diagnostics page sections: services with various states including cooling with retry timestamp, boot issues present/absent, drop counters with zero/non-zero values.

**E2E**: Playwright tests for navigating to the new pages via sidebar, verifying data loads, and testing the tab switching on the global view.

## Documentation Updates

- Add the new pages to the sidebar nav documentation in `design/context.md` Component Inventory section
- Update `CLAUDE.md` if new test patterns emerge

## Impact

**Backend files:**
- `src/hassette/core/telemetry_models.py` — add fields to `JobSummary`
- `src/hassette/core/telemetry_query_service.py` — extend `get_job_summary()` and `get_listener_summary()` queries; add `get_all_jobs_summary()` method
- `src/hassette/web/models.py` — add `last_error_traceback` to `ListenerWithSummary`; extend `ServiceInfoResponse` with `role`, `ready_phase`, `retry_at`
- `src/hassette/web/routes/` — new global jobs route (replace tombstone)
- `src/hassette/web/utils.py` — remove hardcoded `source_tier="app"` from `gather_all_listeners()`
- `frontend/openapi.json` — regenerated
- `frontend/src/api/generated-types.ts` — regenerated

**Frontend files:**
- `frontend/src/components/dashboard/service-status-panel.tsx` — dropped events line
- `frontend/src/components/app-detail/handlers-tab.tsx` — extended stats rows, error traceback
- `frontend/src/pages/handlers.tsx` — new global handlers/jobs page
- `frontend/src/pages/diagnostics.tsx` — new system diagnostics page
- `frontend/src/app.tsx` — new routes
- `frontend/src/components/layout/sidebar.tsx` — new nav entries ("handlers", "diagnostics")
- `frontend/src/api/endpoints.ts` — new API functions
- `frontend/src/global.css` — styles for new components

**Blast radius**: Moderate. Backend query changes affect existing handler/job detail views (additive — new fields only). New pages and routes are additive. No breaking changes to existing endpoints or components.

## Open Questions

None — all design decisions resolved during discovery.
