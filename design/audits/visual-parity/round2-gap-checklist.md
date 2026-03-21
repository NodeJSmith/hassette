# Round 2 Visual Parity Gap Checklist

Generated 2026-03-21 from R2 comparison agent + R2 adversarial verifier.

---

## GAPs (Must Fix)

### R2-001: Invocation table column order wrong
- **Old:** STATUS, TIMESTAMP, DURATION, ERROR
- **New:** TIME, DURATION, STATUS, ERROR
- **File:** `frontend/src/components/app-detail/handler-invocations.tsx`
- **Status:** [ ] Open

### R2-002: Execution table column order wrong
- **Old:** STATUS, TIMESTAMP, DURATION, ERROR
- **New:** TIME, DURATION, STATUS, ERROR (also missing GPS column — likely "ERROR" renamed)
- **File:** `frontend/src/components/app-detail/job-executions.tsx`
- **Status:** [ ] Open

### R2-003: Timestamp format missing date
- **Old:** "03/21 09:08:24 AM" (date + time)
- **New:** "8:43:24 AM" (time only)
- **File:** `frontend/src/utils/format.ts` (`formatTimestamp`)
- **Status:** [ ] Open

### R2-004: Duration missing decimal precision
- **Old:** "158.0ms" (one decimal from Jinja `"%.1f"|format`)
- **New:** "158ms" (integer)
- **File:** `frontend/src/utils/format.ts` (`formatDuration`)
- **Status:** [ ] Open

### R2-005: Empty state text "No handlers registered" vs "No event handlers registered"
- **Old:** "No event handlers registered."
- **New:** "No handlers registered."
- **File:** `frontend/src/components/app-detail/handler-list.tsx`
- **Status:** [ ] Open

### R2-006: Disabled app logs section missing "No log entries." message
- **Old:** Shows "No log entries." centered in the table
- **New:** Empty table with column headers but no message
- **File:** `frontend/src/components/shared/log-table.tsx`
- **Status:** [ ] Open

### R2-007: Disabled status badge missing dot indicator
- **Old:** Grey dot + "disabled" text
- **New:** "disabled" text without dot
- **File:** `frontend/src/components/shared/status-badge.tsx` (small variant for disabled)
- **Status:** [ ] Open

### R2-008: Expand chevrons are INVISIBLE (HIGH from verifier)
- **Old:** SVG right-pointing triangle on handler/job rows
- **New:** Empty `<span class="ht-item-row__chevron"/>` with no content
- **File:** `frontend/src/components/app-detail/handler-row.tsx`, `job-row.tsx` + CSS
- **Status:** [ ] Open

### R2-009: Tab bar uses nonexistent CSS classes (HIGH from verifier)
- **Old:** `ht-tabs` with `<ul><li><a>` — clean underlined text tabs
- **New:** `ht-tab-bar` / `ht-tab` classes don't exist — browser-default button styling
- **File:** `frontend/src/components/apps/status-filter.tsx` + `global.css`
- **Status:** [ ] Open

### R2-010: Expanded detail panel wrong CSS class (HIGH from verifier)
- **Old:** `ht-item-detail` with recessed background, padding, border-top
- **New:** `ht-item-row__detail` — class doesn't exist, no styling
- **File:** `frontend/src/components/app-detail/handler-row.tsx`, `job-row.tsx` + CSS
- **Status:** [ ] Open

### R2-011: 15 missing CSS classes used in components
- **Impact:** Tab bar unstyled, log filters unstyled, instance rows unstyled, sortable headers unstyled
- **Classes:** ht-tab-bar, ht-tab, ht-item-row__detail, ht-table-compact, ht-table-log, ht-log-table-container, ht-log-filters, ht-log-row, ht-log-message, ht-select-sm (should be ht-select--sm), ht-input-sm (should be ht-input--sm), ht-sortable, ht-instance-row, ht-chevron-inline, ht-status-text--*
- **File:** `frontend/src/global.css` — need to add definitions or fix class names to match existing CSS
- **Status:** [ ] Open

### R2-012: Reload button ghost style instead of info style
- **Old:** `ht-btn--info` (visible blue border)
- **New:** `ht-btn--ghost` (no border, transparent)
- **File:** `frontend/src/components/apps/action-buttons.tsx`
- **Status:** [ ] Open

### R2-013: Error log rows have full-row red background
- **Old:** Only the ERROR badge is colored, row background is normal
- **New:** Entire row has pink/red background, badge text potentially unreadable
- **File:** `frontend/src/global.css` (`.ht-log-error` rule) or `log-table.tsx`
- **Status:** [ ] Open

---

## DIFFERENT (Intentional — Do Not Fix)

- Tab style: pill buttons vs underlined text (design choice)
- "Blocked" tab present in new (improvement)
- Apps page heading icon (grid vs gear)
- Handler summary count format differences (data, not style)

## IMPROVEMENT

- Proper styled 404 page vs raw JSON
- "Reconnecting..." state
- Instance metadata visible on disabled apps
