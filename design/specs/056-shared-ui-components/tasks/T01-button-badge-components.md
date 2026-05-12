---
task_id: "T01"
title: "Create Button and Badge components with module CSS"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#15"]
---

## Summary
Create the Button and Badge reusable components in `frontend/src/components/shared/`, each with co-located `.module.css` files that absorb the styles from their respective `styles/*.css` files. Button provides a structural `type="button"` guarantee and prop-driven variants/sizes. Badge provides variant and size props with type-level coupling to `StatusVariant`. Dead badge CSS variants (`--group`, `--cancelled`) are dropped during CSS absorption. Unit tests for both components.

## Prompt
Create two new components in `frontend/src/components/shared/`:

### Button (`button.tsx` + `button.module.css`)

1. Read `frontend/src/styles/buttons.css` for the full CSS to absorb. Convert all `.ht-btn*` selectors to module-scoped class names (e.g., `.btn`, `.sm`, `.xs`, `.icon`, `.ghost`, `.primary`, `.success`, `.warning`, `.info`, `.danger`, `.btnGroup`). Include the `@media (max-width: 900px)` responsive touch-target rule.

2. Component props interface:
   - `variant`: `"default" | "primary" | "success" | "warning" | "info" | "danger"` (default: `"default"`)
   - `size`: `"default" | "sm" | "xs"` (default: `"default"`)
   - `ghost`: `boolean` (default: `false`)
   - `icon`: `boolean` (default: `false`)
   - `class`: `string` (optional, merged via `clsx`)
   - All standard `HTMLButtonElement` attributes EXCEPT `type` — `type` is hardcoded to `"button"` and must not be overridable via props or spread
   - `ref` callback: `ref?: (el: HTMLButtonElement | null) => void`

3. The component renders `<button type="button" ...>` with classes composed via `clsx`. The ghost+semantic combo classes (ghost.success, ghost.warning, etc.) need compound selectors in the module CSS: `.ghost.success:hover { ... }`.

4. Write unit tests in `button.test.tsx`: verify `type="button"` is always present (cannot be overridden), verify each variant/size/ghost/icon prop applies correct classes, verify `class` prop merges, verify `disabled` prop works, verify `ref` callback is called, verify `aria-label` and `data-testid` pass through.

### Badge (`badge.tsx` + `badge.module.css`)

1. Read `frontend/src/styles/badges.css`. Absorb all styles EXCEPT `.ht-badge--group` and `.ht-badge--cancelled` (dead CSS — drop them). Convert selectors to module-scoped names (`.badge`, `.xs`, `.sm`, `.md`, `.success`, `.danger`, `.warning`, `.info`, `.neutral`).

2. Component props interface:
   - `variant`: Import `StatusVariant` from `../../utils/status` and define as `StatusVariant | "info"` (no default — variant is required)
   - `size`: `"default" | "xs" | "sm" | "md"` (default: `"default"`)
   - `class`: `string` (optional, merged via `clsx`)
   - `children`: `preact.ComponentChildren`
   - Standard span attributes pass-through (`data-testid`, `aria-label`, etc.)

3. The component renders `<span>` with classes composed via `clsx`. Must handle mixed children (text + icons like StatusShape) — the existing `inline-flex` + `gap` styling does this.

4. Write unit tests in `badge.test.tsx`: verify each variant applies correct styling, verify each size, verify `class` prop merges, verify mixed children render correctly (text + icon), verify `data-testid` passes through.

### Pattern reference
Follow the existing component patterns in `frontend/src/components/shared/` — e.g., `empty-state.tsx` for a simple component with module CSS, `show-more-button.tsx` for clsx usage.

## Focus
- `frontend/src/styles/buttons.css` — full CSS to absorb into `button.module.css`
- `frontend/src/styles/badges.css` — full CSS to absorb (minus `--group` and `--cancelled`)
- `frontend/src/utils/status.ts:1` — `StatusVariant` type to import for Badge
- `frontend/src/components/shared/show-more-button.tsx` — reference pattern for `clsx` + module CSS
- `frontend/src/components/shared/spinner.tsx` — reference for minimal component with module CSS
- Ghost+semantic compound selectors require `.ghost.success` in module CSS — Vite CSS Modules supports this
- The `@media (max-width: 900px)` responsive rule in buttons.css must be included in `button.module.css`
- Badge `--group` had `cursor: pointer` and hover behavior; confirm it's unused before dropping (it is — zero TSX references)

## Verify
- [ ] FR#1: Button renders `<button type="button">` and the `type` attribute cannot be overridden via props
- [ ] FR#2: Button accepts `variant`, `size`, `ghost`, `icon` props that produce the correct CSS classes
- [ ] FR#3: Button passes through `disabled`, `ref`, `data-testid`, `aria-label`, `aria-expanded`, `title`
- [ ] FR#4: Badge renders `<span>` with `variant` and `size` props producing correct CSS classes
- [ ] FR#5: Badge renders mixed children (text + StatusShape icon) without layout breakage
- [ ] FR#15: Badge module CSS does not contain `--group` or `--cancelled` variant styles
