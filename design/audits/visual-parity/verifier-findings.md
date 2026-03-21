# Adversarial Visual Parity Verification

Independent element-by-element comparison of old vs new UI screenshots.
Conducted without reading the prior comparison document to avoid anchoring bias.

---

## D1 / D4 / X1 / X4 / X6 -- Dashboard (Dark Mode)

### Old UI elements enumerated

1. **Top bar**: green dot + "Connected" text, left-aligned
2. **Theme toggle**: gear/sun icon, top-right corner
3. **Sidebar**: 4 icon-only nav items (dashboard grid, apps molecule, logs clipboard); vertical left strip; Hassette logo at top with teal background
4. **Stats strip**: 5 health cards in a row -- APPS (7, "6 running"), ERROR RATE (0.0%, "No data" in green), HANDLERS (30, "0 invoked"), JOBS (11, "2 executions"), UPTIME (0h 1m)
5. **App Health section**: heading with wifi/signal icon + "App Health"; 7 app cards in a 5-column grid (5 top row, 2 bottom row)
6. **Each app health card**: app name (bold), green/gray dot + status badge text ("running"/"disabled"), handler count + job count, thin progress bar (green for running, gray for disabled), optional "Last: [time]" text
7. **"Manage Apps" link**: bottom of App Health section, small text link
8. **Recent Errors section**: warning triangle icon + "Recent Errors" heading; "No recent errors. All systems healthy." text
9. **Session bar / footer**: "Hassette v0.23.0  Started: 3/21/2026, 9:07:12 AM"
10. **Card containers**: bordered cards with subtle rounded corners and dark background, separated by spacing

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Green dot + "Connected" | SAME | Identical |
| Theme toggle icon (gear/sun) | SAME | Present, same position |
| Sidebar icons | DIFFERENT | Old has a filled teal-background Hassette logo at top; new has a small green dot at top instead of the filled logo block |
| Sidebar icon styling | DIFFERENT | Old sidebar icons are slightly different visual weight; new icons appear similar but the top brand element differs |
| Stats strip (5 cards) | SAME | All 5 cards present with same labels |
| JOBS detail text | DIFFERENT | Old says "2 executions", new says "1 executions" (data difference, not structural) |
| App Health section heading + icon | SAME | Present |
| App health cards (7 apps) | SAME | All 7 present, same grid layout |
| App name truncation | DIFFERENT | Old shows "GarageProximityA..." and "LaundryRoomLights...", new shows "GarageProximit..." and "LaundryRoomLi..." -- slightly different truncation points |
| MonarchUpdaterApp card | DIFFERENT | Old shows "Last: 9:07:14 AM" as an absolute time; new shows "Last: 3m ago" as a relative time; the old also showed the last activity on some cards but not consistently |
| AndysTrackerApp card | DIFFERENT | Old shows "Last: 9:07:19 AM" absolute time; new shows "Last: 3m ago" relative time |
| Progress bars in cards | SAME | Thin green/gray bars present |
| "Manage Apps" link | SAME | Present |
| Recent Errors section | DIFFERENT | Old says "No recent errors. All systems healthy." -- new says just "No recent errors." -- the "All systems healthy." text is missing |
| Session bar / footer | **MISSING** | Old has a footer bar showing "Hassette v0.23.0  Started: 3/21/2026, 9:07:12 AM" -- **completely absent in new UI** |
| Card border/shadow styling | SAME | Similar dark card containers |

---

## D5 / X7 -- Dashboard (Light Mode)

### Old UI elements enumerated

1. Same layout as dark mode but with light background
2. Cards have light gray/white backgrounds with visible borders
3. Theme toggle shows a refresh/sync icon (different from dark mode gear)
4. Status badges use same green color scheme
5. Footer/session bar present with version + start time

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Light mode layout | SAME | Overall structure matches |
| Theme toggle | DIFFERENT | Old light mode shows a refresh icon (circular arrows); new shows a moon icon (crescent) -- this is the correct toggle behavior (shows what clicking will switch TO) |
| Session bar / footer | **MISSING** | Not present in new light mode either |
| Recent Errors text | DIFFERENT | Same truncation as dark mode -- missing "All systems healthy." |

---

## A1 / A6 -- Apps List (All Tab)

### Old UI elements enumerated

1. **Page heading**: gear icon + "App Management"
2. **Filter tabs**: All (7), Running (6), Failed (0), Stopped (0), Disabled (1) -- styled as text tabs with underline on active
3. **Table columns**: APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS
4. **APP KEY column**: monospace teal/green linked text (e.g., "otf", "monarch_updater", "garage_proximity311", etc.)
5. **NAME column**: PascalCase app names (OtfApp, MonarchUpdaterApp, etc.)
6. **CLASS column**: same PascalCase names
7. **STATUS column**: colored dot + status text ("running" in green, "disabled" in gray)
8. **ERROR column**: em-dash for no errors
9. **ACTIONS column**: Stop button (orange), Reload button (teal/blue) -- shown as icon-only buttons with colored backgrounds
10. **RemoteApp row**: shows "running" with a "2 instances" indicator or similar multi-instance marker
11. **Row borders**: subtle horizontal separators between rows

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Page heading + icon | SAME | Present |
| Filter tabs | DIFFERENT | Old uses "All (7) Running (6) Failed (0) Stopped (0) Disabled (1)" as plain text tabs; new uses pill/button-style filter chips: "all 7 | running 6 | failed 0 | stopped 0 | disabled 1 | blocked 0" |
| "blocked" tab | **ADDED** | New UI has a "blocked 0" filter tab not present in old |
| Table columns | DIFFERENT | Old has 6 columns: APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS; New has 5 columns: NAME, STATUS, CLASS, INSTANCES, ACTIONS |
| APP KEY column | **MISSING** | Old showed the app_key as the first column (monospace teal link); new shows NAME as first column and the app_key is not visible as a separate column |
| NAME column as link | DIFFERENT | In old, APP KEY was the clickable link; in new, NAME is the clickable teal link |
| ERROR column | **MISSING** | Old had an ERROR column showing em-dash; new has no ERROR column |
| INSTANCES column | **ADDED** | New shows an INSTANCES column with numeric count (1, 2, etc.); old did not have this |
| Action buttons | DIFFERENT | Old had icon-only Stop/Reload buttons (orange stop, teal reload circles); new has text-labeled buttons: orange "Stop" and teal "Reload" with icons |
| Action button labels | **ADDED** | New buttons show text labels ("Stop", "Reload") alongside icons |
| Row styling | SIMILAR | Both have subtle row separators |

---

## A2 -- Apps List (Running Tab)

### Old UI elements enumerated

Same as All tab but filtered to 6 running apps; "Running (6)" tab underlined.

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Running tab active state | DIFFERENT | Old uses underline; new uses filled pill/chip style to indicate active tab |
| Filtered content | SAME | Shows only running apps |
| Column differences | SAME AS A1 | Same structural differences as All tab |

---

## A4 -- Apps Multi-Instance Expanded

### Old UI elements enumerated

Same as All tab -- the old UI screenshot A4 appears identical to A1 (no visible expansion of multi-instance apps in the table view).

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Multi-instance expansion | SAME | New A4 also appears same as A1 -- no visible instance expansion in the table |

---

## A5 -- Apps Disabled Tab

### Old UI elements enumerated

1. Disabled (1) tab active with underline
2. Single row: garage_proximity APP KEY (teal link), GarageProximityApp NAME, GarageProximityApp CLASS, gray dot + "disabled" STATUS, em-dash ERROR, empty ACTIONS

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Disabled tab active | SAME | Shows filtered to disabled apps |
| Single disabled app | SAME | GarageProximityApp shown |
| APP KEY column | **MISSING** | Old showed "garage_proximity" as separate column; new shows only NAME |
| ERROR column | **MISSING** | Old showed em-dash; new has no ERROR column |
| INSTANCES column | **ADDED** | Shows "0" for disabled app |
| Empty ACTIONS | SAME | No action buttons for disabled apps |

---

## AD1 / AD3 / AD4 -- App Detail Header (OfficeButtonApp)

### Old UI elements enumerated

1. **Breadcrumb**: "Apps / OfficeButtonApp" -- "Apps" as link
2. **App title**: gear icon + "OfficeButtonApp" bold + green dot + "running" badge
3. **Instance label**: "Instance 0 - PID OfficeButtonApp.office_button"
4. **Action buttons**: "Stop" (orange) and "Reload" (teal) buttons, top-right, with icons + text labels
5. **Health strip**: 4 metric cards -- STATUS ("Running" in green), ERROR RATE ("0.0%" in green), HANDLER AVG ("50.2 ms"), JOB AVG ("--" em-dash)
6. **Event Handlers section**: bell icon + "Event Handlers (4 registered)" heading
7. **4 handler rows** (collapsed):
   - Each has: colored dot (green = success), handler description text, subtitle with handler method + topic
   - Stats on right: "X calls", optional "Y failed", optional "Zms avg"
   - Chevron arrow (>) for expand affordance
8. **Scheduled Jobs section**: clock icon + "Scheduled Jobs (0 active)" heading; "No scheduled jobs." empty state text
9. **Logs section**: clipboard icon + "Logs" heading
10. **Log toolbar**: "All Levels" dropdown, Search input, "0 entries" count badge
11. **Log table headers**: LEVEL (sortable), TIMESTAMP (sortable, down arrow), MESSAGE (sortable)
12. **Log empty state**: "No log entries." centered text

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Breadcrumb | SAME | "Apps / OfficeButtonApp" present |
| App title + status badge | SAME | Present with gear icon, green dot, "running" |
| Instance label | SAME | "Instance 0 - PID OfficeButtonApp.office_button_app" |
| Action buttons | DIFFERENT | Old shows "Stop" and "Reload" with icons; new shows "Stop" (orange) and "Reload" (teal) -- looks similar but old had circular icon styling, new may have slightly different button styling |
| Health strip cards | DIFFERENT | Old had 4 cards: STATUS, ERROR RATE, HANDLER AVG, JOB AVG; New has 4 cards: STATUS, ERROR RATE, AVG DURATION, LAST ACTIVITY |
| "HANDLER AVG" label | **MISSING** | Renamed to "AVG DURATION" in new |
| "JOB AVG" label | **MISSING** | Renamed to "LAST ACTIVITY" in new |
| HANDLER AVG value | DIFFERENT | Old showed "50.2 ms"; new shows "<1ms" |
| JOB AVG value | DIFFERENT | Old showed "--"; new shows "--" (same) |
| STATUS value casing | DIFFERENT | Old shows "Running" (capitalized); new shows "running" (lowercase) |
| Event Handlers section | SAME | Bell icon + heading present |
| Handler row structure | DIFFERENT | Old showed handler rows with colored dot + title + subtitle + stats + chevron; New shows similar but subtle differences in layout |
| Handler row stats | DIFFERENT | Old showed "X calls", "Y failed", "Zms avg" inline; New shows similar stats but format may differ |
| Handler expand chevron | DIFFERENT | Old had a chevron (>) SVG arrow; need to verify if new has same affordance |
| Scheduled Jobs section | DIFFERENT | Old shows "Scheduled Jobs (0 active)" with "No scheduled jobs." for OfficeButtonApp; New shows "Scheduled Jobs (0 active)" -- same empty state |
| Logs section | SAME | Heading present |
| Log toolbar | DIFFERENT | Old had "All Levels" dropdown + "Search..." input + "0 entries" badge; New has "INFO" dropdown (different default) + "Search logs..." + "0 entries" |
| Log default filter | **DIFFERENT** | Old defaults to "All Levels"; new defaults to "INFO" -- this is a behavioral change that filters out DEBUG by default |
| Log table columns | DIFFERENT | Old had 3 columns: LEVEL, TIMESTAMP (with sort arrows), MESSAGE; New has 3 columns: TIME (with down arrow), LEVEL, MESSAGE -- **column order changed** |
| Sort indicators | DIFFERENT | Old used double-arrow sort indicators on all columns; new uses a single down-arrow on TIME only |

---

## AD5 / AD6 -- App Detail Handler Expanded + Invocation Table

### Old UI elements enumerated

1. **Expanded handler**: first handler row expanded, showing detail area below
2. **Handler detail**: subtitle showing full handler path (namespace.module:handler_method)
3. **Invocation count**: "67 | 0% Err  avg >" displayed on right of expanded row
4. **Invocation table columns**: STATUS, TIMESTAMP, DURATION, ERROR
5. **STATUS column**: green "success" badges for each row
6. **TIMESTAMP column**: formatted dates (03/21 09:04:34 AM format)
7. **DURATION column**: values like "158.8ms", "0.79ms", "0.4ms", etc.
8. **ERROR column**: em-dash for no errors
9. **Pagination or scroll**: table shows many rows
10. **Other collapsed handlers**: visible below the expanded one with their dots + titles + stats

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Expanded handler detail | SAME | Handler expands to show invocations |
| Handler path subtitle | SAME | Full path shown |
| Invocation stats summary | DIFFERENT | Old showed "67 | 0% Err  avg >"; new shows similar but with "calls" label |
| Invocation table columns | DIFFERENT | Old: STATUS, TIMESTAMP, DURATION, ERROR; New: TIME, DURATION, STATUS, ERROR |
| Column order | **DIFFERENT** | TIME moved to first position; STATUS moved from first to third |
| TIMESTAMP format | DIFFERENT | Old: "03/21 09:04:34 AM" (date + time); New: "8:43:24 AM" (time only, no date) |
| Duration format | SIMILAR | Both show milliseconds |
| SUCCESS badge styling | SIMILAR | Green badge in both |
| Error column | SAME | Em-dash for no errors |
| Collapsed handlers below | SAME | Visible with dots + titles |
| Expand/collapse count badge | DIFFERENT | Old showed raw number + pct; new shows "X calls" format |

---

## AD7 -- App Detail Jobs Collapsed (AndysTrackerApp)

### Old UI elements enumerated

1. **Breadcrumb**: "Apps / AndysTrackerApp"
2. **App title**: gear icon + "AndysTrackerApp" + green dot + "running"
3. **Instance label**: "Instance 0 - PID AndysTrackerApp.andys_tracker"
4. **Action buttons**: Stop + Reload
5. **Health strip**: STATUS (Running), ERROR RATE (0.0%), HANDLER AVG (--), JOB AVG (435.2 ms)
6. **Event Handlers**: "Event Handlers (0 registered)" + "No event handlers registered." empty state
7. **Scheduled Jobs**: "Scheduled Jobs (2 active)"
8. **Two job rows** (collapsed):
   - `andys_tracker_job`: dot + title + "cron: 0 0 * * * 0" subtitle + "1 runs  228.9ms avg >"
   - `run`: dot + title + "AndysTrackerApp.run" subtitle + "24 runs  439.7ms avg >"
9. **Chevron arrows** on each job row (>)
10. **Logs section**: same as other detail pages

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Breadcrumb + title | SAME | Present |
| Instance label | DIFFERENT | Old: "Instance 0 - PID AndysTrackerApp.andys_tracker"; New: "Instance 0 - PID AndysTrackerApp.andys" -- possibly truncated |
| Health strip | DIFFERENT | Old: STATUS/ERROR RATE/HANDLER AVG/JOB AVG; New: STATUS/ERROR RATE/AVG DURATION/LAST ACTIVITY |
| JOB AVG value | DIFFERENT | Old: "435.2 ms"; New shows "6m ago" in LAST ACTIVITY (different metric entirely) |
| AVG DURATION value | DIFFERENT | Old HANDLER AVG was "--"; New AVG DURATION shows "<1ms" |
| Job rows | SIMILAR | Both show 2 jobs with dots + titles |
| Job subtitle | DIFFERENT | Old showed "cron: 0 0 * * * 0" for cron trigger; New shows just "cron" without the full cron expression |
| Job stats | DIFFERENT | Old showed "1 runs 228.9ms avg"; New shows "6 runs" (different count, data timing difference) and possibly different format |
| Job chevron (>) | DIFFERENT | Old had visible chevron arrow; New may or may not show chevron -- not clearly visible in new screenshot |
| Logs default filter | DIFFERENT | Same as AD1 -- old defaults to "All Levels", new defaults to "INFO" |

---

## AD8 / AD9 -- App Detail Job Expanded + Execution Table (AndysTrackerApp)

### Old UI elements enumerated

1. **Expanded job**: `andys_tracker_job` expanded showing execution detail
2. **Job subtitle**: "cron: 0 0 * * * 0" visible under expanded row
3. **Sub-tab**: `run` sub-item visible under the job, with its own subtitle "AndysTrackerApp.run"
4. **Execution table columns**: STATUS, TIMESTAMP, DURATION, GPT, ERROR
5. **STATUS column**: green "success" badges
6. **TIMESTAMP column**: formatted timestamps (03/21 format)
7. **DURATION column**: values like "300.0ms", "338.0ms"
8. **GPT column**: present (or similar column -- hard to read at small size)
9. **ERROR column**: em-dash
10. **Pagination indicators**: visible at top of expanded section ("25 | 0% Err  avg >")

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Expanded job detail | SAME | Job expands to show executions |
| Execution table columns | DIFFERENT | Old: STATUS, TIMESTAMP, DURATION, GPT(?), ERROR; New: TIME, DURATION, STATUS, ERROR |
| Column order | **DIFFERENT** | Same reordering as handler invocations -- TIME first |
| TIMESTAMP format | DIFFERENT | Old showed date+time; New shows time only |
| Job subtitle / trigger info | DIFFERENT | Old showed full cron expression; New shows just "cron" |
| Stats summary | SIMILAR | Both show count + error rate |

---

## AD10 -- App Detail Logs Section (OfficeButtonApp, scrolled down)

### Old UI elements enumerated

Same as AD1/AD4 view but scrolled to show the logs section more prominently. Shows the full handler rows + jobs section + logs toolbar.

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Same as AD1 findings | -- | All same differences apply |
| Logs toolbar layout | SAME | Toolbar present with filter + search + count |

---

## AD14 -- App Detail Disabled (GarageProximityApp)

### Old UI elements enumerated

1. **Breadcrumb**: "Apps / GarageProximityApp"
2. **App title**: gear icon + "GarageProximityApp" + gray dot + "disabled"
3. **No action buttons**: disabled app has no Stop/Reload buttons
4. **Health strip**: 4 cards -- STATUS ("Disabled" white text), ERROR RATE (0.0% green), HANDLER AVG (--), JOB AVG (--)
5. **Event Handlers**: "Event Handlers (0 registered)" + "No event handlers registered."
6. **Scheduled Jobs**: "Scheduled Jobs (0 active)" + "No scheduled jobs."
7. **Logs section**: toolbar with "All Levels" + Search + "0 entries"; columns: LEVEL, TIMESTAMP, MESSAGE; "No log entries."

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Breadcrumb + title | SAME | Present |
| No action buttons | SAME | No buttons for disabled app |
| Health strip labels | DIFFERENT | Old: STATUS/ERROR RATE/HANDLER AVG/JOB AVG; New: STATUS/ERROR RATE/AVG DURATION/LAST ACTIVITY |
| STATUS value | DIFFERENT | Old: "Disabled" (capitalized); New: "disabled" (lowercase) |
| AVG DURATION value | DIFFERENT | Old HANDLER AVG showed "--"; New AVG DURATION shows "<1ms" |
| LAST ACTIVITY value | SAME | Shows "--" |
| Empty states | SAME | Same text for empty handlers/jobs |
| Logs default filter | DIFFERENT | Old: "All Levels"; New: "INFO" |
| Logs table column order | DIFFERENT | Old: LEVEL, TIMESTAMP, MESSAGE; New: TIME, LEVEL, MESSAGE |

---

## AD15 -- App Detail Multi-Instance (RemoteApp)

### Old UI elements enumerated

1. **Breadcrumb**: "Apps / RemoteApp"
2. **App title**: gear icon + "RemoteApp" + green dot + "running"
3. **Instance label**: "Instance 0 - PID RemoteApp.jessica_remote" (or similar -- shows specific instance)
4. **Instance selector/indicator**: showing "jessica_remote.is_running" or similar
5. **Action buttons**: Stop + Reload
6. **Health strip**: STATUS (Running), ERROR RATE (0.0%), HANDLER AVG (69.8 ms), JOB AVG (--)
7. **Event Handlers**: "Event Handlers (1 registered)" -- 1 handler row
8. **Handler row**: showing state_change handler with topic info
9. **Scheduled Jobs**: "Scheduled Jobs (0 active)" + "No scheduled jobs."
10. **Logs section**: standard toolbar + empty table

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Breadcrumb + title | SAME | Present |
| Instance label | DIFFERENT | Old: "Instance 0 - PID RemoteApp.jessica_remote"; New: "Instance 0 - PID RemoteApp.remote_app" -- different PID name |
| Instance selector | UNCERTAIN | Old showed instance-specific info; New appears similar |
| Health strip labels | DIFFERENT | Same label changes as other detail pages |
| HANDLER AVG value | DIFFERENT | Old: "69.8 ms"; New: "<1ms" in AVG DURATION (data/label change) |
| Handler row | SAME | 1 handler shown |
| Logs default filter | DIFFERENT | Old: "All Levels"; New: "INFO" |

---

## L1 / L7 -- Log Viewer (Default / All Levels)

### Old UI elements enumerated

1. **Page heading**: clipboard icon + "Log Viewer"
2. **Log toolbar**: "All Levels" dropdown, "All Apps" dropdown, "Search..." input, "X entries" count badge
3. **Table columns**: LEVEL (sortable), TIMESTAMP (sortable, down arrow), APP (sortable), MESSAGE (sortable)
4. **LEVEL badges**: colored badges -- INFO (teal/blue), WARNING (yellow/orange), ERROR (red), DEBUG (gray)
5. **TIMESTAMP**: formatted times (9:07:14 AM format)
6. **APP column**: teal monospace links to app detail pages (e.g., "monarch_updater", "laundry_room_lights")
7. **MESSAGE column**: full log message text, wrapping if needed
8. **Sort indicators**: double-arrow indicators on all sortable columns; TIMESTAMP has active down-arrow
9. **Loading badge**: shows "Loading..." during initial load
10. **Row density**: compact/dense rows for logs

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Page heading | SAME | "Log Viewer" with icon |
| "All Apps" dropdown | **MISSING** | Old had an "All Apps" dropdown filter to filter by app; New only shows level dropdown + search + count |
| Level dropdown default | DIFFERENT | Old: "All Levels"; New: "INFO" -- different default filter level |
| Table columns | DIFFERENT | Old: LEVEL, TIMESTAMP, APP, MESSAGE; New: TIME, APP, LEVEL, MESSAGE |
| Column order | **DIFFERENT** | TIME is first in new; LEVEL was first in old. APP moved from third to second. |
| TIMESTAMP header label | DIFFERENT | Old: "TIMESTAMP"; New: "TIME" |
| Sort indicators | DIFFERENT | Old showed double-arrow sort indicators on all columns; New shows down-arrow on TIME only |
| LEVEL badge styling | DIFFERENT | Old: inline colored badges (teal INFO, yellow WARNING, red ERROR); New: similar but with possible styling differences -- ERROR rows appear to have full-row pink/red background highlighting |
| ERROR row highlighting | **ADDED** | New UI highlights entire ERROR log rows with a red/pink background; old only colored the badge |
| WARNING row highlighting | **ADDED** | New UI may highlight WARNING rows too (visible pink/coral rows at bottom of L1 new screenshot) |
| APP column links | SAME | Teal monospace links present |
| Log entry count | SAME | Count badge present |

---

## L2 -- Log Viewer (Error Filter)

### Old UI elements enumerated

1. Level filter set to "ERROR"
2. "All Apps" filter set to "All Apps"
3. "1 entries" count
4. Table: LEVEL, TIMESTAMP, APP, MESSAGE columns
5. Single row: ERROR badge (red), "9:07:13 AM", "laundry_room_lights" (teal link), "Error setting initial enabled state"

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| Error filter active | SAME | Shows ERROR filter |
| "All Apps" dropdown | **MISSING** | New has no app filter dropdown |
| Count | SAME | "1 entries" |
| Column order | **DIFFERENT** | Old: LEVEL, TIMESTAMP, APP, MESSAGE; New: TIME, LEVEL, APP, MESSAGE |
| ERROR row styling | **DIFFERENT** | Old: normal row with red LEVEL badge only; New: entire row has pink/red background highlighting |
| Timestamp | SAME | Time shown |

---

## E1 -- Error 404 Page

### Old UI elements enumerated

1. **No sidebar/layout**: raw JSON response page, no Hassette UI chrome
2. **Browser chrome**: "Pretty-print" checkbox at top
3. **Content**: `{"detail":"Not Found"}` JSON text

### Comparison with New UI

| Element | Status | Notes |
|---------|--------|-------|
| 404 page | **DIFFERENT** | Old was a raw JSON API response with no UI; New is a proper styled 404 page with Hassette layout (sidebar, top bar, "Connected"), large "404" heading, "Page not found." text, and "Back to Dashboard" button |
| Sidebar present | **ADDED** | New 404 has full sidebar navigation |
| "Back to Dashboard" button | **ADDED** | New has a navigation button to return home |
| JSON response | **MISSING** | Old showed raw `{"detail":"Not Found"}`; new shows styled HTML |

---

## Skipped Screenshots (Template-Derived, No Live Data)

The following elements exist in the old templates but were not captured because no apps were in a failed state during screenshot capture:

### AD11/AD12 -- Failed App Error + Traceback
From the old template macros, failed apps show:
- STATUS badge in red with "failed" text
- Error message display area
- Traceback/stack trace display (pre-formatted code block)
- A "Start" button (green) instead of Stop/Reload

**Verification status**: Cannot verify parity for error/traceback display without a failed app.

### X3 -- Alert Banner
From old behavior, when failed apps exist:
- A banner/alert appears (likely at top of page)
- Shows count of failed apps or error summary

**Verification status**: Cannot verify parity for alert banner without failed apps.

---

## Summary of Top Findings

### CRITICAL -- Likely to be missed

1. **Session bar / footer completely removed** -- The old UI had a persistent footer showing "Hassette v0.23.0  Started: [datetime]". This is entirely absent from the new UI. Version and uptime-since information is now only available via the UPTIME health card, and version is nowhere visible.

2. **"All Apps" dropdown filter removed from Log Viewer** -- The old log viewer had both a level filter AND an app filter dropdown. The new UI only has the level filter + search. Users who filtered logs by specific app on the global log page have lost that capability.

3. **Log default filter changed from "All Levels" to "INFO"** -- This is a behavioral change that means DEBUG-level logs are hidden by default in the new UI. Users accustomed to seeing all logs will silently miss DEBUG entries.

4. **APP KEY column removed from apps table** -- The old apps table showed both APP KEY and NAME as separate columns. The new table drops APP KEY entirely. For apps where the key differs significantly from the name (e.g., "garage_proximity311" vs "GarageProximityApp"), this information is no longer visible on the list page.

5. **ERROR column removed from apps table** -- The old table had a dedicated ERROR column. The new table does not surface per-app error info in the list view.

6. **Health strip metric labels changed** -- "HANDLER AVG" became "AVG DURATION" and "JOB AVG" became "LAST ACTIVITY". The LAST ACTIVITY card shows a relative time ("6m ago") rather than an average duration, meaning this is a different metric, not just a rename.

7. **Log table column order changed** -- Old: LEVEL first, then TIMESTAMP; New: TIME first, then LEVEL (or APP). This affects muscle memory and any documentation/screenshots referencing column positions.

8. **Status value casing changed** -- Old showed "Running", "Disabled" (title case); new shows "running", "disabled" (lowercase). Minor but noticeable.

9. **"All systems healthy" text removed** from Recent Errors empty state -- old said "No recent errors. All systems healthy.", new says only "No recent errors."

10. **Job trigger details truncated** -- Old showed full cron expressions (e.g., "cron: 0 0 * * * 0"); new shows just "cron" without the expression. Users lose at-a-glance scheduling info.

### STRUCTURAL -- New additions

11. **"blocked" filter tab added** to apps table -- New UI has a "blocked 0" tab not present in old.

12. **INSTANCES column added** to apps table -- New column shows instance count per app.

13. **Full-row error highlighting in logs** -- New UI highlights entire ERROR/WARNING rows with colored backgrounds, improving visibility over old badge-only approach.

14. **Proper 404 page** -- New UI has a styled 404 page with navigation, replacing old raw JSON response.

15. **Sidebar brand element changed** -- Old had a filled teal Hassette logo block at sidebar top; new has a small green dot indicator instead.
