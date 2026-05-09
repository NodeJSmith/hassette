# Brief: Overview page — keep, kill, or merge

**Date:** 2026-05-09
**Status:** explored

## Idea

Whether hassette needs a dedicated overview/dashboard page, or whether `/apps` should be the default landing page. The current overview shows a 7-cell stats strip, an app health table, and a recent errors table — but the sidebar already provides status-grouped apps with live status dots, and the user's actual workflow almost always goes straight to a specific app.

## Key Decisions Made

- **The overview page is a detour, not a destination.** The user's primary visit pattern is "did app X do thing Y?" — they already know which app they care about. The overview adds a click before getting to the answer.
- **Make `/apps` the default landing page.** The apps page already shows the app table with richer detail (status, runs, sparklines, last fired). It directly answers the question "which app do I care about?" and is one click from the answer.
- **The sidebar already handles the "is everything ok?" glance.** All-green status dots in the sidebar answer the health question before the main content even loads. The overview's app health table is redundant with this.
- **Stats strip and recent errors are not missed.** The user confirmed they wouldn't miss either if `/apps` were the landing page. System-level vitals (uptime, dropped events) could move to the status bar or `/diagnostics` if needed.
- **The overview may gain a few things merged into `/apps`** — "if anything." The decision is to start with `/apps` as-is and evaluate what's missing, rather than designing an overview page and hoping it's useful.

## Open Questions

- Should any overview-only data (stats strip, recent errors, system health alert) migrate to `/apps`, the status bar, or nowhere?
- **Context-ID-to-logs linking** (raised during grill): Could handler/job invocations carry a context ID that links to the corresponding log entries? This would make "what happened and why?" answerable from a single view. Separate feature, but it's the root cause of why the overview felt like it needed to exist — bridging the gap between "did it happen?" and "what were the logs?"

## Scope Boundaries

**In scope:**
- Make `/apps` the default route (redirect `/` to `/apps` or render apps page at `/`)
- Remove or deprecate the overview page
- Decide what (if anything) migrates from overview to apps page or status bar

**Explicitly out of scope:**
- Context-ID-to-logs linking (future enhancement, tracked separately)
- Redesigning the apps page layout
- Changes to the sidebar

**Deferred:**
- Whether the greeting concept ("Good evening.") has a home somewhere else (status bar? first-visit-only?)

## Risks and Concerns

- **Framework users expect a dashboard.** Every monitoring UI has one. Removing it is opinionated — but hassette's design is already opinionated (text-only nav, no icons, density-first). The risk is a user's first reaction being "where's the dashboard?" Mitigated by: the apps page IS the dashboard, it just doesn't pretend to be one.
- **Cross-app error visibility.** The overview's recent errors table shows errors from all apps in one place. Without it, a user who doesn't know which app errored has to scan the sidebar (which does show FAILING group) and then click into each failing app. The sidebar's FAILING group partially covers this, but doesn't show the error message.
- **Stats strip data becomes orphaned.** Runs/hour, success rate, dropped events, service health — these are computed by dedicated backend endpoints (`getDashboardKpis`, `getSystemStatus`). If the overview is removed, these endpoints and their frontend consumers become dead code unless the data migrates elsewhere.

## Codebase Context

- **Overview page:** `frontend/src/pages/dashboard.tsx` — fetches 5 API endpoints (KPIs, app grid, manifests, errors, system status). The most data-heavy page.
- **Apps page:** `frontend/src/pages/apps.tsx` — already has its own stats strip (TOTAL, RUNNING, FAILED, STOPPED, DISABLED, HANDLERS, RUNS/HR), status filter pills, search, and a sortable app table.
- **Sidebar:** `frontend/src/components/layout/sidebar.tsx` — shows status-grouped apps from `getManifests()`. No telemetry data.
- **Status bar:** `frontend/src/components/layout/status-bar.tsx` — shows time preset selector, connection status (pulse dot), telemetry degraded indicator, dropped events indicator, theme toggle. Already surfaces some system health signals.
- **Router:** `frontend/src/app.tsx` — `/` maps to `DashboardPage`. Changing the default route is a one-line change.
- **Backend endpoints that may become orphaned:** `getDashboardKpis`, `getDashboardAppGrid`, `getDashboardErrors` in `frontend/src/api/endpoints.ts`; corresponding routes in `src/hassette/web/routes/`.
