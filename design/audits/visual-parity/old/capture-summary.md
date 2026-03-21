# Old UI Screenshot Capture Summary

Captured: 2026-03-21
Source: http://127.0.0.1:8126/ui/ (Hassette v0.23.0)
Browser: Chromium 1440x900, fullPage: true

## Dashboard

| File | Status | Notes |
|------|--------|-------|
| D1-dashboard-default.png | PASS | All 7 apps visible, 5 KPI cards, App Health grid, Recent Errors, session bar |
| D4-dashboard-session-bar.png | PASS | Shows "Hassette v0.23.0" and "Started 3/21/2026, 9:07:12 AM" |
| D5-dashboard-light-mode.png | PASS | Light theme applied via toggle |

## Apps List

| File | Status | Notes |
|------|--------|-------|
| A1-apps-all-tab.png | PASS | All (7) tab, full table with 7 apps + 2 instance sub-rows |
| A2-apps-running-tab.png | PASS | Running (6) tab filtered, garage_proximity excluded |
| A4-apps-multi-instance-expanded.png | PASS | new_remote_app expanded showing jessica_remote + tierra_remote |
| A5-apps-disabled-tab.png | PASS | Disabled (1) tab, only garage_proximity shown |
| A6-apps-table-structure.png | PASS | Column headers: App Key, Name, Class, Status, Error, Actions |

## App Detail — Running (OfficeButtonApp)

| File | Status | Notes |
|------|--------|-------|
| AD1-app-detail-header.png | PASS | Breadcrumb, title, "running" badge, Stop/Reload buttons |
| AD3-app-detail-health-strip.png | PASS | 4 KPI cards: Status, Error Rate, Handler Avg, Job Avg |
| AD4-app-detail-handlers-collapsed.png | PASS | 4 handler rows collapsed with call counts and avg times |
| AD5-app-detail-handler-expanded.png | PASS | First handler expanded showing 21 invocation rows |
| AD6-app-detail-invocation-table.png | PASS | Invocation table: Status, Timestamp, Duration, Error columns |

## App Detail — With Jobs (AndysTrackerApp)

| File | Status | Notes |
|------|--------|-------|
| AD7-app-detail-jobs-collapsed.png | PASS | 2 jobs collapsed: andys_tracker_job (cron) and run |
| AD8-app-detail-job-expanded.png | PASS | "run" job expanded showing 24 execution rows |
| AD9-app-detail-execution-table.png | PASS | Execution table: Status, Timestamp, Duration, Error columns |

## App Detail — Logs

| File | Status | Notes |
|------|--------|-------|
| AD10-app-detail-logs-section.png | PASS | Logs section with level filter, search, sort columns; 0 entries for this app |

## App Detail — Disabled

| File | Status | Notes |
|------|--------|-------|
| AD14-app-detail-disabled.png | PASS | GarageProximityApp with "disabled" badge, no action buttons, empty sections |

## App Detail — Multi-Instance

| File | Status | Notes |
|------|--------|-------|
| AD15-app-detail-multi-instance.png | PASS | RemoteApp with instance dropdown (jessica_remote/tierra_remote) |

## App Detail — Failed

| File | Status | Notes |
|------|--------|-------|
| AD11-app-detail-failed-error.skip | SKIP | No failed app in current HA data (Failed count is 0) |
| AD12-app-detail-failed-traceback.skip | SKIP | No failed app in current HA data (Failed count is 0) |

## Logs

| File | Status | Notes |
|------|--------|-------|
| L1-logs-default.png | PASS | 23 entries, all levels, all apps; shows INFO/ERROR/WARNING badges |
| L2-logs-error-filter.png | PASS | ERROR filter applied, 1 entry: laundry_room_lights |
| L7-logs-app-column.png | PASS | App column with clickable links (monarch_updater, laundry_room_lights, etc.) |

## Error Page

| File | Status | Notes |
|------|--------|-------|
| E1-error-404.png | PASS | Raw JSON response: {"detail":"Not Found"} — no styled error page |

## Layout

| File | Status | Notes |
|------|--------|-------|
| X1-layout-sidebar.png | PASS | Icon-only sidebar: logo, Dashboard, Apps, Logs nav items |
| X3-layout-alert-banner.skip | SKIP | No failed apps exist, so no alert banner is displayed |
| X4-layout-status-bar.png | PASS | Top bar: green "Connected" indicator + theme toggle icon |
| X6-layout-dark-mode.png | PASS | Dashboard in default dark mode |
| X7-layout-light-mode.png | PASS | Dashboard + sidebar in light mode |

## Totals

- **PASS**: 27 screenshots
- **SKIP**: 3 scenarios (no failed apps in current data)
- **TOTAL**: 30 scenarios inventoried
