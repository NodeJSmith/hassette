# New UI Screenshot Capture Summary

Captured: 2026-03-21
Source: Preact SPA at http://127.0.0.1:8126/
All screenshots: fullPage: true

## Dashboard (4 captures)

| File | Description | Notes |
|------|-------------|-------|
| D1-dashboard-default.png | Dashboard with all apps, dark mode | All 7 apps visible in health cards, 5 stat cards at top |
| D4-dashboard-session-bar.png | Dashboard scrolled to bottom | No session bar present in new UI — full page shows Recent Errors section at bottom |
| D5-dashboard-light-mode.png | Dashboard in light mode | Light theme applied correctly |
| X6-layout-dark-mode.png | Dashboard in dark mode | Toggled back from light mode |

## Apps List (5 captures)

| File | Description | Notes |
|------|-------------|-------|
| A1-apps-all-tab.png | All tab active | 7 apps, table with Name/Status/Class/Instances/Actions columns |
| A2-apps-running-tab.png | Running tab filtered | 6 running apps shown |
| A4-apps-multi-instance-expanded.png | Multi-instance app (RemoteApp) | Shows "2" in Instances column; no expand/collapse mechanism exists in new UI |
| A5-apps-disabled-tab.png | Disabled tab filtered | GarageProximityApp only, no action buttons |
| A6-apps-table-structure.png | Table columns visible | Same as A1 — columns: Name, Status, Class, Instances, Actions (Stop/Reload) |

## App Detail — Running with Handlers (6 captures)

| File | Description | Notes |
|------|-------------|-------|
| AD1-app-detail-header.png | OfficeButtonApp full page | Breadcrumb, title with status badge, Stop/Reload buttons, health strip |
| AD3-app-detail-health-strip.png | Health strip visible | Status, Error Rate, Avg Duration, Last Activity cards |
| AD4-app-detail-handlers-collapsed.png | Handlers section collapsed | 4 handler rows with event descriptions and call counts |
| AD5-app-detail-handler-expanded.png | First handler expanded | Invocation table with Time/Duration/Status/Error columns, 21 rows |
| AD6-app-detail-invocation-table.png | Invocation table detail | Same expanded view showing all execution history |
| AD10-app-detail-logs-section.png | Logs section at bottom | Log viewer with level dropdown, search, empty table (0 entries at INFO level) |

## App Detail — With Jobs (3 captures)

| File | Description | Notes |
|------|-------------|-------|
| AD7-app-detail-jobs-collapsed.png | AndysTrackerApp jobs collapsed | 2 jobs: andys_tracker_job (cron, 0 runs) and run (1 run, 323ms avg) |
| AD8-app-detail-job-expanded.png | "run" job expanded | Execution table with 25 rows, all success |
| AD9-app-detail-execution-table.png | Execution table detail | Same expanded view with Time/Duration/Status/Error columns |

## App Detail — Multi-instance (1 capture)

| File | Description | Notes |
|------|-------------|-------|
| AD15-app-detail-multi-instance.png | RemoteApp detail | Shows "Instance 0" — no instance selector or multi-instance navigation visible |

## App Detail — Disabled (1 capture)

| File | Description | Notes |
|------|-------------|-------|
| AD14-app-detail-disabled.png | GarageProximityApp disabled | Status "disabled", no Stop/Reload buttons, 0 handlers, 0 jobs |

## Logs (3 captures)

| File | Description | Notes |
|------|-------------|-------|
| L1-logs-default.png | Default log viewer (INFO level) | 22 entries, App column present, ERROR row highlighted in red/pink |
| L2-logs-error-filter.png | ERROR level filter | 1 entry: laundry_room_lights "Error setting initial enabled state" |
| L7-logs-app-column.png | App column visible | Same as L1 — App column shows app names or dash for system logs |

## Error Page (1 capture)

| File | Description | Notes |
|------|-------------|-------|
| E1-error-404.png | 404 page | "404 / Page not found. / Back to Dashboard" link |

## Layout (3 captures)

| File | Description | Notes |
|------|-------------|-------|
| X1-layout-sidebar.png | Sidebar in dark mode | Icon-only sidebar: Dashboard, Apps, Logs nav items |
| X4-layout-status-bar.png | Top status bar | "Connected" indicator + theme toggle button |
| X7-layout-light-mode.png | Light mode layout | Sidebar + status bar in light theme |

## Notable Observations

1. **No session bar** — D4 requested session bar at bottom; new UI has no session bar equivalent
2. **No multi-instance expand** — A4 shows RemoteApp with "2" instances but no expand/collapse to see individual instances in the table
3. **No instance selector on detail page** — AD15 shows "Instance 0" but no UI to switch between instances
4. **Sidebar is icon-only** — no text labels, no Hassette logo text
5. **ERROR rows highlighted** — log entries with ERROR level get a pink/red background highlight
6. **Theme toggle persists** — dark/light mode toggle works and was left in dark mode after capture

## Total: 27 screenshots captured
