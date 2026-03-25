---
agent: ui-auditor
status: COMPLETE
timestamp: 2026-03-25T12:37:34Z
duration: 180
findings: 18
a11y_issues: 9
consistency_issues: 4
ux_issues: 5
errors: []
skipped_checks: ["color-contrast-automated (requires running app + axe-core)", "screen-reader-live-test"]
---

# UI/UX Audit — Hassette Web Dashboard

## Summary

| Area | Issues | CRITICAL | HIGH | MEDIUM | LOW |
|------|--------|----------|------|--------|-----|
| Accessibility | 9 | 1 | 3 | 4 | 1 |
| Consistency | 4 | 0 | 0 | 4 | 0 |
| UX | 5 | 0 | 1 | 3 | 1 |
| **Total** | **18** | **1** | **4** | **11** | **2** |

**Pass/Fail: BLOCK** — 1 CRITICAL and 4 HIGH findings require resolution before shipping.

### Stack

- **Framework:** Preact SPA with Signals
- **Routing:** wouter
- **Styling:** CSS custom properties (design tokens in `tokens.css`, component styles in `global.css`)
- **State:** @preact/signals

### Positive Observations

The codebase demonstrates several accessibility-conscious patterns that are worth noting:

- Design tokens are well-structured and consistently used across nearly all CSS
- Semantic HTML is used throughout (nav, main, aside, table, thead/tbody, ul/li)
- `aria-label` is present on navigation items, status indicators, and the theme toggle
- `aria-expanded` is correctly used on expandable handler/job rows and log messages
- `aria-sort` is implemented on sortable table columns with proper ascending/descending states
- Keyboard handlers (Enter/Space) exist on `role="button"` elements in the log table and item rows
- `prefers-reduced-motion` is respected with a global media query
- The Spinner component has `role="status"` and `aria-label="Loading"`
- Breadcrumb navigation uses `aria-label="Breadcrumb"` and `aria-current="page"`
- Sort arrows are correctly marked `aria-hidden="true"`

---

## Accessibility

### A11Y-001: No focus indicators on interactive elements [CRITICAL]
**File:** `frontend/src/global.css:551-556`
**Issue:** Focus styles are explicitly removed (`outline: none`) on inputs/selects, and no `:focus-visible` styles are defined anywhere in the stylesheet. Buttons, links, nav items, sortable column headers, and expandable rows have no visible focus ring. The `.ht-sortable` class uses `all: unset` (line 1355) which strips all focus indicators. This makes the entire application unusable for keyboard-only users.
**WCAG:** 2.4.7 Focus Visible (Level AA)
**Fix:** Add a global `:focus-visible` style that provides a visible outline. For example:
```css
:focus-visible {
  outline: 2px solid var(--ht-accent);
  outline-offset: 2px;
}
```
Remove `outline: none` from `.ht-input:focus` and `.ht-select select:focus`, replacing with a custom focus ring. Add explicit `:focus-visible` styles to `.ht-sortable`, `.ht-nav-item`, `.ht-btn`, and `.ht-theme-toggle`.

---

### A11Y-002: No skip navigation link [HIGH]
**File:** `frontend/index.html:12-14`, `frontend/src/app.tsx:30-45`
**Issue:** There is no "Skip to main content" link. With keyboard navigation, users must tab through every sidebar nav item on every page load before reaching page content.
**WCAG:** 2.4.1 Bypass Blocks (Level A)
**Fix:** Add a visually-hidden skip link as the first focusable element inside `<body>` (or the App component):
```tsx
<a href="#main-content" class="ht-skip-link">Skip to main content</a>
```
Add `id="main-content"` to the `<main>` element. Style `.ht-skip-link` to be visually hidden until focused.

---

### A11Y-003: Expand/collapse chevron in manifest table is a `<span>` with onClick [HIGH]
**File:** `frontend/src/components/apps/manifest-row.tsx:22-30`
**Issue:** The expand/collapse chevron for multi-instance apps uses a `<span>` with `onClick` and inline `cursor: pointer`. It has no `role`, no `tabIndex`, no keyboard handler, and no accessible name. Keyboard users cannot operate it; screen readers will not announce it as interactive.
**WCAG:** 4.1.2 Name, Role, Value (Level A); 2.1.1 Keyboard (Level A)
**Fix:** Convert to a `<button>` element with an `aria-label` (e.g., "Expand instances for {appKey}") and `aria-expanded` state. Or use `role="button"` with `tabIndex={0}` and a keyboard handler, following the pattern already used in `handler-row.tsx`.

---

### A11Y-004: Status filter tabs use anchor elements with `href="#"` instead of button/tab pattern [HIGH]
**File:** `frontend/src/components/apps/status-filter.tsx:18-27`
**Issue:** The status filter tabs (`All`, `Running`, `Failed`, etc.) are implemented as `<a href="#">` inside `<li>` elements inside a `<nav>`. They use `e.preventDefault()` on click. This is a tab-like widget but lacks `role="tablist"`, `role="tab"`, `aria-selected`, and `aria-controls` attributes. Screen readers announce these as links, not tabs.
**WCAG:** 4.1.2 Name, Role, Value (Level A)
**Fix:** Implement the ARIA Tabs pattern:
- `<nav>` or containing `<div>`: `role="tablist"`
- Each tab: `<button role="tab" aria-selected={isActive}>` (remove `<a href="#">`)
- Or keep as navigation links but remove the tab-like visual treatment

---

### A11Y-005: Form controls missing accessible labels [MEDIUM]
**File:** `frontend/src/components/shared/log-table.tsx:149-194`
**Issue:** The log level `<select>` (line 152), app filter `<select>` (line 170), and search `<input>` (line 186) have no associated `<label>` elements, no `aria-label`, and no `aria-labelledby`. The select elements use their first `<option>` as a pseudo-label ("All Levels", "All Apps"), but this is not a proper accessible name. The search input uses `placeholder="Search..."` which is not an accessible label.
**WCAG:** 1.3.1 Info and Relationships (Level A); 4.1.2 Name, Role, Value (Level A)
**Fix:** Add `aria-label` attributes: `aria-label="Minimum log level"`, `aria-label="Filter by app"`, `aria-label="Search log messages"`.

---

### A11Y-006: Instance switcher `<select>` not associated with its label [MEDIUM]
**File:** `frontend/src/pages/app-detail.tsx:79-93`
**Issue:** The instance switcher has a `<label>` element (line 79) but it is not connected to the `<select>` via `htmlFor`/`id`. The label reads "Instance" but clicking it will not focus the select.
**WCAG:** 1.3.1 Info and Relationships (Level A)
**Fix:** Add `id="instance-select"` to the `<select>` and `htmlFor="instance-select"` (or `for` in Preact) to the `<label>`.

---

### A11Y-007: SVG icons lack accessible text when used as standalone indicators [MEDIUM]
**File:** `frontend/src/components/shared/icons.tsx` (all icon components)
**Issue:** All SVG icon components render without `aria-hidden="true"` or meaningful `<title>` elements. When icons appear next to text (e.g., headings), they should be `aria-hidden="true"` to avoid screen reader noise. When icons appear alone (e.g., status dots), they need accessible names.
**WCAG:** 1.1.1 Non-text Content (Level A)
**Fix:** Add `aria-hidden="true"` to all decorative icon SVGs (those accompanying visible text). For icons used as the sole content of a button (already handled by `aria-label` on the button), `aria-hidden="true"` on the SVG is still best practice to prevent double announcement.

---

### A11Y-008: Log message expand/collapse `role="button"` on `<td>` lacks accessible name [MEDIUM]
**File:** `frontend/src/components/shared/log-table.tsx:266-284`
**Issue:** The log message cell uses `role="button"` with `tabIndex={0}` and `aria-expanded`, which is good. However, there is no `aria-label` describing the action. Screen readers will announce the entire message text as the button name, which can be very long.
**WCAG:** 2.4.6 Headings and Labels (Level AA)
**Fix:** Add `aria-label="Toggle message expansion"` or similar short label to the `<td>` element.

---

### A11Y-009: Health bar has no text alternative [LOW]
**File:** `frontend/src/components/shared/health-bar.tsx:13-19`
**Issue:** The health bar is a visual-only progress indicator (colored bar fill at X%) with no text or ARIA attributes. Screen readers get no information about the health status.
**WCAG:** 1.1.1 Non-text Content (Level A)
**Fix:** Add `role="progressbar"`, `aria-valuenow={successRate}`, `aria-valuemin={0}`, `aria-valuemax={100}`, and `aria-label="Health: {successRate}% success rate"`.

---

## Consistency

### CON-001: Inline styles scattered across components
**Files:** `frontend/src/components/apps/manifest-row.tsx:24,45,61`, `frontend/src/components/dashboard/error-feed.tsx:50`, `frontend/src/components/shared/log-table.tsx:205,207,209,214,220,226,237`, `frontend/src/components/layout/error-boundary.tsx:18`, `frontend/src/pages/not-found.tsx:3`, `frontend/src/components/layout/sidebar.tsx:32`
**Issue:** 17 inline `style=` attributes across 8 components. Many use hardcoded pixel values (`marginRight: "4px"`, `paddingLeft: "2rem"`, `maxHeight: "600px"`, `width: "90px"`) or layout properties that should be in CSS classes. The `error-feed.tsx` tag even uses a raw string-style attribute: `style="max-width:140px;overflow:hidden;..."`.
**Fix:** Extract these into CSS classes in `global.css`. For the log table column widths, consider a `.ht-table-log th` width rule. For the error tag truncation, create `.ht-tag--truncate`. Replace `marginRight: "4px"` with the existing `ht-mr-2` or a new spacing utility.

---

### CON-002: Inconsistent spacing values — mix of token-based and hardcoded
**Files:** `frontend/src/global.css:382-383` (`0.3em 0.5em`), `frontend/src/global.css:392-393` (`0.25em 0.5em`), `frontend/src/global.css:402` (`0.25em`), various button padding values
**Issue:** While the design token system defines `--ht-sp-*` on a 4px grid, many component styles use `em`-based padding values (`0.35em`, `0.4em 0.85em`, `0.15em 0.55em`). This creates two competing spacing systems. The `em` values are reasonable for text-relative sizing but inconsistent with the explicit spacing tokens.
**Fix:** Decide on a convention: use `--ht-sp-*` tokens for structural spacing and allow `em` for text-adjacent padding within badges/buttons. Document this convention in `tokens.css` comments.

---

### CON-003: `ht-text-warning` utility class used but never defined
**File:** `frontend/src/components/shared/log-table.tsx:197`
**Issue:** The live-paused indicator uses `class="ht-text-xs ht-text-warning"`, but `ht-text-warning` is not defined in `global.css`. The defined utility classes are `ht-text-danger`, `ht-text-success`, `ht-text-muted`, and `ht-text-faint`. This means the warning text has no color styling.
**Fix:** Add `.ht-text-warning { color: var(--ht-warning); }` to the utility section of `global.css`, alongside the existing `ht-text-danger` and `ht-text-success` classes.

---

### CON-004: Tag component lacks a neutral/fallback variant
**File:** `frontend/src/components/dashboard/error-feed.tsx:16-18,49`
**Issue:** The `kindClass()` function falls back to `"neutral"` for unknown error kinds, but `.ht-tag--neutral` is not defined in `global.css`. Only `.ht-tag--handler` and `.ht-tag--job` exist. Tags with unknown kinds get no background or color styling.
**Fix:** Add `.ht-tag--neutral` to `global.css`:
```css
.ht-tag--neutral {
  color: var(--ht-text-secondary);
  background: var(--ht-surface-recessed);
}
```

---

## UX

### UX-001: No navigation on mobile when sidebar is hidden [HIGH]
**File:** `frontend/src/global.css:1027-1034`
**Issue:** Below 768px, the sidebar is set to `display: none` with no replacement. There is no hamburger menu, bottom navigation bar, or any other mechanism to navigate between Dashboard, Apps, and Logs pages on mobile. Users on tablets or phones are stranded on whichever page they loaded.
**WCAG:** Not a WCAG issue, but a fundamental usability failure.
**Fix:** Either:
1. Add a mobile bottom navigation bar (`position: fixed; bottom: 0`) with the same three nav items, or
2. Add a hamburger menu toggle that shows/hides the sidebar as an overlay on mobile, or
3. Convert the sidebar to a horizontal top nav bar on small screens.

---

### UX-002: No confirmation on destructive app actions (Stop) [MEDIUM]
**File:** `frontend/src/components/apps/action-buttons.tsx:50-60`
**Issue:** The Stop button immediately calls `stopApp()` on click with no confirmation dialog. Stopping an app halts all of its automations, which could affect home automation routines (lights, climate, security). There is no undo mechanism.
**Fix:** Add a confirmation step before stopping. Options:
- A browser `confirm()` dialog (minimal effort)
- An inline "Are you sure?" state with confirm/cancel buttons (better UX)
- A toast with an "Undo" action and delayed execution (best UX)

---

### UX-003: Empty states lack guidance on app-detail page [MEDIUM]
**File:** `frontend/src/pages/app-detail.tsx:112-129`
**Issue:** When an app has zero event handlers or zero scheduled jobs, the sections render with headings ("Event Handlers (0 registered)", "Scheduled Jobs (0 active)") but no content below them. There is no empty state message explaining what handlers/jobs are or how they get registered.
**Fix:** Add empty state messages when `listenerCount === 0` and `jobCount === 0`:
```tsx
{listenerCount === 0 && (
  <p class="ht-text-muted ht-text-sm">
    No event handlers registered. Handlers are created in your app's on_initialize() method.
  </p>
)}
```

---

### UX-004: Log table search has no debounce [MEDIUM]
**File:** `frontend/src/components/shared/log-table.tsx:186-194`
**Issue:** The search input filters on every keystroke via `onInput`. With 500 log entries rendered, each keystroke triggers a full re-filter and re-render of the sorted list. There is no debounce on the search input, unlike the dashboard which debounces API calls.
**Fix:** Use the existing `useDebouncedEffect` hook or add a local debounce to the search signal update. A 150-200ms debounce would prevent janky typing on slower devices.

---

### UX-005: Page title does not update on navigation [LOW]
**File:** `frontend/src/app.tsx`, `frontend/index.html:6`
**Issue:** The `<title>` is always "Hassette" regardless of which page the user is on. This makes it impossible to distinguish tabs in the browser and provides no context for screen reader users or browser history.
**Fix:** Update `document.title` in the App component based on the current route. For example: "Dashboard - Hassette", "Apps - Hassette", "my_app - Hassette", "Logs - Hassette".

---

## Out of Scope

The following items were noted but not audited:
- **Color contrast ratios**: Requires rendering the actual UI to measure computed contrast. The token values look reasonable (e.g., `#ececef` on `#111113` for dark mode text) but automated testing with axe-core or Lighthouse is needed.
- **Backend-served CSS**: `src/hassette/web/static/css/tokens.css` is a legacy copy of the frontend tokens. Not audited as the Preact SPA has its own copy.
- **Third-party widgets**: None detected.
