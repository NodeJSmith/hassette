# Visual Parity Round 2 — Capture Summary

**Date:** 2026-03-21
**Source:** http://127.0.0.1:8126/ (Hassette Preact SPA)
**Method:** Playwright MCP full-page screenshots
**Total:** 27 screenshots captured

## Dashboard (4)

| File | Description |
|------|-------------|
| `D1-dashboard-default.png` | Dashboard in dark mode — KPI strip, App Health cards, Recent Errors, session bar |
| `D4-dashboard-session-bar.png` | Same view, session bar ("Hassette / Started") visible at bottom |
| `D5-dashboard-light-mode.png` | Dashboard after toggling to light mode |
| `X6-layout-dark-mode.png` | Dashboard after toggling back to dark mode |

## Apps List (5)

| File | Description |
|------|-------------|
| `A1-apps-all-tab.png` | All tab selected, 7 apps, full table with App Key/Name/Class/Status/Error/Actions |
| `A2-apps-running-tab.png` | Running tab selected, 6 apps filtered |
| `A4-apps-multi-instance-expanded.png` | new_remote_app chevron expanded, showing jessica_remote and tierra_remote sub-rows |
| `A5-apps-disabled-tab.png` | Disabled tab selected, showing only garage_proximity |
| `A6-apps-table-structure.png` | Back to All tab, collapsed chevron state |

## App Detail — OfficeButtonApp (6)

| File | Description |
|------|-------------|
| `AD1-app-detail-header.png` | Full page: breadcrumb, header with status badge, Stop/Reload buttons, health strip |
| `AD3-app-detail-health-strip.png` | Same page, health strip (Status/Error Rate/Handler Avg/Job Avg) |
| `AD4-app-detail-handlers-collapsed.png` | 4 handlers listed in collapsed state, 0 calls each |
| `AD5-app-detail-handler-expanded.png` | First handler expanded, invocation table with 21 rows visible |
| `AD6-app-detail-invocation-table.png` | Same expanded view, Time/Duration/Status/Error columns |

## App Detail — AndysTrackerApp (3)

| File | Description |
|------|-------------|
| `AD7-app-detail-jobs-collapsed.png` | 2 scheduled jobs in collapsed state (andys_tracker_job, run) |
| `AD8-app-detail-job-expanded.png` | "run" job expanded showing execution table with 28 rows |
| `AD9-app-detail-execution-table.png` | Same expanded view with Time/Duration/Status/Error columns |

## App Detail — Other States (3)

| File | Description |
|------|-------------|
| `AD10-app-detail-logs-section.png` | AndysTrackerApp page showing Logs section (0 entries, filter controls) |
| `AD14-app-detail-disabled.png` | GarageProximityApp — disabled state, no Stop/Reload buttons, Status: Disabled |
| `AD15-app-detail-multi-instance.png` | RemoteApp — instance switcher dropdown (jessica_remote/tierra_remote) |

## Logs (3)

| File | Description |
|------|-------------|
| `L1-logs-default.png` | Log Viewer with All Levels + All Apps dropdowns, 22 entries, App column with links |
| `L2-logs-error-filter.png` | ERROR level selected, 1 entry (laundry_room_lights error row highlighted pink) |
| `L7-logs-app-column.png` | All Levels restored, app column links visible (monarch_updater, laundry_room_lights) |

## Error + Layout (5)

| File | Description |
|------|-------------|
| `E1-error-404.png` | 404 page at /nonexistent — large "404" heading, "Back to Dashboard" link |
| `X1-layout-sidebar.png` | Dashboard — sidebar with Hassette logo, Dashboard/Apps/Logs nav icons |
| `X4-layout-status-bar.png` | Dashboard — "Connected" status bar at top with theme toggle |
| `X7-layout-light-mode.png` | Dashboard in light mode — full layout |

## Notes

- Theme was toggled back to dark mode after all captures as requested.
- All screenshots used `fullPage: true` to capture complete scrollable content.
- The multi-instance chevron expand (A4) required clicking the triangle character directly; clicking the cell navigated to the app detail page instead.
