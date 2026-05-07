---
task_id: "T05"
title: "Add global handlers page with handlers and jobs tabs"
status: "done"
depends_on: ["T03"]
implements: ["FR#9", "FR#11", "FR#18", "AC#6", "AC#14"]
---

## Summary
Create the new `/handlers` page with two tabs (Handlers, Jobs). The handlers tab uses the existing `getAllListeners` endpoint; the jobs tab calls the new global jobs endpoint from T03. Both tabs support client-side filtering by app, sorting by key metrics, and a tier toggle (app-only by default, with framework toggle). Also add the "dropped events" line to the dashboard System card and register the new page in sidebar nav, routing, and command palette.

## Prompt
**1. Create `frontend/src/pages/handlers.tsx`** — new page component:
- Two-tab layout: "handlers" tab and "jobs" tab
- Follow the existing page patterns (see `apps.tsx` or `logs.tsx` for structure)
- Use `useApi()` or `useScopedApi()` to fetch data

**Handlers tab:**
- Fetch via `getAllListeners()` from `endpoints.ts:110`
- Render a sortable table with columns: App, Handler, Invocations, Failed, Error Rate, Avg Duration, Max Duration
- Client-side filtering: app dropdown filter (populated from unique app_key values in the data)
- Client-side sorting: click column headers to sort
- Client-side tier toggle: default to `source_tier === "app"`, toggle includes `"framework"`
- Row click navigates to `/apps/{app_key}` with the handler method as a focus param (the app detail page already supports `focusMethod` via URL)
- Handle empty state: "No handlers registered."

**Jobs tab:**
- Add a new `getAllJobs()` function in `endpoints.ts` calling `GET /api/scheduler/jobs`
- Render a sortable table with columns: App, Job Name, Trigger, Executions, Failed, Timed Out, Next Run, Status
- Same filtering/sorting/tier toggle pattern as handlers tab
- For `next_run`: use `formatRelativeTime()`. Handle `next_run < now` on non-cancelled jobs by showing "overdue" (see Edge Cases in design doc)
- Row click navigates to `/apps/{app_key}` with the job focused
- Handle empty state: "No jobs scheduled."

**2. Update routing** — `frontend/src/app.tsx`:
- Add `<Route path="/handlers" component={HandlersPage} />` before the catch-all NotFoundPage route
- Import the new page component

**3. Update sidebar** — `frontend/src/components/layout/sidebar.tsx`:
- Add `{ path: "/handlers", label: "handlers", testId: "nav-handlers" }` to `NAV_ITEMS` between "apps" and "logs"

**4. Update command palette** — `frontend/src/components/layout/command-palette.tsx`:
- Add a "handlers" entry to the static pages list (follow the pattern of existing entries like "overview", "apps", "logs")

**5. Dashboard dropped events** — `frontend/src/components/dashboard/service-status-panel.tsx`:
- **Structural change**: The component currently returns `null` when `entries.length === 0` (line 110-113), hiding the entire panel when no services are degraded. Remove this early return so the panel always renders — the dropped events line must be visible even when all services are healthy.
- Add a "dropped events" line at the bottom of the panel (outside the entries loop) that always renders: reads `droppedOverflow`, `droppedExhausted`, `droppedNoSession`, `droppedShutdown` from `useAppState()`
- Shows "0 events dropped" in `--ink-3` (muted) when total is 0
- Shows "N events dropped" in `--warn` when total > 0
- The line links to `/diagnostics` (which T06 will create — use an `<a>` tag, the route will exist in the same PR)

**6. Styles** in `frontend/src/global.css`:
- Add styles for the sortable table: column headers with sort indicators, hover states
- Tab switching UI: follow the existing tab pattern from handlers-tab.tsx (which has handlers/jobs tabs within app detail)
- Tier toggle: small toggle/checkbox styled consistently with the design system

**Tests:**
- Component test: handlers page renders with handlers tab by default
- Component test: tab switching between handlers and jobs
- Component test: app filter narrows the displayed rows
- Component test: tier toggle shows/hides framework handlers
- Component test: dashboard dropped events line renders with correct text and styling
- E2E: navigate to /handlers via sidebar, verify data loads

## Focus
- The tab pattern within `handlers-tab.tsx` (which shows handlers and jobs within app detail) is a reference — but that's a master-detail layout, not a table. The global page should be a data table, closer to the apps page pattern in `apps.tsx`
- `getAllListeners()` in `endpoints.ts:110` currently passes no params — it will need a `since` param added for time-preset consistency (see overflow finding OVF-5). For now, fetch without `since` — this can be addressed in a follow-up
- `formatRelativeTime()` from `frontend/src/utils/format.ts` handles past timestamps — verify it produces reasonable output for "overdue" jobs
- The sidebar `NAV_ITEMS` is at line 96 of sidebar.tsx — order matters for visual layout
- Command palette pages are defined starting at line 25 of command-palette.tsx
- **STRUCTURAL CHANGE REQUIRED**: The `ServiceStatusPanel` at `service-status-panel.tsx` currently returns `null` when `entries.length === 0` (line 110-113) — meaning the entire panel is hidden when no services are degraded. The dropped events line must render ALWAYS, even when no services are degraded. This requires changing the component's render logic so it no longer early-returns null when there are zero degraded entries. The dropped events line goes at the bottom of the panel, outside the entries loop.

## Verify
- [ ] FR#9: The handlers tab shows all registered handlers across all apps, defaulting to app-tier with a framework toggle
- [ ] FR#11: The handlers and jobs tabs support filtering by app and sorting by columns
- [ ] FR#18: The dashboard System card always shows a dropped events count (0 or N) linking to diagnostics
- [ ] AC#6: The /handlers page exists with a handlers tab that is filterable, sortable, and has a tier toggle
- [ ] AC#14: The dashboard System card shows "0 events dropped" (muted) or "N events dropped" (warn), linking to /diagnostics
