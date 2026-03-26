# WP02: Component ARIA + keyboard fixes

**Lane:** todo
**Depends on:** WP01 (focus styles must exist before components rely on them)

## Objective

Fix ARIA semantics and keyboard access on 6 components. Each fix is isolated.

## Tasks

### 1. manifest-row.tsx — chevron `<span>` → `<button>`

- Convert the expand/collapse `<span class="ht-item-row__chevron-inline">` to `<button>`
- Add `aria-label={isExpanded ? "Collapse instances for {manifest.app_key}" : "Expand instances for {manifest.app_key}"}`
- Add `aria-expanded={isExpanded}`
- Remove inline `style={{ cursor: "pointer", marginRight: "4px" }}` (cursor comes from button; margin moves to CSS in WP03)
- Add button resets to `.ht-item-row__chevron-inline`: `padding: 0; border: none; background: transparent; font: inherit;`

### 2. status-filter.tsx — `<a href="#">` → `<button aria-pressed>`

- Change `<nav class="ht-tabs">` to `<div class="ht-tabs" role="group" aria-label="App status filter">` — `<nav>` is for navigation landmarks, not filter toggle groups
- Replace each `<a href="#" onClick={...}>` with `<button type="button" aria-pressed={active.value === f} onClick={() => { active.value = f; }}>`
- Remove `e.preventDefault()` (no longer needed)
- Remove the `is-active` class from the `<li>` — `aria-pressed` on the button is now the state signal
- Keep `data-testid={`tab-${f}`}` on the `<li>`
- Update ALL THREE CSS selectors in `global.css:595-616`:
  - `.ht-tabs li a` → `.ht-tabs li button`
  - `.ht-tabs li a:hover` → `.ht-tabs li button:hover`
  - `.ht-tabs li.is-active a` → `.ht-tabs li button[aria-pressed="true"]`
- Remove the now-dead `.ht-tabs li.is-active` rule if one exists

### 3. log-table.tsx — expand button alongside message text

- Remove `role="button"`, `tabIndex={0}`, `onKeyDown` from the message `<td>`
- Keep `onClick` on `<td>` for click-anywhere pointer affordance (toggle expand/collapse)
- Add a small expand button *alongside* (not wrapping) the message text:
  ```tsx
  <td class="ht-log-message" onClick={toggle}>
    <button
      type="button"
      class="ht-log-expand-btn"
      aria-label={expandedRows.value.has(rowKey) ? "Collapse log message" : "Expand log message"}
      aria-expanded={expandedRows.value.has(rowKey)}
      onClick={(e) => { e.stopPropagation(); toggle(); }}
    />
    <div class={`ht-log-message__text${expanded ? " is-expanded" : ""}`}>{entry.message}</div>
  </td>
  ```
- The button is a small expand chevron/icon — message text remains a separate readable element for AT users
- Style `.ht-log-expand-btn` as a minimal inline button (no border/background, small chevron icon or ▸/▾ text)
- Add `aria-label="Minimum log level"` to level select
- Add `aria-label="Filter by app"` to app filter select (if present)
- Add `aria-label="Search log messages"` to search input

### 4. app-detail.tsx — label-select association

- Add `id="instance-select"` to the `<select>`
- Add `htmlFor="instance-select"` to the `<label>`

### 5. icons.tsx — `aria-hidden="true"`

- Add `aria-hidden="true"` to every `<svg>` element in the file
- All icons are decorative (accompanying visible text or inside labeled buttons)

### 6. health-bar.tsx — progressbar role

- When `total > 0`:
  ```tsx
  <div class="ht-health-bar" role="progressbar"
       aria-valuenow={Math.round(successRate)}
       aria-valuemin={0} aria-valuemax={100}
       aria-label={`Health: ${Math.round(successRate)}% success rate`}>
  ```
- When `total === 0`: add `aria-hidden="true"` to the outer `<div>` AND force fill class to `ht-health-bar__fill--neutral` (gray) — prevents misleading full-green bar for zero-activity apps

## Files

- `frontend/src/components/apps/manifest-row.tsx`
- `frontend/src/components/apps/status-filter.tsx`
- `frontend/src/components/shared/log-table.tsx`
- `frontend/src/pages/app-detail.tsx`
- `frontend/src/components/shared/icons.tsx`
- `frontend/src/components/shared/health-bar.tsx`
- `frontend/src/global.css` (tab style selector update, log expand button style)
- `frontend/src/components/shared/log-table.test.tsx` (update `[role='button'][aria-expanded]` → `button[aria-expanded]` or `button.ht-log-expand-btn`)
- `tests/e2e/test_apps_list.py` (update `[data-testid='tab-...'] a` → `[data-testid='tab-...'] button` at lines 25, 41, 47)
- `tests/e2e/test_apps.py` (update `[data-testid='tab-running'] a` → `[data-testid='tab-running'] button` at line 23)

## Verification

- Tab through each modified component — all interactive elements reachable and operable
- Screen reader pass: verify status-filter announces "Running, pressed" / "All, not pressed"
- Verify log message expand button announces "Expand log message" not the full message text
- Verify health bar announced as "Health: 87% success rate" (or hidden when no data)
- Run unit tests — `log-table.test.tsx` must pass with updated selectors
- Run existing E2E tests — must pass after selector updates
