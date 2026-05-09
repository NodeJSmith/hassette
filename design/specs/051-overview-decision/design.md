# Design: Remove overview page and default to /apps

**Date:** 2026-05-09
**Status:** archived
**Scope-mode:** hold
**Research:** design/specs/051-overview-decision/brief.md

## Problem

The overview page adds a navigation step between opening the UI and reaching the information the user needs. The user's primary visit pattern is app-specific ("did X happen? why didn't Y fire?"), so landing on a dashboard that summarizes all apps delays the answer. The sidebar already provides at-a-glance health status via status-grouped app entries, making the overview's app health table redundant with information visible on every page.

## Goals

- The root URL (`/`) takes the user directly to the apps list with no intermediate page
- All overview-only code (page component, endpoints, CSS, tests) is removed
- Shared endpoints used by other pages are preserved
- The sidebar navigation reflects the removal cleanly

## Non-Goals

- Redesigning the apps page layout or adding overview-only data to it
- Adding context-ID-to-logs linking (future enhancement identified during grill)
- Relocating the greeting concept to another surface
- Changing the sidebar's app registry behavior

## User Scenarios

### App author: Technical hobbyist running hassette

- **Goal:** Diagnose whether a specific automation ran correctly
- **Context:** Opens the UI after noticing unexpected behavior or at a scheduled time to verify

#### Check if a scheduled job ran

1. **Opens hassette URL**
   - Sees: apps page with status indicators, run counts, sparklines, last fired times
   - Decides: which app to investigate based on run counts and timing
   - Then: clicks into the app for handler/job detail

#### Investigate a failure

1. **Opens hassette URL**
   - Sees: apps page; sidebar shows FAILING group if any app has errors
   - Decides: clicks the failing app in sidebar or table
   - Then: views handler detail, logs tab for diagnostics

## Functional Requirements

- **FR#1** Navigating to `/` redirects to `/apps`
- **FR#2** The `/apps` route continues to render the apps page at its own path
- **FR#3** The sidebar navigation no longer includes an "overview" link
- **FR#4** The overview page component is removed and no longer routable
- **FR#5** Backend endpoints used exclusively by the overview page are removed
- **FR#6** Backend endpoints shared with other pages are preserved

## Edge Cases

- **Bookmarked `/` URL:** Redirects to `/apps` transparently. No broken bookmark.
- **Direct link to `/` in external references:** Same redirect behavior. No 404.
- **E2E tests that navigate to `/`:** Must be updated to expect redirect to `/apps` or navigate directly to `/apps`.

## Acceptance Criteria

- **AC#1** Loading `/` in a browser results in the apps page being displayed (FR#1, FR#2)
- **AC#2** The sidebar shows "apps" as the first nav item with no "overview" entry (FR#3)
- **AC#3** No route matches the former overview page path (FR#4)
- **AC#4** The apps page, diagnostics page, and all other pages function identically after the change (FR#6)
- **AC#5** No orphaned backend routes, frontend API functions, or CSS classes remain from the overview page (FR#5)

## Key Constraints

- `getDashboardAppGrid` is consumed by `apps.tsx` — this endpoint and its backend route must be preserved.
- `getSystemStatus` is consumed by `diagnostics.tsx` — this endpoint must be preserved.
- The `AlertsBar` component (boot issues + degraded services) currently lives in `dashboard.tsx` — evaluate whether this should migrate to the apps page or be dropped.

## Dependencies and Assumptions

- No external systems depend on the overview page.
- The apps page already has its own stats strip, search, filters, and sortable table — no new UI work is needed for it to serve as the landing page.
- The sidebar's active-link highlighting derives from the current route — the redirect must result in `/apps` being the active route, not `/`.

## Architecture

### Route change

In `frontend/src/app.tsx`, replace the `/` → `DashboardPage` route with `<Redirect to="/apps" />` (wouter's `Redirect` component). This allows full deletion of `dashboard.tsx` — no wrapper component needed.

### Removals

| Artifact | Path | Action |
|---|---|---|
| Overview page component | `frontend/src/pages/dashboard.tsx` | Delete |
| Overview CSS | `frontend/src/global.css` — `.ht-overview-*` classes | Delete |
| Sidebar nav link | `frontend/src/components/layout/sidebar.tsx` — "overview" entry | Remove |
| Dashboard KPIs endpoint (frontend) | `frontend/src/api/endpoints.ts` — `getDashboardKpis` | Delete |
| Dashboard errors endpoint (frontend) | `frontend/src/api/endpoints.ts` — `getDashboardErrors` | Delete |
| Dashboard KPIs route (backend) | `src/hassette/web/routes/` — KPI aggregation route | Delete |
| Dashboard errors route (backend) | `src/hassette/web/routes/` — recent errors route | Delete |
| Design context overview section | `design/context.md` — "Overview (Dashboard)" section | Remove and note apps as landing page |
| Overview-specific utilities | `frontend/src/utils/app-data.ts` or similar — if overview-only | Check and remove if orphaned |
| Framework summary endpoint (frontend) | `frontend/src/api/endpoints.ts` — `getFrameworkSummary` | Delete (consumer `framework-health.tsx` already deleted) |
| Framework summary route (backend) | `src/hassette/web/routes/` — `dashboard/framework-summary` | Delete |
| Activity endpoint (backend) | `src/hassette/web/routes/` — `GET /telemetry/dashboard/activity` | Delete (no frontend consumer) |
| Command palette overview entry | `frontend/src/components/shared/command-palette.tsx` — hardcoded "Overview" item | Remove or rename to "Apps" |
| Dashboard e2e tests | `tests/e2e/test_dashboard.py` | Delete entirely (tests reference deleted components; already broken) |
| Dashboard frontend tests | `frontend/src/pages/dashboard.test.tsx` (~380 lines) | Delete; migrate `TelemetryDegradedBanner` coverage |
| Not-found page copy | `frontend/src/pages/not-found.tsx` — "Back to dashboard" label | Update to "Back to apps" |

### Preservations

| Artifact | Path | Reason |
|---|---|---|
| `getDashboardAppGrid` | `frontend/src/api/endpoints.ts` | Used by `apps.tsx` |
| `getSystemStatus` | `frontend/src/api/endpoints.ts` | Used by `diagnostics.tsx` |
| App grid backend route | `src/hassette/web/routes/` | Serves `getDashboardAppGrid` |
| Health/system status route | `src/hassette/web/routes/` | Serves `getSystemStatus` |

### AlertsBar decision

The `AlertsBar` component shows boot issues and degraded services. It's currently overview-only. Drop it — the diagnostics page covers this; the status bar already shows degraded indicators; the sidebar's FAILING group surfaces app-level failures.

### TelemetryDegradedBanner migration

The `TelemetryDegradedBanner` component (distinct from `AlertsBar`) shows a banner when telemetry writes are failing. Move it to the layout shell (`app.tsx`) so it renders on all pages — this is a system-level signal that shouldn't be page-specific. Migrate its test coverage from `dashboard.test.tsx` to the layout test file.

## Alternatives Considered

**Keep overview but make it minimal** — A stripped-down overview with just a greeting and system state sentence. Rejected because: the user confirmed the overview is slower than going straight to `/apps`, and the greeting doesn't answer any diagnostic question.

**Render apps page at both `/` and `/apps`** — Avoids a redirect but creates two canonical URLs for the same content (bad for browser history, active link highlighting, and bookmarks). A redirect is cleaner.

## Test Strategy

- **E2e tests:** Delete `tests/e2e/test_dashboard.py` entirely (already broken — references deleted components). Update `TITLE_MAP` in `test_navigation.py` to remove the `/` → `"Dashboard - Hassette"` entry. Update brand-link assertion that expects URL ending in `/$` to expect `/apps`. Update any other tests navigating to `/` to expect redirect to `/apps`.
- **Frontend unit tests:** Delete `dashboard.test.tsx` (~380 lines). Migrate `TelemetryDegradedBanner` test coverage to layout tests. Verify apps page tests still pass.
- **Backend tests:** Remove tests for deleted routes (`dashboard/kpis`, `dashboard/errors`, `dashboard/framework-summary`, `dashboard/activity`). Verify preserved routes still work.
- **Manual verification:** Load `/` in browser, confirm redirect to `/apps`. Verify sidebar highlights "apps" with no "overview" entry. Verify command palette has no "Overview" entry. Check all other pages still work.

## Documentation Updates

- Remove the "Overview (Dashboard)" section from `design/context.md`
- Add a note that `/apps` is the default landing page
- Update the "Sidebar" section to reflect "overview" link removal

## Impact

**Files affected:** ~10-15 files across frontend (page, router, sidebar, CSS, endpoints, tests) and backend (routes, tests).
**Blast radius:** Low — the overview page is leaf code with no downstream dependents. The only risk is orphaning shared utilities or endpoints, mitigated by the preservation list above.
**Breaking changes:** None for API consumers. The `/` route changes behavior (redirect vs page render) but this is a UI-only change.
