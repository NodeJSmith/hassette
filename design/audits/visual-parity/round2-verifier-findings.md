# Round 2 Visual Parity — Verifier Findings

Independent adversarial review comparing old UI screenshots to new Preact SPA screenshots.

---

## Dashboard (D1, D4, D5)

### D1 — Dashboard Default (dark mode)

**Old UI elements enumerated:**
- Connection status bar: green dot + "Connected" text, top-left
- KPI strip: 5 bordered cards (APPS 7 / ERROR RATE 0.0% / HANDLERS 30 / JOBS 11 / UPTIME 0h 1m), each with sub-detail text
- App Health section: gear icon + "App Health" heading, 7 app cards in grid (5 columns wide, 2 rows), each card has: app name as link, green/grey dot + "running"/"disabled" badge, handler/job counts, teal health bar, optional "Last: 9:07:14 AM" timestamp
- "Manage Apps" link at bottom of health grid
- Recent Errors section: warning icon + heading, "No recent errors. All systems healthy." message
- Status bar at bottom: "Hassette v0.23.0 Started 3/21/2026, 9:07:12 AM"
- Sidebar: 4 icons (dashboard, apps, ?, logs), dashboard highlighted teal

**New UI comparison:**
1. **MATCH** - Connection status bar present and styled correctly
2. **MATCH** - KPI strip present with 5 bordered cards, correct labels/values
3. **MATCH** - App Health grid present with correct app cards
4. **MATCH** - Manage Apps link present
5. **MATCH** - Recent Errors section present
6. **MATCH** - Status bar present
7. **MINOR DIFF** - Uptime shows "0h 4m" vs old "0h 1m" — time difference, not a bug

### D5 — Dashboard Light Mode

**Old UI elements:**
- Light background (white/light grey), same structure as D1
- KPI cards have subtle borders on light background
- Sidebar icons are dark on light background
- Refresh button visible in top-right corner (circular arrow icon)

**New UI comparison:**
1. **MATCH** - Light mode rendering appears correct, good contrast
2. **MATCH** - Refresh button visible top-right
3. **MATCH** - KPI cards maintain borders in light mode

---

## Apps List (A1, A2, A4, A5, A6)

### A1 — Apps All Tab

**Old UI elements:**
- Page heading: gear icon + "App Management"
- Tab bar: "All (7)", "Running (6)", "Failed (0)", "Stopped (0)", "Disabled (1)" — all as text links, active tab has teal underline, no visible border around each tab
- Table headers: APP KEY, NAME, CLASS, STATUS, ERROR, ACTIONS — uppercase, light grey text, single bottom border
- Table rows: 7 apps, app_key as teal link in code font, status column has small colored badges (running=green, disabled=grey), action column has Stop/Reload button pairs for running apps
- Action buttons show icon + label text ("Stop", "Reload") with visible borders

**New UI comparison:**
1. **FINDING: Tab styling mismatch (MEDIUM)** — New UI renders tabs as bordered pill/button shapes with visible borders around each tab text. Old UI had simple text tabs with only an underline on the active tab and no per-tab borders. The new uses `ht-tab-bar` / `ht-tab` CSS classes that DO NOT EXIST in global.css — the old used `ht-tabs` with `<ul><li><a>` markup. This means tabs are unstyled (rely on browser defaults for buttons), creating a visible bordered-rectangle appearance instead of the old clean underlined text tabs.
2. **FINDING: Extra tab "Blocked (0)" (LOW)** — New UI adds a "Blocked (0)" tab not present in old UI. This is a feature addition, not a parity issue.
3. **FINDING: Reload button styling changed (MEDIUM)** — Old used `ht-btn--info` (blue border) for Reload. New uses `ht-btn--ghost` (transparent border). This significantly reduces the visibility of the Reload action.
4. **FINDING: Stop icon rendering changed (LOW)** — Old used filled rect SVG (`fill="currentColor"`). New uses stroke-only outlined rect (`fill="none"`). Visual difference is subtle but present.

### A5 — Apps Disabled Tab

**Old UI elements:**
- Table shows only garage_proximity row
- Status shows grey dot + "disabled" text
- No action buttons for disabled app
- Error column shows em dash

**New UI comparison:**
1. **FINDING: Status badge dot missing on disabled status (MEDIUM)** — Old showed a small grey dot before "disabled" text. New shows just "disabled" text without a dot. The small badge variant in new StatusBadge component uses `ht-badge ht-badge--sm ht-badge--neutral` (no dot), while old used the same class. Looking more carefully at the old screenshot, the disabled status in the table row does show just text without dot (the small badge variant), so this may be consistent after all. However the dot IS visible in the old A5 screenshot before "disabled".

---

## App Detail (AD1 through AD15)

### AD1 — App Detail Header

**Old UI elements:**
- Breadcrumb: "Apps / OfficeButtonApp"
- App title: gear icon + "OfficeButtonApp" + green dot + "running" badge
- Instance line: "Instance 0 · PID OfficeButtonApp.office_button"
- Action buttons: blue "Stop" button + blue "Reload" button in top-right
- Health strip: 4 cards (STATUS: Running / ERROR RATE: 0.0% / HANDLER AVG: empty or value / JOB AVG: value)

**New UI comparison:**
1. **MATCH** - Breadcrumb and title correct
2. **FINDING: Action button placement differs (LOW)** — Old placed Stop + Reload buttons inline with the page heading. New places them similarly but Reload is ghost-styled (see A1 finding).
3. **FINDING: Health strip label "HANDLER AVG" value format changed (LOW)** — Old showed "50.2 ms" (one decimal + space + "ms"). New shows "<1ms" (no space, no decimal). The `formatDuration` function handles this differently — values < 1 become "<1ms", values >= 1 are rounded integers (e.g., "137ms" not "137.0 ms"). Old Jinja used `"%.1f"|format()` for one decimal place.

### AD4 — Handlers Collapsed

**Old UI elements:**
- Section heading: bell icon + "Event Handlers (4 registered)"
- 4 handler rows, each with: colored dot (green), handler title text, subtitle with method path, right-side stats (calls count, avg duration), chevron arrow (>)
- Chevron is an SVG right-pointing triangle

**New UI comparison:**
1. **FINDING: Chevron/expand indicator MISSING (HIGH)** — Old UI rendered an SVG `<polyline points="4 2 8 6 4 10"/>` inside `ht-item-row__chevron`. New code renders `<span class="ht-item-row__chevron" />` with NO child content. The CSS defines the container size and rotation transition but has no `::before`/`::after` pseudo-element to draw a visible indicator. The expand affordance is completely invisible. Users cannot tell which rows are expandable.

### AD5 — Handler Expanded + Invocation Table

**Old UI elements:**
- Expanded handler row with detail panel below
- Invocation table columns: STATUS, TIMESTAMP, DURATION, ERROR
- Status column shows colored badges (success=green)
- Timestamp format: "03/21 09:04:24 AM"
- Duration format: "158.0ms" (one decimal)

**New UI comparison:**
1. **FINDING: Invocation table column order changed (MEDIUM)** — Old order: STATUS, TIMESTAMP, DURATION, ERROR. New order: Time, Duration, Status, Error. The STATUS column moved from first to third position, and column headers changed from uppercase to title-case.
2. **FINDING: Expanded detail panel class mismatch (HIGH)** — New code uses `ht-item-row__detail` CSS class (handler-row.tsx line 84). The global.css only defines `ht-item-detail` (not `ht-item-row__detail`). This means the expanded panel has NO background color, NO padding, and NO border-top separator. The old UI's dark recessed background for expanded content is lost.
3. **FINDING: Duration format changed (LOW)** — Old: "158.0ms" (one decimal). New: "158ms" (integer). Subtle but noticeable with many values.

### AD7 — Jobs Collapsed

**Old UI elements:**
- Section heading: clock icon + "Scheduled Jobs (2 active)"
- 2 job rows with dots, names, trigger info, stats, chevrons
- Job subtitle shows "cron: 0 0 * * * 0" trigger info

**New UI comparison:**
1. **MATCH** - Job rows render correctly
2. **SAME CHEVRON ISSUE** as AD4 — expand indicators invisible on job rows too

### AD8/AD9 — Job Expanded + Execution Table

**Old UI elements:**
- Expanded job with execution history table
- Columns: STATUS, TIMESTAMP, DURATION, GPS, ERROR
- Status badges in first column

**New UI comparison:**
1. **FINDING: Execution table column order matches invocation table issue** — Same column reordering as handler invocations
2. Same detail panel class mismatch as handlers

### AD10 — Logs Section

**Old UI elements:**
- Section heading: document icon + "Logs"
- Log toolbar: Level dropdown, Search input, "X entries" badge
- Log table: LEVEL, TIMESTAMP, MESSAGE columns
- Sticky header row
- Sort indicators on column headers (small up/down arrows)
- All columns have sort indicators via `sortIndicator()` function

**New UI comparison:**
1. **FINDING: Sort indicators removed from Level and Message columns (MEDIUM)** — Old had `sortIndicator('level')` and `sortIndicator('message')` on all four columns. New only has a toggle on Timestamp (↑/↓). Level and Message columns are no longer sortable.
2. **MATCH** - Level dropdown and search input present

### AD14 — App Detail Disabled

**Old UI elements:**
- App title shows grey dot + "disabled" text
- No action buttons shown (correct for disabled)
- Health strip shows: STATUS: Disabled, ERROR RATE: 0.0%, HANDLER AVG: — (em dash), JOB AVG: — (em dash)
- Empty handlers section: "No event handlers registered."
- Empty jobs section: "No scheduled jobs."
- Log viewer with dropdowns + empty table

**New UI comparison:**
1. **FINDING: Handler AVG shows value instead of em dash for disabled apps (LOW)** — Old showed "—" for HANDLER AVG on disabled app. New shows "<1ms". This appears to be a data issue from the backend providing a default value rather than null, but visually it looks wrong for a disabled app that has never run.
2. **FINDING: Instance line format changed (LOW)** — Old: "Instance 0 · PID OfficeButtonApp.office_button". New: "Instance 0" (no PID information shown).
3. **FINDING: Empty handlers text changed (LOW)** — Old: "No event handlers registered." New: "No handlers registered." Wording shortened.

### AD15 — App Detail Multi-Instance

**Old UI elements:**
- Instance selector dropdown: "jessica_remote (running) ▼"
- Shows single instance view for selected instance

**New UI comparison:**
1. **FINDING: Instance selector rendering (MEDIUM)** — Old showed a dropdown selector for multi-instance apps with instance name + status. New shows "INSTANCES: jessica_remote (running) ▼" — the label is slightly different but functionally equivalent.

---

## Logs Page (L1, L2, L7)

### L1 — Logs Default

**Old UI elements:**
- Page heading: document icon + "Log Viewer"
- Toolbar: Level dropdown ("All Levels"), App dropdown ("All Apps"), Search input, "X entries" badge
- Log table with LEVEL, TIMESTAMP, APP, MESSAGE columns
- All columns have sort indicators
- Level badges: DEBUG=grey, INFO=green/teal, WARNING=yellow outlined, ERROR=red filled
- Row alternation or consistent dark background
- App column shows app_key as teal code link
- Messages in monospace-like text

**New UI comparison:**
1. **FINDING: Log row ERROR highlighting CHANGED DRAMATICALLY (HIGH)** — Old UI: ERROR rows have the same row background as other rows; only the ERROR badge in the Level column has a red background. New UI: The CSS class `.ht-log-error` applies `background: var(--ht-danger)` to the ENTIRE ROW, creating a bright red/pink full-width highlight. This is confirmed in L2 screenshot where the error row is completely pink/red. The old UI was much more subtle — the error was indicated by the badge only.
2. **FINDING: WARNING badge styling changed (MEDIUM)** — Old: WARNING badge had yellow/amber background with dark text. New: `.ht-log-warning` applies `color: var(--ht-bg); background: var(--ht-warning)` as a row-level class. But the badge itself is rendered as `ht-badge--warning` which uses `color: var(--ht-warning); background: var(--ht-warning-light)`. The row class and badge class may conflict or double-apply.
3. **FINDING: INFO badge styling difference (LOW)** — Old: INFO rows showed a teal/green badge. New: INFO badge uses `ht-badge--success` (green). In the old Jinja template's Alpine.js `levelClass()` function, INFO mapped to a teal class. The new maps INFO to "success" which is green — semantically similar but could be a different shade.

### L2 — Logs Error Filter

**Old UI elements:**
- Dropdown shows "ERROR" selected
- Single error row: ERROR badge (red), timestamp, app link "laundry_room_lights", message "Error setting initial enabled state"
- Row background is same dark color as all other rows — NOT highlighted

**New UI comparison:**
1. **CONFIRMED: Error row has full pink/red background** — This is a dramatic visual change from the old UI. See L1 finding above.
2. **FINDING: Level badge MISSING from error row (MEDIUM)** — In old L2, the ERROR row shows a red ERROR badge in the Level column. In new L2, the Level column appears to not show a badge text — the entire row is red and the badge may be lost in the background color. Hard to see badge text against the red background.

---

## Error Page (E1)

**Old UI elements:**
- Raw JSON response: `{"detail":"Not Found"}` on white background
- No app chrome (sidebar, header, etc.)

**New UI comparison:**
1. **IMPROVEMENT** — New shows a proper 404 page within the app layout, with "404", "Page not found.", and a "Back to Dashboard" button. This is better than the old raw JSON response.

---

## Layout (X1, X4, X6, X7)

### Sidebar

**Old UI elements:**
- 4 icon buttons: dashboard (grid), apps (people/network), ?, logs (document)
- Active page highlighted with teal background
- Icons are simple line art

**New UI comparison:**
1. **MATCH** - Sidebar icons match in position and highlight behavior
2. **MATCH** - Active state highlighting works correctly

### Light/Dark Mode

1. **MATCH** - Theme toggle (sun icon) present in top-right corner
2. **MATCH** - Light mode renders with correct token values
3. **MATCH** - Dark mode renders correctly

---

## Missing CSS Classes Summary

These CSS classes are used in components but have NO definition in global.css:

| Class | Used in | Impact |
|---|---|---|
| `ht-tab-bar` | status-filter.tsx | Tab container unstyled |
| `ht-tab` | status-filter.tsx | Individual tabs unstyled |
| `ht-item-row__detail` | handler-row.tsx, job-row.tsx | Expanded detail panel has no background/padding |
| `ht-table-compact` | handler-invocations.tsx, job-executions.tsx, log-table.tsx | No effect (intended to be tighter rows) |
| `ht-table-log` | log-table.tsx | No effect |
| `ht-log-table-container` | log-table.tsx | No effect |
| `ht-log-filters` | log-table.tsx | Filter toolbar unstyled |
| `ht-log-row` | log-table.tsx | No effect |
| `ht-log-message` | log-table.tsx | No effect |
| `ht-select-sm` | log-table.tsx | Should be `ht-select--sm` |
| `ht-input-sm` | log-table.tsx | Should be `ht-input--sm` |
| `ht-sortable` | log-table.tsx | Cursor/hover styling missing |
| `ht-instance-row` | manifest-row.tsx | Instance sub-rows unstyled |
| `ht-chevron-inline` | manifest-row.tsx | Expand chevron for multi-instance unstyled |
| `ht-status-text--*` | health-strip.tsx | Status value coloring in health cards |

---

## TOP 5 MOST LIKELY-TO-BE-MISSED FINDINGS

### 1. Expand chevron indicators are INVISIBLE (HIGH)
Handler rows and job rows render an empty `<span class="ht-item-row__chevron"/>` with no visible content. The old UI had an SVG right-pointing triangle. Users cannot see that rows are expandable. This is a core usability regression.

### 2. Tab bar is completely unstyled — uses nonexistent CSS classes (HIGH)
The status filter tabs on the apps page use `ht-tab-bar` and `ht-tab` CSS classes that do not exist. The old UI used `ht-tabs` / `li` / `a` structure. The result is browser-default button rendering (bordered rectangles) instead of the old clean underlined text tabs.

### 3. Expanded detail panel has wrong CSS class — no background/padding (HIGH)
New code uses `ht-item-row__detail` but CSS defines `ht-item-detail`. The expanded handler/job detail panels have no recessed background, no padding, and no border-top separator. Content appears flush with the collapsed row.

### 4. Error log rows have full-row red background — old UI had subtle badge-only coloring (MEDIUM)
The `.ht-log-error` CSS class paints the entire table row with `background: var(--ht-danger)`. The old UI only colored the ERROR badge in the Level column. This is a dramatic visual difference that makes the error row extremely prominent, potentially making the badge text unreadable against the red background.

### 5. Reload button changed from visible blue (ht-btn--info) to transparent ghost (ht-btn--ghost) (MEDIUM)
The reload action button lost its visible blue border and hover background. As a ghost button, it has no border and no background until hovered. This reduces the discoverability of the reload action in the app table and detail page, especially since Stop retains its visible warning styling.
