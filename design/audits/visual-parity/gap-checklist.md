# Visual Parity Gap Checklist

Generated 2026-03-21 from comparison agent + adversarial verifier.
Sources: `comparison.md` + `verifier-findings.md`

---

## GAPs (Must Fix)

### GAP-001: Session info bar missing from dashboard
- **Scenario:** D1, D4, D5
- **Old UI:** Footer bar showing "Hassette v0.23.0 Started 3/21/2026, 9:07:12 AM"
- **New UI:** Missing entirely
- **File to fix:** `frontend/src/pages/dashboard.tsx` (new component needed)
- **Old template:** `pages/dashboard.html` (ht-session-bar div)
- **Status:** [ ] Open

### GAP-002: APP KEY column removed from apps table
- **Scenario:** A1, A6
- **Old UI:** First column shows app_key as linked `<code>` element (e.g., `office_button_app`)
- **New UI:** Column removed — only display_name shown
- **File to fix:** `frontend/src/components/apps/manifest-row.tsx`
- **Old template:** `partials/manifest_list.html`
- **Status:** [ ] Open

### GAP-003: ERROR column removed from apps table
- **Scenario:** A1, A6
- **Old UI:** Error column shows error_message in red for failed apps, "—" for healthy
- **New UI:** Column removed
- **File to fix:** `frontend/src/components/apps/manifest-row.tsx`
- **Old template:** `partials/manifest_list.html`
- **Status:** [ ] Open

### GAP-004: Multi-instance app expand/collapse missing
- **Scenario:** A4
- **Old UI:** Multi-instance apps have a chevron toggle; expanding shows indented instance sub-rows with per-instance name, status, error, and actions
- **New UI:** Shows instance count in a column but no expand mechanism, no sub-rows
- **File to fix:** `frontend/src/components/apps/manifest-list.tsx`, `manifest-row.tsx`
- **Old template:** `partials/manifest_list.html` (instance rows section)
- **Status:** [ ] Open

### GAP-005: App filter dropdown missing from logs page
- **Scenario:** L1
- **Old UI:** Dropdown with "All Apps" + each app_key to filter logs by app
- **New UI:** Only level filter and search — no app dropdown
- **File to fix:** `frontend/src/components/shared/log-table.tsx`
- **Old template:** `macros/ui.html` (log_table macro, app_keys select)
- **Status:** [ ] Open

### GAP-006: "All Levels" option missing from log level filter
- **Scenario:** L1
- **Old UI:** Level dropdown starts with "All Levels" (shows everything including DEBUG)
- **New UI:** Starts at "INFO" — no "All" option, DEBUG hidden by default
- **File to fix:** `frontend/src/components/shared/log-table.tsx`
- **Old template:** `macros/ui.html` (log_table macro, level select)
- **Status:** [ ] Open

### GAP-007: Log table app column not linked
- **Scenario:** L7
- **Old UI:** App names in the App column are links to `/ui/apps/{key}`
- **New UI:** Plain text, not linked
- **File to fix:** `frontend/src/components/shared/log-table.tsx`
- **Old template:** `macros/ui.html` (log_table macro, app column `<a>` tag)
- **Status:** [ ] Open

### GAP-008: Sidebar brand logo replaced with pulse dot
- **Scenario:** X1
- **Old UI:** Hassette logo image (24px height) with teal background block
- **New UI:** Small green pulsing dot only — no logo
- **File to fix:** `frontend/src/components/layout/sidebar.tsx`
- **Old template:** `components/nav.html` (img tag in ht-sidebar-brand)
- **Status:** [ ] Open

### GAP-009: "Job Avg" KPI card replaced with "Last Activity"
- **Scenario:** AD3
- **Old UI:** Health strip has 4 cards: Status, Error Rate, Handler Avg, Job Avg
- **New UI:** Status, Error Rate, Avg Duration, Last Activity — "Job Avg" duration data replaced with relative timestamp
- **File to fix:** `frontend/src/components/app-detail/health-strip.tsx`
- **Old template:** `partials/app_health_strip.html`
- **Status:** [ ] Open

### GAP-010: Status value not capitalized in health strip
- **Scenario:** AD3, AD14
- **Old UI:** "Running" (title case)
- **New UI:** "running" (lowercase)
- **File to fix:** `frontend/src/components/app-detail/health-strip.tsx`
- **Old template:** `partials/app_health_strip.html` (uses |capitalize filter)
- **Status:** [ ] Open

### GAP-011: Recent Errors empty state text shortened
- **Scenario:** D1
- **Old UI:** "No recent errors. All systems healthy."
- **New UI:** "No recent errors."
- **File to fix:** `frontend/src/components/dashboard/error-feed.tsx`
- **Old template:** `partials/dashboard_errors.html`
- **Status:** [ ] Open

### GAP-012: Handler row subtitle missing topic
- **Scenario:** AD5
- **Old UI:** Subtitle shows "handler_method · topic"
- **New UI:** Subtitle shows handler_method only
- **File to fix:** `frontend/src/components/app-detail/handler-row.tsx`
- **Old template:** `macros/ui.html` (handler_row macro, subtitle span)
- **Status:** [ ] Open

### GAP-013: Job row subtitle missing trigger_value
- **Scenario:** AD8
- **Old UI:** Subtitle shows "trigger_type: trigger_value" (e.g., "cron: 0 0 * * * 0")
- **New UI:** Shows trigger_type only (e.g., "cron") — missing the cron expression
- **File to fix:** `frontend/src/components/app-detail/job-row.tsx`
- **Old template:** `macros/ui.html` (job_row macro, subtitle span)
- **Status:** [ ] Open

### GAP-014: Instance switcher dropdown missing on multi-instance app detail
- **Scenario:** AD15
- **Old UI:** Select dropdown with instance names and statuses for switching between instances
- **New UI:** Shows "Instance 0" only, no switcher
- **File to fix:** `frontend/src/pages/app-detail.tsx` (new component needed)
- **Old template:** `pages/app_detail.html` (is_multi_instance select)
- **Status:** [ ] Open

### GAP-015: AlertBanner not wired into render tree
- **Scenario:** X3 (skipped — no failed apps), but confirmed by code reading
- **Old UI:** Alert banner shows between status bar and page content when apps fail
- **New UI:** Component exists (`alert-banner.tsx`) but is NOT rendered in `app.tsx`
- **File to fix:** `frontend/src/app.tsx`
- **Old template:** `base.html` (alert_banner.html include)
- **Status:** [ ] Open

### GAP-016: Error display card missing on failed app detail
- **Scenario:** AD11 (skipped — no failed apps), but confirmed by template reading
- **Old UI:** Red error card with message + "Show traceback" expand button
- **New UI:** No error display at all
- **File to fix:** `frontend/src/pages/app-detail.tsx` (new section)
- **Old template:** `pages/app_detail.html` (error-display card)
- **Status:** [ ] Open

### GAP-017: Log table column order changed
- **Scenario:** L1, AD10
- **Old UI:** Columns: LEVEL, TIMESTAMP, APP, MESSAGE
- **New UI:** Columns: TIME, LEVEL, APP/MESSAGE (with TIME first)
- **File to fix:** `frontend/src/components/shared/log-table.tsx`
- **Old template:** `macros/ui.html` (log_table macro)
- **Status:** [ ] Open

### GAP-018: Apps list table not wrapped in card
- **Scenario:** A1
- **Old UI:** Filter tabs + table wrapped in `ht-card`
- **New UI:** No card wrapper
- **File to fix:** `frontend/src/pages/apps.tsx`
- **Old template:** `pages/apps.html`
- **Status:** [ ] Open

### GAP-019: Tab labels not title-cased with parentheses
- **Scenario:** A1
- **Old UI:** "All (7)", "Running (6)", "Failed (0)", "Stopped (0)", "Disabled (1)"
- **New UI:** "all 7", "running 6", "failed 0", etc. (lowercase, no parens)
- **File to fix:** `frontend/src/components/apps/status-filter.tsx`
- **Old template:** `pages/apps.html` (filter tabs)
- **Status:** [ ] Open

### GAP-020: Logs page not wrapped in card
- **Scenario:** L1
- **Old UI:** Log viewer wrapped in `ht-card`
- **New UI:** No card wrapper
- **File to fix:** `frontend/src/pages/logs.tsx`
- **Old template:** `pages/logs.html`
- **Status:** [ ] Open

---

## DIFFERENT (Intentional — Do Not Fix)

- Relative timestamps ("3m ago") vs absolute ("9:07:14 AM") on dashboard cards
- Sidebar icon style (outline vs filled)
- "Manage Apps" as button-styled link vs plain text link
- Invocation/execution table column order (TIME first in new)
- Handler invocation row styling differences (cards vs table rows)
- Default log level INFO vs "All Levels"  — **actually classified as GAP-006 above**
- Overall spacing more generous in new UI

## IMPROVEMENT (New UI Better)

- "Reconnecting..." WebSocket state (old only had Connected/Disconnected)
- Styled 404 page (old was raw JSON for non-/ui/ paths)
- "blocked" filter tab in apps list
- INSTANCES column in apps table
- Last invoked/executed timestamps on handler/job rows
- Error row highlighting in log table (color-coded backgrounds)
