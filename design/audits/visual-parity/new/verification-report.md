# New UI Screenshot Verification Report

Verified: 2026-03-21
Total screenshots in new/: 27 PNG files

## 1. Page/State Correctness

| File | Expected Content | Verdict | Notes |
|------|-----------------|---------|-------|
| D1-dashboard-default.png | Dashboard, dark mode, all apps | PASS | 5 stat cards (Apps 7, Error Rate 0.0%, Handlers 30, Jobs 11, Uptime 0h 3m), App Health grid with 7 apps, Recent Errors section, sidebar visible |
| D4-dashboard-session-bar.png | Dashboard scrolled to session bar | FAIL | Identical to D1 -- no scroll or session bar visible. Capture summary acknowledges new UI has no session bar, but the screenshot is a pixel-perfect duplicate of D1 rather than a distinct capture |
| D5-dashboard-light-mode.png | Dashboard in light mode | PASS | Light background, moon icon in theme toggle, all content visible |
| X6-layout-dark-mode.png | Layout in dark mode | PASS | Dark theme, sun icon toggle, sidebar + status bar visible. Content is dashboard (same as D1) which is acceptable for a layout screenshot |
| X1-layout-sidebar.png | Sidebar navigation | FAIL | Identical to D1 and X6 -- same pixel content. Should isolate/highlight the sidebar specifically, or at minimum be a distinguishable capture |
| X4-layout-status-bar.png | Top status bar | FAIL | Identical to D1, X1, X6 -- same pixel content. Should isolate/highlight the status bar |
| A1-apps-all-tab.png | Apps list, All tab | PASS | "all 7" tab active, 7 app rows with Name/Status/Class/Instances/Actions columns, Stop/Reload buttons. Low resolution but readable |
| A2-apps-running-tab.png | Apps list, Running tab | PASS | "running 6" tab active, 6 apps shown, GarageProximityApp excluded |
| A4-apps-multi-instance-expanded.png | Multi-instance app expanded | WARN | Shows RemoteApp with "2" in Instances column but no expand/collapse mechanism -- identical to A1/A6. Capture summary acknowledges this. Low resolution |
| A5-apps-disabled-tab.png | Disabled tab filtered | PASS | "disabled 1" tab active, only GarageProximityApp shown, no action buttons |
| A6-apps-table-structure.png | Table column structure | FAIL | Identical to A1 -- same pixel content, same tab, same data. No distinct value |
| AD1-app-detail-header.png | App detail header (OfficeButtonApp) | PASS | Breadcrumb "Apps / OfficeButtonApp", title with "running" badge, Stop/Reload buttons, health strip, handlers section. Low resolution but readable |
| AD3-app-detail-health-strip.png | Health strip KPIs | FAIL | Identical to AD1 -- same pixel content. Should isolate the health strip or show a different scroll position |
| AD4-app-detail-handlers-collapsed.png | Handlers collapsed | FAIL | Identical to AD1 and AD3 -- same pixel content |
| AD5-app-detail-handler-expanded.png | First handler expanded | PASS | Handler expanded showing invocation table with ~21 rows (Time/Duration/Status/Error columns), all success. Full page captured including other collapsed handlers, jobs section, and logs at bottom |
| AD6-app-detail-invocation-table.png | Invocation table detail | FAIL | Identical to AD5 -- same pixel content |
| AD10-app-detail-logs-section.png | Logs section | FAIL | Identical to AD5 and AD6 -- same pixel content. Logs section is visible at the very bottom but this is the same full-page capture, not scrolled to the logs |
| AD7-app-detail-jobs-collapsed.png | Jobs collapsed (AndysTrackerApp) | PASS | Breadcrumb "Apps / AndysTrackerApp", 0 handlers, 2 jobs collapsed: andys_tracker_job (cron, 0 runs) and run (1 run, 323ms avg, 6m ago), logs section with 0 entries |
| AD8-app-detail-job-expanded.png | Job expanded | PASS | "run" job expanded showing execution table with ~25 rows, Time/Duration/Status/Error columns, all success. Low resolution but readable |
| AD9-app-detail-execution-table.png | Execution table detail | FAIL | Identical to AD8 -- same pixel content |
| AD14-app-detail-disabled.png | Disabled app detail | PASS | GarageProximityApp with "disabled" status, no Stop/Reload buttons, 0 handlers, 0 jobs, empty logs |
| AD15-app-detail-multi-instance.png | Multi-instance app detail | PASS | RemoteApp with "running" badge, "Instance 0", 1 handler, 0 jobs. Low resolution. No instance selector visible |
| L1-logs-default.png | Log viewer, default | PASS | "Log Viewer" title, INFO level, multiple log entries with Time/Level/App/Message columns, ERROR row highlighted in pink/red. Low resolution |
| L2-logs-error-filter.png | Log viewer, ERROR filter | PASS | ERROR dropdown selected, 1 entry: laundry_room_lights "Error setting initial enabled state", pink highlight |
| L7-logs-app-column.png | Log viewer, App column | FAIL | Identical to L1 -- same pixel content |
| E1-error-404.png | 404 error page | PASS | "404 / Page not found. / Back to Dashboard" with sidebar and status bar |
| X7-layout-light-mode.png | Layout in light mode | PASS | Light theme dashboard with moon icon toggle, all content visible. Uptime shows "0h 8m" (later capture than D5's "0h 3m") |

## 2. Interactive States

| State | File | Verdict | Notes |
|-------|------|---------|-------|
| Expanded handler row | AD5 | PASS | First handler expanded with full invocation history |
| Expanded job row | AD8 | PASS | "run" job expanded with execution history |
| Running tab filter | A2 | PASS | Filtered to 6 running apps |
| Disabled tab filter | A5 | PASS | Filtered to 1 disabled app |
| ERROR log filter | L2 | PASS | Filtered to 1 error entry |
| Light mode toggle | D5, X7 | PASS | Both show light theme correctly applied |
| Dark mode toggle | X6 | PASS | Dark theme with sun icon |
| Multi-instance expanded (apps list) | A4 | WARN | No expand/collapse exists in new UI; shows "2" in Instances column only |

## 3. Full-Page Captures

| File | Scrollable Content Included? | Verdict |
|------|------------------------------|---------|
| D1 | Yes -- stat cards, App Health, Recent Errors all visible | PASS |
| AD5 | Yes -- header through logs section captured in one tall image | PASS |
| AD8 | Yes -- header through logs section captured | PASS |
| L1 | Partial -- bottom rows may be cut off (low resolution makes verification difficult) | WARN |
| AD7 | Yes -- full page with header, handlers, jobs, logs | PASS |

## 4. Blank/Corrupted Screenshots

No blank or corrupted screenshots detected. All 27 PNGs render valid UI content. File sizes range from 16 KB (E1-error-404.png) to 188 KB (AD5/AD6/AD10), all within expected ranges.

## 5. Filename Matching: new/ vs old/

### Files in new/ with matching old/ counterpart (PASS: 27/27)

All 27 PNG filenames in new/ have a corresponding PNG file in old/. Full match list:

| Filename | In new/ | In old/ |
|----------|---------|---------|
| D1-dashboard-default.png | Yes | Yes |
| D4-dashboard-session-bar.png | Yes | Yes |
| D5-dashboard-light-mode.png | Yes | Yes |
| X6-layout-dark-mode.png | Yes | Yes |
| X1-layout-sidebar.png | Yes | Yes |
| X4-layout-status-bar.png | Yes | Yes |
| A1-apps-all-tab.png | Yes | Yes |
| A2-apps-running-tab.png | Yes | Yes |
| A4-apps-multi-instance-expanded.png | Yes | Yes |
| A5-apps-disabled-tab.png | Yes | Yes |
| A6-apps-table-structure.png | Yes | Yes |
| AD1-app-detail-header.png | Yes | Yes |
| AD3-app-detail-health-strip.png | Yes | Yes |
| AD4-app-detail-handlers-collapsed.png | Yes | Yes |
| AD5-app-detail-handler-expanded.png | Yes | Yes |
| AD6-app-detail-invocation-table.png | Yes | Yes |
| AD7-app-detail-jobs-collapsed.png | Yes | Yes |
| AD8-app-detail-job-expanded.png | Yes | Yes |
| AD9-app-detail-execution-table.png | Yes | Yes |
| AD10-app-detail-logs-section.png | Yes | Yes |
| AD14-app-detail-disabled.png | Yes | Yes |
| AD15-app-detail-multi-instance.png | Yes | Yes |
| L1-logs-default.png | Yes | Yes |
| L2-logs-error-filter.png | Yes | Yes |
| L7-logs-app-column.png | Yes | Yes |
| E1-error-404.png | Yes | Yes |
| X7-layout-light-mode.png | Yes | Yes |

### Files in old/ with no new/ counterpart (skipped scenarios)

These exist as `.skip` files in old/ and were intentionally excluded from new/:

| Filename | Reason |
|----------|--------|
| AD11-app-detail-failed-error.skip | No failed app in current HA data |
| AD12-app-detail-failed-traceback.skip | No failed app in current HA data |
| X3-layout-alert-banner.skip | No failed apps, so no alert banner |

These skips are consistent between old/ and new/ -- neither set has these as PNGs.

## Summary

| Check | Result |
|-------|--------|
| Total screenshots | 27 |
| Correct page/state | 16 PASS, 1 WARN, 10 FAIL |
| Interactive states verified | 7 PASS, 1 WARN |
| Full-page captures | 4 PASS, 1 WARN |
| Blank/corrupted | 0 (all valid) |
| Filename coverage | 27/27 matched (3 old/ .skip files have no new/ counterpart, as expected) |

## Critical Issues

### ISSUE 1: 10 duplicate screenshots (HIGH)

The following files are pixel-identical duplicates of another screenshot and add no distinct value:

| Duplicate | Identical to |
|-----------|-------------|
| D4-dashboard-session-bar.png | D1-dashboard-default.png |
| X1-layout-sidebar.png | D1-dashboard-default.png |
| X4-layout-status-bar.png | D1-dashboard-default.png |
| A6-apps-table-structure.png | A1-apps-all-tab.png |
| A4-apps-multi-instance-expanded.png | A1-apps-all-tab.png |
| AD3-app-detail-health-strip.png | AD1-app-detail-header.png |
| AD4-app-detail-handlers-collapsed.png | AD1-app-detail-header.png |
| AD6-app-detail-invocation-table.png | AD5-app-detail-handler-expanded.png |
| AD10-app-detail-logs-section.png | AD5-app-detail-handler-expanded.png |
| AD9-app-detail-execution-table.png | AD8-app-detail-job-expanded.png |
| L7-logs-app-column.png | L1-logs-default.png |

**Root cause:** Full-page screenshots with `fullPage: true` capture the entire page in one image. When the capture script takes multiple screenshots of the same page without scrolling to a specific element or changing viewport, the result is identical. In contrast, the old/ screenshots for equivalent filenames (like AD3 vs AD1, AD6 vs AD5) appear to be the same full-page captures too -- so this may be by design for the capture matrix, but it means these "focused" screenshots do not actually focus on their named feature.

### ISSUE 2: Low resolution on some captures (MEDIUM)

Several screenshots (A1, A4, A6, AD1, AD3, AD4, AD8, AD9, AD15, L1, L7) appear to have been captured at a smaller viewport or were downscaled, making text difficult to read. The old/ equivalents for these same scenarios have similar sizes, suggesting this may be intentional thumbnail resolution, but it reduces audit utility.

### ISSUE 3: D4 does not show session bar (LOW)

D4-dashboard-session-bar.png is documented as "no session bar present in new UI." The screenshot is valid but the filename implies a feature that does not exist in the new UI. This is acknowledged in the capture summary but creates confusion in the comparison matrix.
