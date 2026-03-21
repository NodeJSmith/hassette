# Visual Parity Comparison — Old UI vs New UI

Audit date: 2026-03-21

---

### D1-dashboard-default.png — Dashboard default view

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | KPI strip card count | 5 cards (Apps, Error Rate, Handlers, Jobs, Uptime) | 5 cards (Apps, Error Rate, Handlers, Jobs, Uptime) | MATCH |
| 2 | KPI strip layout | Horizontal row with equal-width cards | Horizontal row with equal-width cards | MATCH |
| 3 | KPI detail text "6 running" | Present under Apps count | Present under Apps count | MATCH |
| 4 | KPI detail "No data" under Error Rate | Present | Present | MATCH |
| 5 | KPI detail "0 invoked" under Handlers | Present | Present | MATCH |
| 6 | KPI detail under Jobs | "2 executions" | "1 executions" (data differs, layout same) | MATCH |
| 7 | App Health section heading | Heart-pulse icon + "App Health" | Heart-pulse icon + "App Health" | MATCH |
| 8 | App Health card count | 7 cards in 5+2 grid | 7 cards in 5+2 grid | MATCH |
| 9 | App Health card content | Name, status badge, handler/job counts, progress bar, "Last:" timestamp | Name, status badge, handler/job counts, progress bar, "Last:" relative time | DIFFERENT |
| 10 | "Last:" timestamp format | Absolute "Last: 9:07:14 AM" | Relative "Last: 3m ago" | DIFFERENT |
| 11 | "Manage Apps" link | Text link at bottom of App Health section | Button-styled link at bottom of App Health section | DIFFERENT |
| 12 | Recent Errors section | Present with "No recent errors. All systems healthy." | Present with "No recent errors." | DIFFERENT |
| 13 | Recent Errors empty text | "No recent errors. All systems healthy." | "No recent errors." (shorter) | GAP |
| 14 | Session info bar | Present at bottom: "Hassette v0.23.0 Started 3/29/2026, 9:07:32 AM" | Missing entirely | GAP |
| 15 | Theme toggle button | Present in header bar (top-right, small icon) | Present in header bar (gear/sun icon, top-right) | MATCH |
| 16 | Sidebar icons | Dashboard (grid), Apps (people), Logs (document) — filled style | Dashboard (grid), Apps (people), Logs (document) — outline style | DIFFERENT |
| 17 | Sidebar active indicator | Filled/highlighted icon on active page | Green highlight border + filled icon on active page | DIFFERENT |
| 18 | Connection status bar | "Connected" with green dot | "Connected" with green dot | MATCH |
| 19 | Overall spacing | Compact, fits on smaller viewport | More generous padding, takes more vertical space | DIFFERENT |

---

### D4-dashboard-session-bar.png — Dashboard session bar

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Session info bar | Present: "Hassette v0.23.0 Started 3/29/2026, 9:07:32 AM" | Missing entirely | GAP |
| 2 | All other dashboard elements | Same as D1 | Same as D1 (no session bar) | MATCH |

---

### D5-dashboard-light-mode.png — Dashboard light mode

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Light mode background | Light gray/white background | Light gray/white background | MATCH |
| 2 | Card styling in light mode | Cards with subtle borders, light backgrounds | Cards with subtle borders, light backgrounds | MATCH |
| 3 | Text contrast in light mode | Good contrast, dark text on light bg | Good contrast, dark text on light bg | MATCH |
| 4 | Session info bar | Present at bottom | Missing | GAP |
| 5 | Theme toggle icon | Refresh/sync icon (top-right) | Moon icon (top-right) — correct for light mode | IMPROVEMENT |
| 6 | Sidebar in light mode | Dark sidebar maintained | Dark sidebar maintained (same as dark mode) | MATCH |
| 7 | KPI strip cards | Bordered cards with light fill | Bordered cards with light fill | MATCH |
| 8 | App Health cards in light | Dark-bordered cards with white fill | Light-bordered cards with white fill | MATCH |

---

### X1-layout-sidebar.png — Layout sidebar

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Sidebar width | Narrow icon-only sidebar | Narrow icon-only sidebar | MATCH |
| 2 | Sidebar position | Left fixed | Left fixed | MATCH |
| 3 | Sidebar background | Dark (same as page bg) | Dark (same as page bg) | MATCH |
| 4 | Sidebar icon count | 3 icons (Dashboard, Apps, Logs) | 3 icons (Dashboard, Apps, Logs) | MATCH |
| 5 | Active page indicator | Filled icon with highlight background | Outlined icon with green left border accent | DIFFERENT |
| 6 | Hassette logo/brand mark | Small colored icon at top of sidebar | Small green dot at very top of sidebar | DIFFERENT |
| 7 | Sidebar icon style | Filled SVG icons | Outlined SVG icons | DIFFERENT |

---

### X4-layout-status-bar.png — Layout status bar

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Top status bar | "Connected" with green dot, full width | "Connected" with green dot, full width | MATCH |
| 2 | Status bar position | Top of content area | Top of content area | MATCH |
| 3 | Theme toggle in status bar | Present (icon top-right of status bar) | Present (gear/sun icon top-right) | MATCH |
| 4 | Session info bar (bottom) | Present at page bottom | Missing | GAP |

---

### X6-layout-dark-mode.png — Layout dark mode

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Dark mode background color | Dark charcoal (#1a1a2e or similar) | Dark charcoal (similar tone) | MATCH |
| 2 | Card background in dark | Slightly lighter dark cards | Slightly lighter dark cards | MATCH |
| 3 | Text colors in dark mode | Muted gray labels, white values | Muted gray labels, white values | MATCH |
| 4 | Green accent color | Teal/emerald green for status, values | Teal/emerald green for status, values | MATCH |
| 5 | Session info bar | Present | Missing | GAP |
| 6 | Theme toggle icon | Sun/gear icon | Sun/gear icon | MATCH |

---

### X7-layout-light-mode.png — Layout light mode

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Light mode colors | White/light gray background | White/light gray background | MATCH |
| 2 | Card borders in light | Subtle borders visible | Subtle borders visible | MATCH |
| 3 | Sidebar appearance | Stays dark in light mode | Stays dark in light mode | MATCH |
| 4 | Session info bar | Present | Missing | GAP |
| 5 | Theme toggle icon | Refresh-style icon | Moon icon (indicating switch to dark) | IMPROVEMENT |
| 6 | Overall light mode rendering | Clean, high contrast | Clean, high contrast | MATCH |

---

### A1-apps-all-tab.png — Apps list, All tab

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Page heading | "App Management" with layers icon | "App Management" with grid icon | DIFFERENT |
| 2 | Tab bar | "All (7) Running (6) Failed (0) Stopped (0) Disabled (1)" — text links with active underline | "all 7 | running 6 | failed 0 | stopped 0 | disabled 1 | blocked 0" — pill/button style tabs | DIFFERENT |
| 3 | "blocked" tab | Not present in old UI | Present as new tab showing "blocked 0" | IMPROVEMENT |
| 4 | Table columns (old) | APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS | — | — |
| 5 | Table columns (new) | — | NAME, STATUS, CLASS, INSTANCES, ACTIONS | DIFFERENT |
| 6 | "APP KEY" column | Present as first column with monospace code links | Removed; NAME column now serves as the link | DIFFERENT |
| 7 | "NAME" column (old) | Display name as plain text, separate from app_key | Link text, replaces app_key as identifier | DIFFERENT |
| 8 | "ERROR" column | Present showing "—" for no errors | Removed entirely | GAP |
| 9 | "INSTANCES" column | Not present | Present showing instance count (1 or 2) | IMPROVEMENT |
| 10 | App key visibility | Displayed as `code` in first column | Not shown anywhere in the table row | GAP |
| 11 | Status badge styling | Dot + text inline (e.g., "running" with green dot) | Text badge/pill (e.g., "running" in colored text) | DIFFERENT |
| 12 | Action buttons | Two round icon buttons (Stop, Reload) per row | "Stop" and "Reload" text buttons per row | DIFFERENT |
| 13 | Row for disabled app | Shows in All tab with "disabled" status badge | Shows in All tab with "disabled" status badge | MATCH |
| 14 | Multi-instance app (RemoteApp) | Has expand/collapse chevron, shows instance count | Shows "2" in INSTANCES column, no expand chevron visible | GAP |
| 15 | Row hover styling | No visible hover state in screenshot | No visible hover state in screenshot | MATCH |
| 16 | Table wrapped in card | Yes, single card container | No visible card wrapper — table directly in page | DIFFERENT |

---

### A2-apps-running-tab.png — Apps list, Running tab

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Tab active state | "Running (6)" with underline | "running 6" with filled/highlight background | DIFFERENT |
| 2 | Filtered rows | 6 running apps shown | 6 running apps shown | MATCH |
| 3 | Disabled app filtered out | GarageProximityApp not shown | GarageProximityApp not shown | MATCH |
| 4 | Column structure | Same as A1-old (APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS) | Same as A1-new (NAME, STATUS, CLASS, INSTANCES, ACTIONS) | DIFFERENT |
| 5 | Action buttons for running | Stop + Reload buttons visible | Stop + Reload text buttons visible | MATCH |

---

### A4-apps-multi-instance-expanded.png — Apps multi-instance expanded

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Expand/collapse for multi-instance | Chevron icon on RemoteApp row, expandable to show child instances | No expand/collapse mechanism visible | GAP |
| 2 | Child instance rows | Sub-rows appear under parent when expanded, showing individual instance details | Not visible; only shows "2" in INSTANCES column | GAP |
| 3 | Instance-level actions | Visible on expanded child rows | Not available | GAP |
| 4 | Visual grouping | Parent row styled as group header with indented children | Flat table, no hierarchy | GAP |

---

### A5-apps-disabled-tab.png — Apps disabled tab

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Disabled tab active | "Disabled (1)" underlined | "disabled 1" highlighted | DIFFERENT |
| 2 | Filtered result | Shows only GarageProximityApp | Shows only GarageProximityApp | MATCH |
| 3 | Disabled app actions | No action buttons visible (empty ACTIONS column) | No action buttons visible (empty ACTIONS column) | MATCH |
| 4 | Status display | Dot + "disabled" text | "disabled" text badge | DIFFERENT |
| 5 | Error column | Present, shows "—" | Absent | GAP |
| 6 | Instances column | Not present | Present, shows "0" | IMPROVEMENT |

---

### A6-apps-table-structure.png — Apps table structure

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Column count | 6 (APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS) | 5 (NAME, STATUS, CLASS, INSTANCES, ACTIONS) | DIFFERENT |
| 2 | Column headers style | Uppercase, muted color | Uppercase, muted color | MATCH |
| 3 | Table density | Dense rows, compact | Similar density | MATCH |
| 4 | App key in code font | Yes, monospace `code` styling | Not present | GAP |
| 5 | Overall table width usage | Full width | Full width | MATCH |

---

### AD1-app-detail-header.png — App detail header

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Breadcrumb | "Apps / OfficeButtonApp" | "Apps / OfficeButtonApp" | MATCH |
| 2 | App title | "OfficeButtonApp" with layers icon + status badge | "OfficeButtonApp" with gear icon + status badge | DIFFERENT |
| 3 | Status badge in title | Dot-style "running" badge | Dot-style "running" badge | MATCH |
| 4 | Action buttons | "Stop" (red outline) + "Reload" (outline) — top right | "Stop" (red outline) + "Reload" (outline) — top right | MATCH |
| 5 | Instance metadata | "Instance 0 - PID OfficeButtonApp.office_button" | "Instance 0 - PID OfficeButtonApp.office_button_app" | MATCH |
| 6 | Health strip cards (old) | STATUS ("Running"), ERROR RATE ("0.0%"), HANDLER AVG ("50.2 ms"), JOB AVG ("—") | — | — |
| 7 | Health strip cards (new) | — | STATUS ("running"), ERROR RATE ("0.0%"), AVG DURATION ("<1ms"), LAST ACTIVITY ("—") | DIFFERENT |
| 8 | "STATUS" card value casing | "Running" (title case) | "running" (lowercase) | GAP |
| 9 | "HANDLER AVG" → "AVG DURATION" | "HANDLER AVG" label with "50.2 ms" | "AVG DURATION" label with "<1ms" | DIFFERENT |
| 10 | "JOB AVG" → "LAST ACTIVITY" | "JOB AVG" showing "—" | "LAST ACTIVITY" showing "—" | DIFFERENT |
| 11 | Health card count | 4 cards | 4 cards | MATCH |

---

### AD3-app-detail-health-strip.png — App detail health strip

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Card labels | STATUS, ERROR RATE, HANDLER AVG, JOB AVG | STATUS, ERROR RATE, AVG DURATION, LAST ACTIVITY | DIFFERENT |
| 2 | Status value casing | "Running" | "running" | GAP |
| 3 | Handler avg value | "50.2 ms" | "<1ms" (data differs, format similar) | MATCH |
| 4 | Card border styling | Subtle left-colored border on STATUS card | No colored border visible | DIFFERENT |
| 5 | Card spacing | Tight horizontal layout | Similar tight layout | MATCH |

---

### AD4-app-detail-handlers-collapsed.png — App detail handlers collapsed

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Section heading | "Event Handlers (4 registered)" with bell icon | "Event Handlers (4 registered)" with bell icon | MATCH |
| 2 | Handler rows | 4 handler rows with description text | 4 handler rows with description text | MATCH |
| 3 | Handler description line 1 | "Fires on hass.event.state_changed.event.office_button_action entity event.office_button_action and state changed" | Same text | MATCH |
| 4 | Handler subtitle (module path) | "hassette.office_button_app.OfficeButtonApp.handle_office_button > hassette.on.state_changed/office_button_action" | "hassette.office_button_app.OfficeButtonApp.handle_office_button" | DIFFERENT |
| 5 | Invocation count badge | Right-aligned "67 fits, 0ms avg" or similar stats | Right-aligned stats visible | MATCH |
| 6 | Expand/collapse chevron | Right chevron ">" per handler row | Right chevron ">" per handler row | MATCH |
| 7 | Handler row separator | Subtle horizontal lines | Subtle horizontal lines | MATCH |
| 8 | Scheduled Jobs section | "Scheduled Jobs (0 active)" visible below | "Scheduled Jobs (0 active)" visible below | MATCH |
| 9 | Logs section heading | "Logs" visible at bottom | "Logs" visible at bottom | MATCH |

---

### AD5-app-detail-handler-expanded.png — App detail handler expanded

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Expanded handler | First handler expanded to show invocation history | First handler expanded to show invocation history | MATCH |
| 2 | Invocation table columns (old) | STATUS, TIMESTAMP, DURATION, ERROR | — | — |
| 3 | Invocation table columns (new) | — | TIME, DURATION, STATUS, ERROR | DIFFERENT |
| 4 | Column order | STATUS first, then TIMESTAMP | TIME first, then DURATION | DIFFERENT |
| 5 | Timestamp format | Absolute "03/21 09:04:24 AM" (date + time) | Time only "8:43:24 AM" (no date) | DIFFERENT |
| 6 | Status values | "success" green badges per row | "success" green badges per row | MATCH |
| 7 | Duration values | "156.0ms" format | "158ms" format (no decimal) | DIFFERENT |
| 8 | Error column | Shows "—" for no error | Shows "—" for no error | MATCH |
| 9 | Row count visible | ~25+ rows visible | ~25+ rows visible | MATCH |
| 10 | Pagination controls | "67 fits, 0ms avg" stats at top + pagination arrows | Stats at top with pagination | MATCH |
| 11 | Other handlers below | 3 remaining handlers shown collapsed | 3 remaining handlers shown collapsed | MATCH |
| 12 | Jobs section visible | "Scheduled Jobs (0 active)" at bottom | "Scheduled Jobs (0 active)" at bottom | MATCH |
| 13 | Logs section visible | Log filter controls visible at bottom | Log filter controls visible at bottom | MATCH |

---

### AD6-app-detail-invocation-table.png — App detail invocation table

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Table structure | Same as AD5 — expanded invocation history | Same as AD5 — expanded invocation history | MATCH |
| 2 | Column headers | STATUS, TIMESTAMP, DURATION, ERROR | TIME, DURATION, STATUS, ERROR | DIFFERENT |
| 3 | Timestamp format | Full date+time "03/21 09:04:24 AM" | Time only "8:43:24 AM" | DIFFERENT |
| 4 | Duration decimals | "156.0ms" (1 decimal) | "158ms" (no decimal) | DIFFERENT |
| 5 | Sort indicators on columns | Up/down arrows on TIMESTAMP and DURATION | Up/down arrows on TIME column | DIFFERENT |

---

### AD7-app-detail-jobs-collapsed.png — App detail jobs collapsed (AndysTrackerApp)

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | App shown | AndysTrackerApp | AndysTrackerApp | MATCH |
| 2 | Handlers section | "Event Handlers (0 registered)" with "No event handlers registered." | "Event Handlers (0 registered)" with "No handlers registered." | DIFFERENT |
| 3 | Empty handlers text | "No event handlers registered." | "No handlers registered." | DIFFERENT |
| 4 | Jobs section heading | "Scheduled Jobs (2 active)" | "Scheduled Jobs (2 active)" | MATCH |
| 5 | Job rows | "andys_tracker_job" (cron 0 0 * * *0) and "run" | "andys_tracker_job" (cron) and "run" | MATCH |
| 6 | Job subtitle | Full cron expression visible | "cron" label only | DIFFERENT |
| 7 | Job stats | "1 runs 228.7ms avg" and "24 runs 439.7ms avg" | "6 runs" and "1 runs 322ms avg 6m ago" | DIFFERENT |
| 8 | Job activity indicator | No dot indicator | Green dot on "run" job (indicating recent activity) | IMPROVEMENT |
| 9 | Health strip | STATUS, ERROR RATE, HANDLER AVG ("—"), JOB AVG ("435.2 ms") | STATUS, ERROR RATE, AVG DURATION ("<1ms"), LAST ACTIVITY ("6m ago") | DIFFERENT |
| 10 | "LAST ACTIVITY" metric | Not present (was JOB AVG) | Shows "6m ago" — relative time | DIFFERENT |

---

### AD8-app-detail-job-expanded.png — App detail job expanded

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Expanded job | "run" job expanded to show execution history | "run" job expanded to show execution history | MATCH |
| 2 | Execution table columns (old) | STATUS, TIMESTAMP, DURATION, SIZE/ERROR | — | — |
| 3 | Execution table columns (new) | — | TIME, DURATION, STATUS, ERROR | DIFFERENT |
| 4 | Column order | STATUS first | TIME first | DIFFERENT |
| 5 | Timestamp format | Full date+time "03/20 9:04:00 PM" | Time only "9:15:08 AM" | DIFFERENT |
| 6 | Duration format | "200.0ms" (1 decimal) | "323ms" (no decimal) | DIFFERENT |
| 7 | Row count visible | ~25 rows | ~25 rows | MATCH |
| 8 | Pagination | Present with arrow controls | Present with arrow controls | MATCH |
| 9 | Logs section at bottom | Level filter + Search + 0 entries | Level filter + Search + 0 entries | MATCH |

---

### AD9-app-detail-execution-table.png — App detail execution table

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Content | Same as AD8 (expanded job with execution rows) | Same as AD8 (expanded job with execution rows) | MATCH |
| 2 | All differences | Same as AD8 analysis | Same as AD8 analysis | MATCH |

---

### AD10-app-detail-logs-section.png — App detail logs section

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Logs heading | "Logs" with document icon | "Logs" with document icon | MATCH |
| 2 | Level filter dropdown (old) | "All Levels" dropdown | — | — |
| 3 | Level filter dropdown (new) | — | "INFO" dropdown (default to INFO, not All Levels) | DIFFERENT |
| 4 | Search input | "Search..." text input | "Search logs..." text input | DIFFERENT |
| 5 | Entry count | "0 entries" | "0 entries" | MATCH |
| 6 | Log table columns (old) | LEVEL, TIMESTAMP, MESSAGE | — | — |
| 7 | Log table columns (new) | — | TIME, LEVEL, MESSAGE | DIFFERENT |
| 8 | Column order | LEVEL first | TIME first | DIFFERENT |
| 9 | Sort indicators | Sort arrows on LEVEL, TIMESTAMP, MESSAGE | Sort arrow on TIME (descending) | DIFFERENT |
| 10 | Empty state text (old) | "No log entries." | — | — |
| 11 | Empty state text (new) | — | No visible empty state text | MATCH |
| 12 | Full-page logs: App column | Not present in app detail (only in global logs) | Not present in app detail | MATCH |

---

### AD14-app-detail-disabled.png — App detail disabled app

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | App shown | GarageProximityApp | GarageProximityApp | MATCH |
| 2 | Status badge | "disabled" with gray dot | "disabled" with gray dot | MATCH |
| 3 | Health strip cards | STATUS ("Disabled"), ERROR RATE ("0.0%"), HANDLER AVG ("—"), JOB AVG ("—") | STATUS ("disabled"), ERROR RATE ("0.0%"), AVG DURATION ("<1ms"), LAST ACTIVITY ("—") | DIFFERENT |
| 4 | Status value casing | "Disabled" (title case) | "disabled" (lowercase) | GAP |
| 5 | Action buttons | No Stop/Reload buttons visible | No Stop/Reload buttons visible | MATCH |
| 6 | Instance metadata | "Instance 0 - PID GarageProximityApp.garage_proximity" (no block_reason) | "Instance 0 - PID GarageProximityApp.garage_proximity" | MATCH |
| 7 | Handlers section | "Event Handlers (0 registered)" + "No event handlers registered." | "Event Handlers (0 registered)" + "No handlers registered." | DIFFERENT |
| 8 | Jobs section | "Scheduled Jobs (0 active)" + "No scheduled jobs." | "Scheduled Jobs (0 active)" + "No scheduled jobs." | MATCH |
| 9 | Logs section | Present with filters and empty table | Present with filters and empty table | MATCH |
| 10 | Log level default | "All Levels" dropdown | "INFO" dropdown | DIFFERENT |

---

### AD15-app-detail-multi-instance.png — App detail multi-instance

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | App shown | RemoteApp | RemoteApp | MATCH |
| 2 | Instance selector/tabs | Not visible — shows single instance view | Not visible — shows single instance view | MATCH |
| 3 | Instance metadata | "Instance 0 - PID RemoteApp.jessica_remote" and "jessica_remote.jessica@" visible | Instance metadata visible | MATCH |
| 4 | Health strip | STATUS, ERROR RATE, HANDLER AVG ("69.8 ms"), JOB AVG | STATUS, ERROR RATE, AVG DURATION ("<1ms"), LAST ACTIVITY ("—") | DIFFERENT |
| 5 | Handler section | "Event Handlers (1 registered)" with one handler | "Event Handlers (1 registered)" with one handler | MATCH |
| 6 | Jobs section | "Scheduled Jobs (0 active)" | "Scheduled Jobs (0 active)" | MATCH |
| 7 | Logs section | Present | Present | MATCH |
| 8 | Instance navigation | Not visible in screenshot (may require separate tab/URL) | Not visible in screenshot | MATCH |

---

### L1-logs-default.png — Logs page default view

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Page heading | "Log Viewer" with document icon | "Log Viewer" with document icon | MATCH |
| 2 | Log table columns (old) | LEVEL, TIMESTAMP, APP, MESSAGE | — | — |
| 3 | Log table columns (new) | — | TIME, LEVEL, APP, MESSAGE | DIFFERENT |
| 4 | Column order | LEVEL first | TIME first | DIFFERENT |
| 5 | Level filter (old) | "All Levels" dropdown | — | — |
| 6 | Level filter (new) | — | "INFO" dropdown | DIFFERENT |
| 7 | App filter (old) | "All Apps" dropdown | — | — |
| 8 | App filter (new) | — | Not visible in toolbar (may be removed or different location) | GAP |
| 9 | Search input | Present | Present | MATCH |
| 10 | Entry count | Visible | Visible | MATCH |
| 11 | Timestamp format | Absolute "9:07:08 AM" | Relative or time-only format | DIFFERENT |
| 12 | Level badges | Colored badges (INFO green, WARNING yellow, ERROR red) | Colored badges (INFO green, WARNING yellow, ERROR red) | MATCH |
| 13 | ERROR row highlighting | Red/pink background on error rows | Red/pink background on error rows | MATCH |
| 14 | WARNING row highlighting | Yellow/amber badge, no row highlight | Yellow/amber badge, no row highlight | MATCH |
| 15 | Log message text wrapping | Messages appear to wrap or truncate | Messages appear to wrap or truncate | MATCH |
| 16 | Sort indicators | Sort arrows on column headers | Sort arrow on TIME column (descending) | DIFFERENT |

---

### L2-logs-error-filter.png — Logs error filter

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Level filter set to ERROR | "ERROR" in dropdown | "ERROR" in dropdown | MATCH |
| 2 | App filter | "All Apps" dropdown visible | Not visible | GAP |
| 3 | Filtered result | 1 entry: ERROR from laundry_room_lights | 1 entry: ERROR from laundry_room_lights | MATCH |
| 4 | Error row styling | Red ERROR badge, no full-row highlight | Full-row pink/red highlight | IMPROVEMENT |
| 5 | Columns in filtered view | LEVEL, TIMESTAMP, APP, MESSAGE | TIME, LEVEL, APP, MESSAGE | DIFFERENT |
| 6 | Timestamp format | "9:07:13 AM" | "9:15:03 AM" (different session but same format style) | MATCH |
| 7 | Search input | Present with "Search..." placeholder | Present with "Search logs..." placeholder | DIFFERENT |

---

### L7-logs-app-column.png — Logs app column

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | APP column presence | Present, showing app_key per log row | Present, showing app_key per log row | MATCH |
| 2 | APP column links | app_key displayed as colored links (clickable to app detail) | app_key displayed as colored links | MATCH |
| 3 | APP column position | 3rd column (after LEVEL, TIMESTAMP) | 3rd column (after TIME, LEVEL) | DIFFERENT |
| 4 | Multiple apps visible | Multiple different app keys visible in column | Multiple different app keys visible | MATCH |

---

### E1-error-404.png — 404 error page

| # | Element | Old UI | New UI | Classification |
|---|---------|--------|--------|----------------|
| 1 | Error page content (old) | Raw JSON: `{"detail":"Not Found"}` — no styled error page | — | — |
| 2 | Error page content (new) | — | Styled "404" heading + "Page not found." + "Back to Dashboard" button | IMPROVEMENT |
| 3 | Sidebar | Not present (raw API response) | Present with sidebar and status bar | IMPROVEMENT |
| 4 | Connection status | Not shown | "Connected" bar shown | IMPROVEMENT |
| 5 | Navigation | No way to navigate back | "Back to Dashboard" button provides navigation | IMPROVEMENT |

---

## Summary

### Totals by Classification

| Classification | Count |
|----------------|-------|
| **GAP** | 20 |
| **REGRESSION** | 0 |
| **DIFFERENT** | 54 |
| **IMPROVEMENT** | 12 |
| **MATCH** | 103 |

### GAP Inventory (must fix)

| # | Location | Description |
|---|----------|-------------|
| G1 | D1, D4, D5, X4, X6, X7 | **Session info bar missing** — old UI showed "Hassette v0.23.0 Started [timestamp]" at bottom of dashboard; completely absent in new UI |
| G2 | D1 | **Recent Errors empty state text truncated** — old: "No recent errors. All systems healthy." vs new: "No recent errors." |
| G3 | A1, A6 | **APP KEY column removed** — old UI showed `app_key` in monospace code font as first column; new UI removed it entirely, only showing display_name |
| G4 | A1, A5 | **ERROR column removed from apps table** — old UI had an ERROR column showing error messages or "—"; new UI dropped it |
| G5 | A1, A4 | **Multi-instance expand/collapse missing** — old UI had chevron to expand RemoteApp into child instance rows; new UI only shows instance count |
| G6 | A4 | **Child instance rows missing** — old UI showed individual instance details as sub-rows; new UI has no instance hierarchy |
| G7 | A4 | **Instance-level actions missing** — old UI provided per-instance Stop/Reload on expanded child rows |
| G8 | AD1, AD3, AD14 | **Status value casing** — old: "Running"/"Disabled" (title case); new: "running"/"disabled" (lowercase) |
| G9 | L1, L2 | **App filter dropdown missing from logs page** — old UI had "All Apps" dropdown for filtering by app; new UI removed it |

### DIFFERENT Inventory (intentional changes, verify intent)

Key intentional differences across multiple screenshots:
- **Timestamp format**: absolute timestamps (old) vs relative time (new) in dashboard health cards
- **Health strip labels**: "HANDLER AVG"/"JOB AVG" (old) vs "AVG DURATION"/"LAST ACTIVITY" (new)
- **Table column order**: STATUS first (old) vs TIME first (new) in invocation/execution/log tables
- **Duration format**: 1 decimal "156.0ms" (old) vs integer "158ms" (new)
- **Tab bar style**: text links with underline (old) vs pill/button style (new)
- **Sidebar icon style**: filled (old) vs outlined (new)
- **Log level default**: "All Levels" (old) vs "INFO" (new)
- **Column differences**: APP KEY+NAME+ERROR (old) vs NAME+INSTANCES (new) in apps table

### IMPROVEMENT Inventory

Key improvements:
- **404 error page**: raw JSON (old) vs styled page with navigation (new)
- **"blocked" tab**: new filter tab not present in old UI
- **INSTANCES column**: new column showing instance count
- **Error row highlighting**: full-row pink highlight for errors in log table (new)
- **Job activity indicator**: green dot on recently-active jobs (new)
- **Theme toggle icon**: contextual moon/sun icon (new) vs generic icon (old)
