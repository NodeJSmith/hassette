---
task_id: "T03"
title: "Migrate shared components to use Button, Badge, Chip, Card"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#12", "FR#13"]
---

## Summary
Migrate the existing shared components (`action-buttons.tsx`, `show-more-button.tsx`, `confirm-dialog.tsx`, `table-card.tsx`, `error-boundary.tsx`) to use the new Button and Card components instead of raw `ht-*` class strings. This task also adds `data-role="action-buttons"` to ActionButtons and updates `apps.module.css` to target the data attribute. Update the two test files that query by CSS class to use `data-testid`.

## Prompt
Migrate the following shared components. Each migration replaces raw `ht-*` class strings with the corresponding component import and props.

### action-buttons.tsx
1. Import `Button` from `./button`.
2. Replace the three `<button class={...}>` elements with `<Button>` using appropriate props:
   - Start button: `<Button variant="success" size={isIcon ? undefined : "sm"} ghost={isIcon} icon={isIcon} ...>`
   - Reload button: `<Button variant={isIcon ? "info" : undefined} size={isIcon ? undefined : "sm"} ghost={isIcon} icon={isIcon} ...>`
   - Stop button: `<Button variant={isIcon ? "warning" : "danger"} size={isIcon ? undefined : "sm"} ghost={isIcon} icon={isIcon} ...>`
3. Replace `class="ht-btn-group"` with a module CSS class. Add `action-buttons.module.css` if it doesn't exist (it doesn't currently). Move `.ht-btn-group` styles from `styles/buttons.css` (the flex container: `display: flex; gap: var(--sp-2); flex-wrap: wrap;`) into a `.btnGroup` class. Add `data-role="action-buttons"` to the wrapper div.
4. Update `frontend/src/pages/apps.module.css`: replace `:global(.ht-btn-group)` on lines 168 and 174 with `[data-role="action-buttons"]`.

### show-more-button.tsx
1. Import `Button` from `./button`.
2. Replace `<button ... class={clsx("ht-btn ht-btn--xs ht-btn--ghost", styles.showMore)}>` with `<Button variant="ghost" size="xs" class={styles.showMore}>`.

### confirm-dialog.tsx
1. Import `Button` from `./button`.
2. Replace cancel button: `<button type="button" ref={cancelRef} class="ht-btn">Cancel</button>` → `<Button ref={(el) => { cancelRef.current = el; }}>Cancel</Button>`. Note: Button accepts a callback ref; confirm-dialog uses `useRef`, so bridge with a callback.
3. Replace confirm button: `<button ... class={clsx("ht-btn", tone === "danger" ? "ht-btn--danger" : "ht-btn--primary")}>` → `<Button variant={tone === "danger" ? "danger" : "primary"} data-testid={...}>`.

### table-card.tsx
1. Import `Card` from `./card`.
2. Replace `<div class={...} ref={ref}>` with `<Card variant="compact" class={className} containerRef={ref}>`.
3. The internal `ht-table-toolbar`, `ht-table-toolbar__*`, and `ht-table-card-scroll` classes remain as global classes (tables are non-goals).

### error-boundary.tsx
1. Import `Button` from `./button` and `Card` from `./card`.
2. Replace `<div class="ht-card ht-error-card">` with `<Card variant="error" data-testid="error-card">`.
3. Replace `<button type="button" class="ht-btn ht-btn--primary">` with `<Button variant="primary">`.

### Test updates
1. `frontend/src/components/layout/error-boundary.test.tsx`: Replace `container.querySelector(".ht-error-card")` with `getByTestId("error-card")` or `container.querySelector("[data-testid='error-card']")`. The `data-testid` was added to Card in the error-boundary migration above.

Note: `job-executions.test.tsx` badge selector updates are handled in T04 alongside the `data-testid` addition to `job-executions.tsx`.

## Focus
- `frontend/src/components/shared/action-buttons.tsx:49,52,55,67,79` — all `ht-btn` usages; no existing `.module.css` file, must create one
- `frontend/src/components/shared/show-more-button.tsx:14` — single `clsx("ht-btn ht-btn--xs ht-btn--ghost", styles.showMore)`
- `frontend/src/components/shared/confirm-dialog.tsx:104,112` — two buttons with refs
- `frontend/src/components/shared/table-card.tsx:18` — single `ht-card ht-card--compact` usage
- `frontend/src/components/layout/error-boundary.tsx:25,30` — Card + Button usage
- `frontend/src/pages/apps.module.css:168,174` — `:global(.ht-btn-group)` → `[data-role="action-buttons"]`
- `frontend/src/pages/apps.module.css:199` — `:global(.ht-chip--auto)` → `[data-variant="muted"]` (done in T04 when apps.tsx is migrated)
- Confirm-dialog's `cancelRef` and `confirmRef` are `useRef<HTMLButtonElement>` — bridge to callback ref pattern
- The `action-buttons.test.tsx` exists and must continue to pass

## Verify
- [ ] FR#12: `TableCard` internally renders `<Card variant="compact">` instead of raw `ht-card` classes
- [ ] FR#13: All five shared components and error-boundary use Button/Card components instead of raw class strings
