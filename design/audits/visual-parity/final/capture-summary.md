# Final Visual Parity Screenshots

Captured: 2026-03-21
Source: http://127.0.0.1:8126/ (Preact SPA, post visual-parity fixes)
Total: 27 screenshots (all full-page PNG)

## Dashboard (4)

| File | Description |
|------|-------------|
| D1-dashboard-default.png | Dashboard with all apps, KPI strip, App Health grid, Recent Errors (dark mode) |
| D4-dashboard-session-bar.png | Same page showing session/footer bar at bottom |
| D5-dashboard-light-mode.png | Dashboard in light mode |
| X6-layout-dark-mode.png | Dashboard toggled back to dark mode |

## Apps List (5)

| File | Description |
|------|-------------|
| A1-apps-all-tab.png | All tab with full table (App Key, Name, Class, Status, Error, Actions) |
| A2-apps-running-tab.png | Running tab filtered (6 apps) |
| A4-apps-multi-instance-expanded.png | new_remote_app chevron expanded showing jessica_remote and tierra_remote sub-rows |
| A5-apps-disabled-tab.png | Disabled tab showing garage_proximity |
| A6-apps-table-structure.png | All tab, full page table structure |

## App Detail - Running with Handlers (6)

| File | Description |
|------|-------------|
| AD1-app-detail-header.png | OfficeButtonApp: breadcrumb, logo icon, status badge, action buttons |
| AD3-app-detail-health-strip.png | Health strip (Status, Error Rate, Handler Avg, Job Avg) |
| AD4-app-detail-handlers-collapsed.png | 4 handler rows in collapsed state |
| AD5-app-detail-handler-expanded.png | First handler expanded with invocation table (21 rows) |
| AD6-app-detail-invocation-table.png | Same view, invocation table with Time/Duration/Status/Error columns |

## App Detail - With Jobs (3)

| File | Description |
|------|-------------|
| AD7-app-detail-jobs-collapsed.png | AndysTrackerApp: 2 jobs collapsed (andys_tracker_job + run) |
| AD8-app-detail-job-expanded.png | run job expanded with execution table (25 rows) |
| AD9-app-detail-execution-table.png | Same view, execution table visible |

## App Detail - Other States (3)

| File | Description |
|------|-------------|
| AD10-app-detail-logs-section.png | Logs section on AndysTrackerApp (0 entries, filter controls visible) |
| AD14-app-detail-disabled.png | GarageProximityApp: disabled status, no handlers/jobs, no action buttons |
| AD15-app-detail-multi-instance.png | RemoteApp: instance switcher dropdown (jessica_remote/tierra_remote) |

## Logs (3)

| File | Description |
|------|-------------|
| L1-logs-default.png | Default log viewer with All Levels/All Apps dropdowns, 23 entries |
| L2-logs-error-filter.png | ERROR level filtered, 1 entry with pink highlight row |
| L7-logs-app-column.png | App column showing clickable links (monarch_updater, laundry_room_lights) |

## Error Page (1)

| File | Description |
|------|-------------|
| E1-error-404.png | 404 page with "Back to Dashboard" link |

## Layout (4)

| File | Description |
|------|-------------|
| X1-layout-sidebar.png | Sidebar with Hassette logo, Dashboard/Apps/Logs nav icons (dark) |
| X4-layout-status-bar.png | Status bar with green "Connected" indicator and theme toggle |
| X7-layout-light-mode.png | Light mode sidebar + status bar |

## Notes

- Theme was toggled back to dark mode after all captures
- Console shows a recurring 404 for `/hassette-logo.png` (broken image reference in sidebar) -- the Hassette logo `<img>` tag references a missing file, though the sidebar still renders with a broken image placeholder
- All pages load and render correctly via WebSocket connection
- App column links in logs page navigate to correct app detail pages
