# Round 2 Visual Parity Comparison

Compared 27 screenshot pairs between old UI (reference) and new UI (post-fixes).

---

## Dashboard

### D1-dashboard-default.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old has health cards inside bordered cards with visible border/background; new renders same layout faithfully | MATCH |
| 2 | Health bar (teal progress bars under each app card) present in old, present in new | MATCH |
| 3 | "Manage Apps" link present in both | MATCH |
| 4 | Recent Errors section with icon + heading matches | MATCH |
| 5 | Status bar at bottom (version + start time) matches | MATCH |
| 6 | Old shows stat cards ("APPS 7", "ERROR RATE 0.0%", etc.) in bordered cards; new matches | MATCH |
| **No differences found** | | |

### D4-dashboard-session-bar.png
| # | Finding | Classification |
|---|---------|---------------|
| **No differences found** — identical to D1 in both old and new (same page state) | | |

### D5-dashboard-light-mode.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old status bar shows "Hassette v0.23.0 Started 3/29/2026, 9:07:12 AM"; new shows "Hassette Started 3/21/2026, 10:02:27 AM" — data difference only, not a visual gap | MATCH |
| 2 | Old light mode has slightly warmer white background; new has a clean white — negligible rendering difference | MATCH |
| 3 | Old health cards have visible card borders; new matches with same bordered card style | MATCH |
| 4 | Old has refresh icon (circular arrow) top-right; new has same refresh icon | MATCH |
| **No differences found** | | |

---

## Layout / Chrome

### X1-layout-sidebar.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Sidebar icons (dashboard grid, apps people icon, logs clipboard icon) match in both | MATCH |
| 2 | Sidebar background color and width match | MATCH |
| 3 | Active page indicator (highlight on sidebar icon) matches | MATCH |
| **No differences found** | | |

### X4-layout-status-bar.png
| # | Finding | Classification |
|---|---------|---------------|
| **No differences found** — same as D1/X1 | | |

### X6-layout-dark-mode.png
| # | Finding | Classification |
|---|---------|---------------|
| **No differences found** — dark mode rendering matches | | |

### X7-layout-light-mode.png
| # | Finding | Classification |
|---|---------|---------------|
| **No differences found** — matches D5 light mode | | |

---

## Apps List

### A1-apps-all-tab.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old has tabs: "All (7) Running (6) Failed (0) Stopped (0) Disabled (1)"; new has same tabs plus "Blocked (0)" | **DIFFERENT** |
| 2 | Old tab style: plain text with underline on active; new has bordered/pill-style tab buttons | **DIFFERENT** |
| 3 | Old page heading uses gear icon; new uses grid/apps icon | **DIFFERENT** |
| 4 | Table columns match: APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS | MATCH |
| 5 | Action buttons (Stop/Reload pairs) with circular icon style match | MATCH |
| 6 | Status badges (running with green dot, disabled with grey) match in style | MATCH |
| 7 | App key links in teal/green color match | MATCH |

### A2-apps-running-tab.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Tab style difference carries over (same as A1) | **DIFFERENT** |
| 2 | Filtered content correct — shows only running apps | MATCH |
| 3 | "Blocked (0)" extra tab visible in new | **DIFFERENT** |

### A4-apps-multi-instance-expanded.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old shows chevron expand/collapse indicators for multi-instance apps; new shows same | MATCH |
| 2 | Tab style difference (same as A1) | **DIFFERENT** |
| 3 | Expanded instance sub-rows visible in both with indented styling | MATCH |
| 4 | "Blocked (0)" extra tab in new | **DIFFERENT** |

### A5-apps-disabled-tab.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Tab style: old uses underline-only active indicator; new uses bordered pill/button style tabs | **DIFFERENT** |
| 2 | "Blocked (0)" extra tab in new | **DIFFERENT** |
| 3 | Old status badge has dot + "disabled"; new shows "disabled" text without dot | **GAP** |
| 4 | Old has no action buttons for disabled app (ACTIONS column empty); new matches (also empty) | MATCH |

### A6-apps-table-structure.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Same content as A1 — tab style and Blocked tab differences carry over | **DIFFERENT** |

---

## App Detail

### AD1-app-detail-header.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Breadcrumb "Apps / OfficeButtonApp" present in both | MATCH |
| 2 | App title with gear icon + name + status badge matches | MATCH |
| 3 | Old shows "Instance 0 · PID OfficeButtonApp.office_button"; new shows same instance metadata | MATCH |
| 4 | Old health strip: STATUS "Running", ERROR RATE "0.0%", HANDLER AVG "50.2 ms", JOB AVG "—"; new shows STATUS "Running", ERROR RATE "0.0%", HANDLER AVG "<1ms", JOB AVG "—" — data difference | MATCH |
| 5 | Stop/Reload buttons in top-right match | MATCH |
| 6 | Old health strip cards have visible borders; new matches | MATCH |

### AD3-app-detail-health-strip.png
| # | Finding | Classification |
|---|---------|---------------|
| **No differences found** — same page state as AD1 | | |

### AD4-app-detail-handlers-collapsed.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | "Event Handlers (4 registered)" section heading with bell icon matches | MATCH |
| 2 | Handler rows show event pattern text in teal, callback path in muted text | MATCH |
| 3 | Collapsed state (no invocation table visible) matches | MATCH |
| 4 | "Scheduled Jobs (0 active)" section visible at bottom matches | MATCH |
| 5 | Logs section with filter controls visible at bottom matches | MATCH |
| **No differences found** | | |

### AD5-app-detail-handler-expanded.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old invocation table has columns: STATUS, TIMESTAMP, DURATION, ERROR with explicit column headers; new has columns: TIME, DURATION, STATUS, ERROR | **GAP** |
| 2 | Old shows "STATUS" as first column with badge; new moves STATUS to third column | **GAP** |
| 3 | Old has "TIMESTAMP" column showing "03/21 09:08:24 AM" format; new shows "8:43:24 AM" (time-only, no date) | **GAP** |
| 4 | Old shows invocation count and pagination ("20 calls avg" summary); new shows "0 calls" with different summary format | **DIFFERENT** |
| 5 | Old handler rows show chevron (>) indicator for expand; new shows similar expand indicator | MATCH |
| 6 | Old status badges use small colored pills (success=green, error=red); new uses same colored pills | MATCH |
| 7 | Old duration format "158.0ms" vs new "158ms" — minor formatting difference | **GAP** |

### AD6-app-detail-invocation-table.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Same differences as AD5 (column order, timestamp format, duration format) | **GAP** |

### AD7-app-detail-jobs-collapsed.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old shows "Scheduled Jobs (2 active)" with job rows showing name, cron expression, run count, avg duration, and chevron; new shows same structure | MATCH |
| 2 | Old job row shows "1 runs 228.9ms avg >" format; new shows "6 runs" with slightly different formatting | **DIFFERENT** |
| 3 | Old shows "No event handlers registered." text; new shows "No handlers registered." | **GAP** |
| 4 | Old has additional job detail text "AndysTrackerApp.run"; new has same pattern | MATCH |

### AD8-app-detail-job-expanded.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old execution table has columns: STATUS, TIMESTAMP, DURATION, GPS, ERROR; new has columns: FIRED, DURATION, STATUS, ERROR | **GAP** |
| 2 | Old TIMESTAMP shows full date+time "03/21 9:08:24 PM"; new FIRED column shows time-only "10:02:34 AM" | **GAP** |
| 3 | Old has a "GPS" column not present in new | **GAP** |
| 4 | Old duration shows "358.0ms"; new shows "367ms" — format difference (no decimal) | **GAP** |
| 5 | Old status badges in execution table match styling with new | MATCH |
| 6 | Old shows pagination controls ("20 calls avg"); new shows run count summary differently | **DIFFERENT** |

### AD9-app-detail-execution-table.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Same issues as AD8 — column names, timestamp format, GPS column missing | **GAP** |

### AD10-app-detail-logs-section.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old logs section has filter row: "All Levels" dropdown + "Search..." input + count; new matches | MATCH |
| 2 | Old log table columns: LEVEL, TIMESTAMP, MESSAGE; new matches | MATCH |
| 3 | "No log entries." empty state text matches | MATCH |
| 4 | Log section heading with clipboard icon matches | MATCH |
| **No differences found** (viewing AD10 which is the same page as AD1 scrolled to logs) | | |

### AD14-app-detail-disabled.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old breadcrumb "Apps / GarageProximityApp" matches new | MATCH |
| 2 | Old title "GarageProximityApp" + disabled badge matches new | MATCH |
| 3 | Old has no instance metadata line visible; new shows "Instance 0" | **DIFFERENT** |
| 4 | Old HANDLER AVG shows "—"; new shows "<1ms" | **DIFFERENT** |
| 5 | Old "No event handlers registered." text; new shows "No handlers registered." | **GAP** |
| 6 | Old "No scheduled jobs." text; new "No scheduled jobs." matches | MATCH |
| 7 | Health strip cards border style matches | MATCH |
| 8 | Old has no Stop/Reload buttons for disabled app; new also has none | MATCH |
| 9 | Old logs section with sort indicators matches new | MATCH |
| 10 | Old shows "No log entries." centered; new shows empty table with no text — column headers visible but no "No log entries." message | **GAP** |

### AD15-app-detail-multi-instance.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old shows instance selector: "jessica_remote (running)" dropdown; new shows "jessica_remote (running)" with selector/tabs | MATCH |
| 2 | Old shows handler row with event pattern in teal; new matches | MATCH |
| 3 | Old "No scheduled jobs." text matches new | MATCH |
| 4 | Old health strip matches new (STATUS Running, ERROR RATE 0.0%, HANDLER AVG, JOB AVG) | MATCH |
| 5 | Old shows "Event Handlers (1 registered)" with handler details; new matches | MATCH |
| **No differences found beyond data values** | | |

---

## Logs Page

### L1-logs-default.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old has filter row: "All Levels" dropdown + "All Apps" dropdown + "Search..." input + entry count; new has same controls | MATCH |
| 2 | Old log table columns: LEVEL, TIMESTAMP, APP, MESSAGE; new matches | MATCH |
| 3 | Old level badges (INFO=blue, WARNING=yellow, ERROR=red) match new styling | MATCH |
| 4 | Old error rows have red/pink background highlight; new has same red/pink row highlight | MATCH |
| 5 | Old warning rows have yellow badge; new has same yellow/amber badge | MATCH |
| 6 | Old "INFO" badge is subtle teal/blue; new matches | MATCH |
| 7 | Old SUCCESS rows have green badge; new has similar green styling | MATCH |
| 8 | Old timestamp format shows time only; new matches | MATCH |
| 9 | Old APP column shows app key as teal link; new matches | MATCH |
| **No differences found** | | |

### L2-logs-error-filter.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old shows ERROR filter active with 1 entry; new matches with 1 entry | MATCH |
| 2 | Old error row has red "ERROR" badge + timestamp + app link + message; new shows same but with full-row pink/red background highlight that is more prominent | **DIFFERENT** |
| 3 | Old error row background is the same dark table background with just the badge colored; new has a very prominent pink/coral full-row background | **GAP** |
| 4 | Old level column shows "ERROR" badge in red pill; new row has no separate ERROR badge visible — the entire row is pink | **GAP** |
| 5 | Old sort indicators on column headers match new | MATCH |

### L7-logs-app-column.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Same as L1 — no differences beyond data values | MATCH |
| **No differences found** | | |

---

## Error Page

### E1-error-404.png
| # | Finding | Classification |
|---|---------|---------------|
| 1 | Old shows raw JSON `{"detail":"Not Found"}` on white background with "Pretty-print" checkbox (browser default); new shows styled 404 page with "404" heading, "Page not found." text, "Back to Dashboard" button, within the app shell (sidebar + status bar) | **IMPROVEMENT** |

---

## Summary

### Counts

| Classification | Count |
|---|---|
| **GAP** (must fix) | 14 |
| **DIFFERENT** (intentional) | 12 |
| **IMPROVEMENT** (new is better) | 1 |
| **MATCH** | ~60+ individual checks |

### GAP Details (must fix)

| # | Screenshot | Issue |
|---|-----------|-------|
| G1 | A5-apps-disabled-tab | Status badge for "disabled" missing the dot indicator in new UI |
| G2 | AD5-app-detail-handler-expanded | Invocation table column order wrong: old is STATUS, TIMESTAMP, DURATION, ERROR; new is TIME, DURATION, STATUS, ERROR |
| G3 | AD5-app-detail-handler-expanded | Timestamp column shows time-only ("8:43:24 AM") instead of date+time ("03/21 09:08:24 AM") |
| G4 | AD5-app-detail-handler-expanded | Duration format missing decimal: "158ms" vs old "158.0ms" |
| G5 | AD6-app-detail-invocation-table | Same column order/timestamp/duration issues as G2-G4 |
| G6 | AD7-app-detail-jobs-collapsed | Empty handler text says "No handlers registered." vs old "No event handlers registered." |
| G7 | AD8-app-detail-job-expanded | Execution table column order wrong: old is STATUS, TIMESTAMP, DURATION, GPS, ERROR; new is FIRED, DURATION, STATUS, ERROR |
| G8 | AD8-app-detail-job-expanded | Timestamp column renamed from "TIMESTAMP" to "FIRED" and shows time-only |
| G9 | AD8-app-detail-job-expanded | Missing "GPS" column from execution table |
| G10 | AD8-app-detail-job-expanded | Duration format missing decimal: "367ms" vs old "358.0ms" |
| G11 | AD9-app-detail-execution-table | Same issues as G7-G10 |
| G12 | AD14-app-detail-disabled | Empty handler text says "No handlers registered." vs old "No event handlers registered." |
| G13 | AD14-app-detail-disabled | Empty logs table missing "No log entries." message |
| G14 | L2-logs-error-filter | Error rows have overly prominent pink/coral full-row background instead of subtle row with just a red ERROR badge; ERROR level badge not visible as distinct element |

### DIFFERENT Details (intentional changes, no action needed)

| # | Screenshot | Change |
|---|-----------|--------|
| D1 | A1/A2/A4/A5/A6 | Tab style changed from underline to bordered pill/button style |
| D2 | A1/A2/A4/A5/A6 | Extra "Blocked (0)" tab added |
| D3 | A1 | Page heading icon changed from gear to grid |
| D4 | AD5 | Invocation summary format changed |
| D5 | AD7 | Job run count summary format slightly different |
| D6 | AD8 | Execution pagination/summary format changed |
| D7 | AD14 | Instance metadata line now shown for disabled apps |
| D8 | AD14 | Handler AVG shows "<1ms" instead of "—" for disabled apps |
| D9 | L2 | Error row styling is more prominent (may be intentional emphasis) |

---

## Verdict: **FAIL**

14 GAPs remain. The most impactful clusters:

1. **Invocation/execution table column order and naming** (G2, G5, G7, G8, G11) — the tables reorganized columns and renamed headers vs the old UI
2. **Timestamp format regression** (G3, G8) — lost date portion, showing time-only
3. **Duration decimal formatting** (G4, G10) — dropped the ".0" decimal formatting
4. **Missing GPS column** (G9) — execution table lost a column
5. **Empty state text wording** (G6, G12, G13) — minor wording differences and a missing empty-state message
6. **Disabled status dot missing** (G1) — badge lost its dot indicator
7. **Error row over-styling** (G14) — error rows too visually aggressive vs old subtle badge-only approach
