---
task_id: "T02"
title: "Rewrite Apps page"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#7", "AC#2", "AC#4"]
---

## Summary
Rewrite the Apps page (`apps.md`) to document the current apps-centric landing page. This is the page users see first when opening the UI — it needs to explain the stats strip, searchable/sortable table, status filters, multi-instance expansion, and action buttons. It also establishes the monitoring workflow entry point (Alex scenario) and the troubleshooting entry point (Sam scenario).

## Prompt
Rewrite `docs/pages/web-ui/apps.md` (currently 55 lines). The Apps page is the UI landing page (`/` redirects to `/apps`).

Structure:

1. **Opening paragraph** — what the page shows and when to use it (monitoring check-in, finding a failing app)
2. **Hero screenshot** — `![Apps page](../../_static/web_ui_apps.png)`
3. **Stats strip** — document each stat: TOTAL, RUNNING, FAILED, STOPPED, DISABLED, HANDLERS, RUNS / HR. Explain these are scoped by the time-preset selector.

4. **App table** — document columns using a table:
   | Column | Description |
   | APP | App key + class name. Multi-instance apps show "N instances" with expand chevron |
   | STATUS | Lifecycle state with color indicator. Sortable (click header). Filterable via popover (running, failed, stopped, disabled, blocked) |
   | LAST ERROR | Most recent error message, truncated. "—" when healthy |
   | RUNS | Sparkline + total handler/job invocations in the time window |
   | LAST FIRED | Relative timestamp of most recent handler/job execution |
   | ACTIONS | Reload and Stop buttons per app |

5. **Search** — "search apps..." filters the table by app key and class name

6. **Multi-instance apps** — apps with multiple instances show an expand chevron (▶). Click to see individual instance rows. Each instance has its own status, runs, and actions.

7. **"auto" badge** — apps auto-detected from the app directory (not explicitly configured in `hassette.toml`) show an "auto" badge. Briefly explain the distinction.

8. **Mobile layout** — brief note that the table switches to card layout on narrow viewports.

9. **Related pages** — link to App Detail (for drill-down), Layout & Navigation (for the time-preset selector explanation)

Read `frontend/src/pages/apps.tsx` (291 lines) for the exact column definitions and behavior.

Do NOT reference "Dashboard", "Sessions", "session scope toggle", "bottom navigation", or "icon sidebar" anywhere.

## Focus
- The current `apps.md` is 55 lines and partially accurate — the status filter concept exists but the implementation changed from tabs to a column-filter popover on the Status header.
- The apps table now shows app_key + class_name in the APP column (e.g., "climate_controller ClimateController").
- Multi-instance apps (MotionLights, PresenceTracker) show "2 instances" and expand to show per-instance rows.
- The sparkline in the RUNS column is a mini activity graph — describe it as "activity sparkline" without over-explaining the implementation.
- The `![Apps page](../../_static/web_ui_apps.png)` screenshot shows all these features with real data.

## Verify
- [ ] FR#3: Every documented interaction (status filter, sort, search, expand multi-instance, reload/stop) exists in the current frontend
- [ ] FR#7: The monitoring workflow starts here — a reader understands how to spot a problem and where to go next (App Detail)
- [ ] AC#2: No references to "Dashboard page", "Sessions page", "session scope toggle", "bottom navigation", or "icon sidebar"
- [ ] AC#4: "Related pages" section links to App Detail for drill-down, completing the monitoring entry point
