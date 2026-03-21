# Visual Gap Analysis: Old Jinja2 UI vs New Preact SPA

**Date**: 2026-03-20
**Status**: Ready for Implementation
**Scope**: Exhaustive page-by-page, component-by-component comparison

---

## 1. Page-by-Page Comparison

### 1.1 Dashboard (`/`)

#### KPI Strip

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| 5 KPI cards (Apps, Error Rate, Handlers, Jobs, Uptime) | Present | Present | MATCH |
| Error Rate sub-detail ("X / Y invocations" or "No data") | Present | Present | MATCH |
| Handlers sub-detail ("N invoked") | "N invoked" | "N invoked" | MATCH |
| Jobs sub-detail ("N executions") | Present | Present | MATCH |
| Apps sub-detail ("N running") | Present | Present | MATCH |
| Uptime formatting ("Nh Nm") | Present | Present | MATCH |
| Auto-refresh every 30s via htmx | Yes (hx-trigger) | No polling -- WS only | DIFFERENT -- old had periodic GET refresh |

**Preact file**: `frontend/src/components/dashboard/kpi-strip.tsx`
**Old template**: `partials/dashboard_kpi_strip.html`

#### App Health Grid

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| 2-column card grid | Present | Present | MATCH |
| App name + status badge (dot + label) | Present | Present | MATCH |
| Handler/job counts | Present | Present | MATCH |
| Health bar (success rate fill) | Present | Present | MATCH |
| Error rate percentage on card | Shown when total_invocations > 0 with danger/warn color | NOT shown | **GAP** |
| "Last: [time]" footer | Present (toLocaleTimeString) | Present (relative time "Xm ago") | DIFFERENT -- format changed from absolute to relative |
| "Manage Apps" link | Links to `/ui/apps` | Links to `/apps` | MATCH (SPA routing) |
| Live update via WS (`data-live-on-app`) | Yes, htmx live partial refresh | Yes, refetch on appStatus change | MATCH (different mechanism) |

**GAP-D1**: App cards in old UI show error rate percentage (e.g. "2.1% errors") when invocations > 0. New UI does not display this.
- **Preact file**: `frontend/src/components/dashboard/app-card.tsx`
- **Old template**: `partials/dashboard_app_grid.html` (lines with `classify_error_rate`)

**GAP-D2**: Old UI shows "Last: 11:46:48 PM" (absolute time via `toLocaleTimeString`). New UI shows "Last: 2m ago" (relative). This is a design choice difference, not a bug -- but the old UI used absolute timestamps consistently on dashboard cards.
- **Preact file**: `frontend/src/components/dashboard/app-card.tsx` line 43
- **Old template**: `partials/dashboard_app_grid.html` (x-text with toLocaleTimeString)

#### Recent Errors Section

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Section heading with warning icon | Present | Present | MATCH |
| Error type badge (danger badge) | `ht-badge--danger` with `error_type` text | Uses `ht-tag ht-tag-${kind}` with "handler"/"job" as text | **DIFFERENT** |
| App key link | Links to `/ui/apps/{key}` | Links to `/apps/{key}` | MATCH |
| Handler method shown | Present (`err.handler_method`) | NOT shown | **GAP** |
| Timestamp | Present (toLocaleTimeString) | Present (relative time) | DIFFERENT |
| Error message body | Present | Present | MATCH |
| Error type name (e.g. "ValueError") | Shown as badge text | Shown as `<code>` element | DIFFERENT |
| "No recent errors. All systems healthy." | Present | "No recent errors." (shorter text) | **GAP** |

**GAP-D3**: Old error feed shows the handler method (e.g. `on_button_press`) for each error. New UI omits this.
- **Preact file**: `frontend/src/components/dashboard/error-feed.tsx`
- **Old template**: `partials/dashboard_errors.html` (the `err.handler_method` code element)

**GAP-D4**: Old error feed badge shows the actual exception type (e.g. "ValueError") as a danger badge. New UI shows "handler" or "job" as a tag instead. The error_type is shown separately as a code element, but the badge content is different.
- **Preact file**: `frontend/src/components/dashboard/error-feed.tsx` line 18
- **Old template**: `partials/dashboard_errors.html`

**GAP-D5**: Old empty state text is "No recent errors. All systems healthy." -- new is just "No recent errors."
- **Preact file**: `frontend/src/components/dashboard/error-feed.tsx` line 10
- **Old template**: `partials/dashboard_errors.html`

#### Session Info Bar

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Version display ("Hassette v0.23.0") | Present | NOT present | **GAP** |
| Start time ("Started 3/20/2026, 11:46:39 PM") | Present | NOT present | **GAP** |
| Session bar at page bottom | Present | NOT present | **GAP** |

**GAP-D6**: The entire session info bar at the bottom of the dashboard is missing from the new UI. This showed the Hassette version and session start time.
- **Preact file**: `frontend/src/pages/dashboard.tsx` (needs new component)
- **Old template**: `pages/dashboard.html` (the `ht-session-bar` div at the bottom)

---

### 1.2 Apps List (`/apps`)

#### Page Header

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| "App Management" heading with layers icon | Present | Present | MATCH |
| Icon is "layers/boxes" SVG | Old uses 3-layer boxes icon | New uses 4-square grid icon | **DIFFERENT** |

**GAP-A1**: The Apps page heading icon differs. Old UI uses the Lucide "boxes" (3D stacked cubes) icon. New UI uses a 4-square grid icon (like layout-grid). Minor visual inconsistency.
- **Preact file**: `frontend/src/pages/apps.tsx` lines 26-31
- **Old template**: `pages/apps.html` (the SVG in the h1)

#### Status Filter Tabs

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Filter tabs (All, Running, Failed, Stopped, Disabled) | Present as `ht-tabs` with `<ul>/<li>/<a>` | Present as `ht-tab-bar` with `<button>` elements | MATCH (different markup, same function) |
| Count shown in tabs | "Running (5)" format | "running 5" format (lowercase, no parens) | **DIFFERENT** |
| "Blocked" filter | NOT shown in old tabs (only 5 tabs) | Shown as 6th tab | **DIFFERENT** |
| Tabs inside card | Tabs are inside the `ht-card` | Tabs are outside any card | **DIFFERENT** |
| HTMX-driven filtering | Yes (htmx.ajax to swap tbody) | No (client-side filter via signal) | DIFFERENT mechanism |

**GAP-A2**: Old filter tabs use title-case labels with counts in parentheses: "Running (5)". New UI uses lowercase with counts as a separate span: "running 5". The old format was more polished.
- **Preact file**: `frontend/src/components/apps/status-filter.tsx` line 22
- **Old template**: `pages/apps.html` (the filter_tabs loop)

#### Manifest Table

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Columns: App Key, Name, Class, Status, Error, Actions | 6 columns | 5 columns: Name, Status, Class, Instances, Actions | **DIFFERENT** |
| App Key column | Present (linked `<code>` element) | Absent -- Name column is linked instead | **GAP** |
| Error column | Shows error_message in red text or "---" | NOT present | **GAP** |
| Instance count shown | Shown as badge "N instances" in Status column | Shown in dedicated "Instances" column | DIFFERENT |
| Multi-instance expand/collapse | Expandable chevron rows for instances | NOT present | **GAP** |
| Instance sub-rows | Shown with indent, per-instance status/error/actions | NOT present | **GAP** |
| Action buttons in table | Present (Start/Stop/Reload icons, no labels) | Present (Start/Stop/Reload with labels) | DIFFERENT -- old had icon-only in table |
| Table wrapped in card | Yes (`ht-card`) | No wrapping card | **DIFFERENT** |
| Dense table styling | `ht-table--dense` class | Just `ht-table` | DIFFERENT |

**GAP-A3**: The "App Key" column from the old UI (showing the raw key like `office_button`) is missing. The old UI had both App Key and Name; the new UI only has Name (which is the display_name).
- **Preact file**: `frontend/src/components/apps/manifest-row.tsx`
- **Old template**: `partials/manifest_list.html`

**GAP-A4**: The "Error" column is missing from the new manifest table. In the old UI, this showed the error_message in red text for failed apps, or a dash for healthy apps.
- **Preact file**: `frontend/src/components/apps/manifest-row.tsx`
- **Old template**: `partials/manifest_list.html` (the error_message td)

**GAP-A5**: Multi-instance app support is missing from the manifest table. The old UI had:
1. A chevron toggle on the parent row for multi-instance apps
2. Expandable sub-rows for each instance (indented, with per-instance name/status/error/actions)
3. Instance names shown as linked code elements
- **Preact file**: `frontend/src/components/apps/manifest-list.tsx` and `manifest-row.tsx`
- **Old template**: `partials/manifest_list.html` (the `instance_count > 1` conditional block and `ht-instance-row` loop)

**GAP-A6**: The manifest table is not wrapped in an `ht-card` in the new UI. The old UI wrapped the entire filter tabs + table inside a single card.
- **Preact file**: `frontend/src/pages/apps.tsx`
- **Old template**: `pages/apps.html` (the wrapping `ht-card`)

---

### 1.3 App Detail (`/apps/:key`)

#### Breadcrumb

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| "Apps / AppName" breadcrumb | Present | Present | MATCH |
| Link to `/ui/apps` | Yes | Links to `/apps` | MATCH |

#### App Header

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Display name with icon | Present (layers icon) | Present (layers icon) | MATCH |
| Status badge (dot + label) | Present | Present | MATCH |
| Action buttons (Stop/Reload or Start) | Present | Present | MATCH |
| Reload button style | `ht-btn--info` (accent/teal border) | `ht-btn--ghost` (transparent border) | **DIFFERENT** |

**GAP-AD1**: Reload button uses `ht-btn--info` in old UI (accent-colored border) vs `ht-btn--ghost` in new UI (no border). Visual difference in emphasis.
- **Preact file**: `frontend/src/components/apps/action-buttons.tsx` line 71
- **Old template**: `macros/ui.html` (the `action_buttons` macro, `ht-btn--info` class)

#### Instance Metadata

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| "Instance N * PID XXX" line | Shows instance index and PID (owner_id) | Shows "Instance 0" with broken metadata display | **GAP** |
| Instance switcher dropdown (multi-instance) | Present (select with instance names) | NOT present | **GAP** |

**GAP-AD2**: The instance metadata line is broken in the new UI. It shows "Instance 0" followed by a garbled "PID ClassName.appKey" instead of the actual PID. The old UI used `instance.owner_id` for the PID.
- **Preact file**: `frontend/src/pages/app-detail.tsx` lines 87-91
- **Old template**: `pages/app_detail.html` (the `instance-meta` paragraph)

**GAP-AD3**: The instance switcher dropdown for multi-instance apps is completely missing. In the old UI, this was a `<select>` element that let you navigate between instances of the same app.
- **Preact file**: `frontend/src/pages/app-detail.tsx` (needs new component)
- **Old template**: `pages/app_detail.html` (the `is_multi_instance` conditional block)

#### Error Display (for failed/errored apps)

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Error message card | Present (red text in card) | NOT present | **GAP** |
| Expandable traceback | Present (Show/Hide traceback button) | NOT present | **GAP** |

**GAP-AD4**: When an app has an error (failed status), the old UI showed a dedicated error card with the error message in red text and an expandable traceback. The new UI has no error display at all on the app detail page.
- **Preact file**: `frontend/src/pages/app-detail.tsx` (needs new section between header and health strip)
- **Old template**: `pages/app_detail.html` (the `error-display` card with `error_message` and `error_traceback`)

#### Health Strip (KPI cards)

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Status card with capitalized value | "Running" (capitalized) | "running" (lowercase) | **DIFFERENT** |
| Status card color coding | green for running, red for failed | Uses `ht-status-text--{status}` class | Needs verification |
| Error Rate card | Present | Present | MATCH |
| Handler Avg card | Present ("65.4 ms" or "---") | Present (formatDuration) | MATCH |
| Job Avg card | Present ("---" when no data) | **Replaced with "Last Activity"** | **GAP** |
| Live update via polling | Yes (data-live-on-app, htmx partial) | No polling | DIFFERENT |

**GAP-AD5**: The old UI had a "Job Avg" KPI card showing average job execution duration. The new UI replaced this with a "Last Activity" card showing the timestamp of the most recent activity. The old "Job Avg" data is available in the API (`AppHealthData.job_avg_duration`) but is not displayed.
- **Preact file**: `frontend/src/components/app-detail/health-strip.tsx`
- **Old template**: `partials/app_health_strip.html` (the "Job Avg" health_card call)

**GAP-AD6**: The Status card value is lowercase ("running") in the new UI vs capitalized ("Running") in the old UI.
- **Preact file**: `frontend/src/components/app-detail/health-strip.tsx` line 16
- **Old template**: `partials/app_health_strip.html` (uses `|capitalize` filter)

#### Event Handlers Section

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Section heading with bell icon + count | Present | Present | MATCH |
| Handler rows (expandable) | Present | Present | MATCH |
| Dot color (success/danger/neutral) | Present | Present | MATCH |
| Handler summary as title | Shows summary if available, else method name | Shows summary if available, else short method name | MATCH |
| Handler method as subtitle | Shows full method + topic | Shows full method only | **GAP** |
| Stats: calls, failed, avg duration | Present | Present | MATCH |
| "Last invoked" relative time | NOT shown in old (no last_invoked_at display) | Shown in new | IMPROVEMENT |
| Chevron icon (expand/collapse) | SVG chevron (right arrow rotating) | CSS-only chevron (border trick) | DIFFERENT |
| Invocation table on expand | Columns: Status, Timestamp, Duration, Error | Columns: Time, Duration, Status, Error | **DIFFERENT column order** |
| Error traceback row in invocations | Present (expandable pre block) | NOT present | **GAP** |
| Stats polling (keeps counts fresh) | Yes (hidden div with hx-get every 5s) | No polling | DIFFERENT |

**GAP-AD7**: Old handler rows show the event topic in the subtitle when a summary exists (e.g. "Fires on hass.event.state_changed(light.office_b...) * hass.event.state_changed"). New UI only shows the handler method.
- **Preact file**: `frontend/src/components/app-detail/handler-row.tsx` lines 59-63
- **Old template**: `macros/ui.html` (handler_row macro, the subtitle span with `listener.topic`)

**GAP-AD8**: Old invocation table had error traceback rows -- when an invocation had an `error_traceback`, a second row with a `<pre>` block appeared below the invocation row. New UI does not show tracebacks in the invocation table.
- **Preact file**: `frontend/src/components/app-detail/handler-invocations.tsx`
- **Old template**: `partials/handler_invocations.html` (the `error_traceback` conditional tr)

**GAP-AD9**: Invocation table column order differs. Old: Status | Timestamp | Duration | Error. New: Time | Duration | Status | Error.
- **Preact file**: `frontend/src/components/app-detail/handler-invocations.tsx` lines 22-27
- **Old template**: `partials/handler_invocations.html`

#### Scheduled Jobs Section

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Section heading with clock icon + count | Present | Present | MATCH |
| Job rows (expandable) | Present | Present | MATCH |
| Job name as title | Present | Present | MATCH |
| Trigger type + value in subtitle | Shows "trigger_type: trigger_value" | Shows only trigger_type | **GAP** |
| Falls back to handler_method in subtitle | Yes | No (only shows trigger_type or nothing) | **GAP** |
| Execution table on expand | Columns: Status, Timestamp, Duration, Error | Columns: Time, Duration, Status, Error | **DIFFERENT column order** |
| "Last executed" relative time | NOT shown in old | Shown in new | IMPROVEMENT |

**GAP-AD10**: Old job rows show "trigger_type: trigger_value" in the subtitle (e.g. "cron: */5 * * * *"), falling back to `handler_method` when no trigger_type. New UI only shows trigger_type without the trigger_value.
- **Preact file**: `frontend/src/components/app-detail/job-row.tsx` lines 57-59
- **Old template**: `macros/ui.html` (job_row macro subtitle)

#### Logs Section (within App Detail)

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Log table with level filter | Present | Present | MATCH |
| Search input | Present | Present | MATCH |
| Entry count badge | Present (badge style) | Present (plain text) | DIFFERENT |
| App filter dropdown | Not shown (single app) | Not shown | MATCH |
| Sortable columns | All columns sortable (Level, Timestamp, App, Message) | Only Time column sortable | **GAP** |
| Sort indicator text | Up/down arrow characters | Up/down triangle characters | DIFFERENT |
| Level badge styling | Color-coded badges (debug gray, info teal, warning yellow bg, error red bg) | Uses `ht-log-level-{level}` class | Needs CSS check |
| Sticky header | Yes (`position: sticky; top: 0`) | No sticky header specified | **GAP** |
| App column links | Links to `/ui/apps/{key}` | Plain text | **GAP** |
| Log streaming via WebSocket | Present (Alpine.js logTable component) | Present (WS ring buffer) | MATCH |

**GAP-AD11**: Old log table had sortable columns for Level, Timestamp, App, and Message. New log table only supports sorting by Time.
- **Preact file**: `frontend/src/components/shared/log-table.tsx` lines 87-96
- **Old template**: `macros/ui.html` (log_table macro, all four th elements have @click="toggleSort()")

**GAP-AD12**: Old log table had a sticky header (`position: sticky; top: 0; background: var(--ht-surface-sticky)`). New log table does not have a sticky header, so column labels scroll away in long log lists.
- **Preact file**: `frontend/src/components/shared/log-table.tsx` (the thead element)
- **Old template**: `macros/ui.html` (log_table macro, the thead style attribute)

---

### 1.4 App Detail -- Disabled App (`/apps/:key` for disabled app)

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| "disabled" status badge | Gray dot + "disabled" text | Present | MATCH |
| Health strip shows "Disabled" status | "Disabled" (capitalized) with no color | lowercase "disabled" | **GAP** (see GAP-AD6) |
| Empty handlers section | "No event handlers registered." | "No handlers registered." | MATCH (slightly different text) |
| Empty jobs section | "No scheduled jobs." | "No scheduled jobs." | MATCH |
| Empty logs | "No log entries." | "No log entries." (or "0 entries") | MATCH |

---

### 1.5 Logs Page (`/logs`)

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| "Log Viewer" heading with scroll icon | Present | Present | MATCH |
| Log table in card wrapper | Yes (`ht-card`) | No card wrapper | **GAP** |
| App filter dropdown | Present (dropdown with all app keys) | NOT present | **GAP** |
| App column with links | Links to `/ui/apps/{key}` | Plain text (no links) | **GAP** |
| Level filter | All Levels / DEBUG / INFO / etc. | DEBUG / INFO / WARNING / ERROR / CRITICAL (no "All") | **GAP** |
| Default level | "All Levels" (shows everything) | "INFO" (hides DEBUG by default) | **GAP** |

**GAP-L1**: The global logs page is missing the per-app filter dropdown. Old UI had a `<select>` with all app keys to filter logs by app.
- **Preact file**: `frontend/src/components/shared/log-table.tsx`
- **Old template**: `macros/ui.html` (log_table macro, the `app_keys` select)

**GAP-L2**: The logs page log table is not wrapped in a card. Old UI wrapped it in `ht-card`.
- **Preact file**: `frontend/src/pages/logs.tsx`
- **Old template**: `pages/logs.html` (the `ht-card` wrapper)

**GAP-L3**: Old log table level filter had an "All Levels" option that showed everything including DEBUG. New UI starts at "INFO" and has no "All" option.
- **Preact file**: `frontend/src/components/shared/log-table.tsx` lines 8, 17
- **Old template**: `macros/ui.html` (the level select with empty-value "All Levels" option)

**GAP-L4**: App column in log table does not link to the app detail page. Old UI had each app_key as a link to `/ui/apps/{key}`.
- **Preact file**: `frontend/src/components/shared/log-table.tsx` line 103
- **Old template**: `macros/ui.html` (log_table macro, the `<a>` link in app column)

---

## 2. Component-by-Component Gaps

### 2.1 Sidebar / Navigation

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Brand logo image | `hassette-logo.png` (img element, 24px height) | Green pulse dot only | **GAP** |
| Favicon | `hassette-logo.png` | Served from built SPA assets (not checked) | **NEEDS CHECK** |
| 3 nav items (Dashboard, Apps, Logs) | Present | Present | MATCH |
| Active state highlight | Present | Present | MATCH |

**GAP-S1**: The sidebar brand area shows the Hassette logo image in the old UI. The new UI replaces it with just a green pulsing dot. The logo file exists at `src/hassette/web/static/img/hassette-logo.png`.
- **Preact file**: `frontend/src/components/layout/sidebar.tsx` lines 62-64
- **Old template**: `components/nav.html` (the `img` tag in `ht-sidebar-brand`)

### 2.2 Status Bar

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Connection indicator (dot + text) | Present | Present | MATCH |
| "Reconnecting..." state | Not in old (just Connected/Disconnected) | Present | IMPROVEMENT |
| Theme toggle button (sun/moon icons) | Present | Present | MATCH |
| Theme toggle icon visibility logic | JS-based MutationObserver | Conditional rendering | MATCH (different mechanism) |

### 2.3 Alert Banner

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Alert banner for failed apps | Present (`components/alert_banner.html`) | Component exists (`alert-banner.tsx`) but NOT wired in | **GAP** |

**GAP-C1**: The AlertBanner component exists in the new Preact code but is NOT rendered anywhere. In the old UI, it was included in `base.html` via `{% include "components/alert_banner.html" %}` and appeared between the status bar and page content. The new `app.tsx` does not render `AlertBanner`.
- **Preact file**: `frontend/src/app.tsx` (needs to render AlertBanner between StatusBar and Switch)
- **Old template**: `base.html` (the `alert_banner.html` include)

### 2.4 Status Badge

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Dot + label (large) variant | Present | Present | MATCH |
| Small badge variant | Present | Present | MATCH |
| Blocked status support with tooltip | Present (block_reason as title) | Present but not used on manifest table | MATCH |

### 2.5 Health Bar

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| CSS fill bar with health level | Uses `classify_health_bar()` result as class | Uses `healthStatus` prop directly | MATCH |

### 2.6 Action Buttons

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Start (for stopped/failed) | Present | Present | MATCH |
| Stop (for running) | Present | Present | MATCH |
| Reload (for running) | Present (`ht-btn--info`) | Present (`ht-btn--ghost`) | **DIFFERENT** (see GAP-AD1) |
| Labels shown/hidden toggle | `show_labels` parameter | Always shown | DIFFERENT |
| Disabled state support | Not explicit (blocked via status) | Uses `disabled={loading}` | IMPROVEMENT |

---

## 3. Missing Features (Cross-Cutting)

### 3.1 Multi-Instance Support

**GAP-MI1**: The entire multi-instance app workflow is absent from the new UI.

Old UI capabilities:
- App manifest table: expandable instance sub-rows with per-instance status, error, and actions
- App detail page: instance switcher dropdown (`<select>`) to navigate between instances
- App detail page: instance index in URL path (`/apps/:key/:index`)
- Per-instance API calls (instance_index parameter)

New UI state:
- Manifest table shows instance count in a column but no expandable rows
- App detail page hardcodes "Instance 0"
- Router only handles `/apps/:key` (no `:index` parameter)
- API endpoints pass `instanceIndex = 0` always

**Files to change**:
- `frontend/src/components/apps/manifest-list.tsx` -- add expand/collapse rows
- `frontend/src/components/apps/manifest-row.tsx` -- add instance sub-rows
- `frontend/src/pages/app-detail.tsx` -- add instance switcher, parameterize index
- `frontend/src/app.tsx` -- add route `/apps/:key/:index`
- `frontend/src/api/endpoints.ts` -- already supports instanceIndex param

**Old templates**: `partials/manifest_list.html` (instance rows), `pages/app_detail.html` (instance switcher)

### 3.2 Session Bar

**GAP-MI2**: The session info bar at the bottom of the dashboard is entirely missing. See GAP-D6.

Old UI showed:
- Hassette version (e.g. "v0.23.0")
- Session start time (localized datetime)

The version and session data are available:
- `hassette_version` was passed as template context
- `session_summary.started_at` was a Unix timestamp
- The WS `connected` message already provides `session_id`

**Files to change**:
- `frontend/src/pages/dashboard.tsx` -- add session bar component
- New component needed: `frontend/src/components/dashboard/session-bar.tsx`
- May need new API endpoint or WS payload for version info

**Old template**: `pages/dashboard.html` (the `ht-session-bar` div)

### 3.3 Logo / Favicon

**GAP-MI3**: The sidebar brand logo is missing (replaced by pulse dot). See GAP-S1.

The logo file exists at `/src/hassette/web/static/img/hassette-logo.png` and the old UI used it both as the sidebar brand icon and as the favicon.

**Files to change**:
- `frontend/src/components/layout/sidebar.tsx` -- replace pulse dot with img
- `frontend/index.html` (or equivalent) -- add favicon link

### 3.4 Error Display on App Detail

**GAP-MI4**: No error/traceback display for failed apps. See GAP-AD4.

### 3.5 HTMX Page Transition Indicator

| Feature | Old UI | New UI | Status |
|---------|--------|--------|--------|
| Progress bar on page transitions | Present (CSS pseudo-element on `.ht-main::before` during `htmx-request`) | NOT present | **GAP** |

**GAP-MI5**: The old UI had a thin accent-colored progress bar that appeared at the top of the main content area during htmx page transitions. The CSS for it exists in the shared `global.css` (`.ht-layout.htmx-request .ht-main::before`) but since the SPA uses client-side routing, there's no htmx-request class being set. A loading indicator during page transitions would be the SPA equivalent.

### 3.6 App Filter on Global Logs

**GAP-MI6**: See GAP-L1. The global logs page needs an app filter dropdown.

---

## 4. Summary Table of All Gaps

| ID | Severity | Page | Description | Preact File |
|----|----------|------|-------------|-------------|
| GAP-D1 | Low | Dashboard | App cards missing error rate percentage | `app-card.tsx` |
| GAP-D3 | Low | Dashboard | Error feed missing handler method | `error-feed.tsx` |
| GAP-D4 | Low | Dashboard | Error feed badge shows kind instead of error_type | `error-feed.tsx` |
| GAP-D5 | Trivial | Dashboard | Empty error state shorter text | `error-feed.tsx` |
| GAP-D6 | Medium | Dashboard | Session info bar missing entirely | `dashboard.tsx` (new component) |
| GAP-A2 | Trivial | Apps List | Filter tab label formatting (casing, parens) | `status-filter.tsx` |
| GAP-A3 | Low | Apps List | Missing "App Key" column | `manifest-row.tsx` |
| GAP-A4 | Medium | Apps List | Missing "Error" column | `manifest-row.tsx` |
| GAP-A5 | High | Apps List | Multi-instance expand/collapse rows missing | `manifest-list.tsx`, `manifest-row.tsx` |
| GAP-A6 | Trivial | Apps List | Table not wrapped in ht-card | `apps.tsx` |
| GAP-AD1 | Trivial | App Detail | Reload button uses ghost vs info style | `action-buttons.tsx` |
| GAP-AD2 | Medium | App Detail | Instance metadata line broken (shows class instead of PID) | `app-detail.tsx` |
| GAP-AD3 | High | App Detail | Instance switcher dropdown missing | `app-detail.tsx` (new component) |
| GAP-AD4 | High | App Detail | Error display / traceback missing for failed apps | `app-detail.tsx` (new section) |
| GAP-AD5 | Low | App Detail | "Job Avg" card replaced with "Last Activity" | `health-strip.tsx` |
| GAP-AD6 | Trivial | App Detail | Status value not capitalized | `health-strip.tsx` |
| GAP-AD7 | Low | App Detail | Handler subtitle missing event topic | `handler-row.tsx` |
| GAP-AD8 | Medium | App Detail | Invocation table missing error tracebacks | `handler-invocations.tsx` |
| GAP-AD9 | Trivial | App Detail | Invocation table column order differs | `handler-invocations.tsx` |
| GAP-AD10 | Low | App Detail | Job subtitle missing trigger_value | `job-row.tsx` |
| GAP-AD11 | Low | App/Logs | Only Time column sortable (was all 4) | `log-table.tsx` |
| GAP-AD12 | Low | App/Logs | Log table missing sticky header | `log-table.tsx` |
| GAP-L1 | Medium | Logs | Missing per-app filter dropdown | `log-table.tsx` |
| GAP-L2 | Trivial | Logs | Log table not wrapped in ht-card | `logs.tsx` |
| GAP-L3 | Low | Logs | Level filter missing "All Levels" option | `log-table.tsx` |
| GAP-L4 | Low | Logs | App column not linked to app detail | `log-table.tsx` |
| GAP-S1 | Medium | Sidebar | Logo image missing (shows pulse dot) | `sidebar.tsx` |
| GAP-C1 | Medium | Layout | AlertBanner not wired into render tree | `app.tsx` |
| GAP-MI1 | High | Cross-cutting | Multi-instance support missing entirely | Multiple files |
| GAP-MI5 | Low | Layout | No page transition loading indicator | `app.tsx` or new component |

---

## 5. Design/Style Differences (Not Bugs)

These are intentional or acceptable differences between the old and new UI that do not need to be "fixed" but should be acknowledged:

1. **Relative vs absolute timestamps**: New UI uses "2m ago" style throughout; old used absolute times in some places. This is arguably an improvement.
2. **Client-side vs server-side filtering**: Apps list and logs now filter client-side. Better UX.
3. **WebSocket-only updates vs polling**: Old UI polled with htmx intervals; new UI relies entirely on WebSocket. Better architecture.
4. **SPA routing**: Links use `/apps/` instead of `/ui/apps/`. Expected for SPA.
5. **CSS chevron vs SVG chevron**: Handler/job row expand indicators use CSS borders instead of SVG. Fine.
6. **"Last invoked/executed" timestamps**: New UI added these to handler and job rows. Improvement.
7. **Reconnecting state**: New UI shows "Reconnecting..." during WebSocket reconnection. Improvement.

---

## 6. Priority Grouping for Implementation

### Must Fix (functional gaps)
1. **GAP-AD4** -- Error display + traceback for failed apps (users cannot see why an app failed)
2. **GAP-AD2** -- Broken instance metadata (shows wrong data)
3. **GAP-C1** -- AlertBanner not wired in (failed apps go unnoticed)
4. **GAP-A4** -- Missing Error column in manifest table

### Should Fix (feature parity)
5. **GAP-MI1/GAP-A5/GAP-AD3** -- Multi-instance support (expand rows + switcher)
6. **GAP-L1** -- App filter on global logs page
7. **GAP-S1** -- Sidebar logo
8. **GAP-D6** -- Session info bar
9. **GAP-AD8** -- Error tracebacks in invocation table

### Nice to Have (polish)
10. **GAP-D1** -- Error rate on app cards
11. **GAP-D3/D4** -- Error feed handler method and badge content
12. **GAP-AD7** -- Handler subtitle topic
13. **GAP-AD10** -- Job trigger_value in subtitle
14. **GAP-L3** -- "All Levels" option in log filter
15. **GAP-L4** -- App column links in log table
16. **GAP-AD11/AD12** -- Multi-column sort + sticky log header
17. **GAP-A2** -- Filter tab label formatting
18. **GAP-AD6** -- Capitalize status value
19. **GAP-A6/L2** -- Card wrappers
