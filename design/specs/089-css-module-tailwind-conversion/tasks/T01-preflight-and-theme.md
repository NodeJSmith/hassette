---
task_id: "T01"
title: "Adopt Tailwind Preflight and register custom theme"
status: "planned"
depends_on: []
implements: ["FR#2", "FR#7", "AC#7"]
---

## Summary

Replace the hand-rolled reset (`styles/reset.css`) with Tailwind Preflight and register custom screen breakpoints in the `@theme` block. This is the foundation for all subsequent CSS Module conversions — Preflight changes the baseline rendering of all elements, and the custom screens enable responsive Tailwind prefixes. Also preserve `styles/fonts.css` (its `@font-face` declarations have no Tailwind equivalent).

## Target Files

- modify: `frontend/src/global.css`
- delete: `frontend/src/styles/reset.css`
- read: `frontend/src/styles/fonts.css`
- read: `frontend/src/components/shared/spinner.module.css`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

Replace the hand-rolled reset with Tailwind Preflight and register custom breakpoints in the Tailwind theme.

**Step 1 — Switch to full Tailwind import with Preflight:**

In `frontend/src/global.css`, replace the two separate Tailwind imports:
```css
@import "tailwindcss/theme.css" layer(theme);
@import "tailwindcss/utilities.css" layer(utilities);
```
with the single full import:
```css
@import "tailwindcss";
```
This adds Preflight (Tailwind's reset layer) alongside theme and utilities. Remove the comments about skipping Preflight.

**Step 2 — Remove the hand-rolled reset import:**

Remove `@import "./styles/reset.css";` from `global.css`. Delete the file `frontend/src/styles/reset.css`.

**Step 3 — Preserve hassette-specific reset rules:**

Preflight does NOT include these hassette-specific rules from reset.css. Add them to `global.css` inside a `@layer base` block:

```css
@layer base {
  /* Focus indicator — zero specificity so component overrides win */
  :where(:focus-visible) {
    outline: var(--border-width-medium) solid var(--primary);
    outline-offset: var(--spacing-0-5);
  }

  /* Reduced motion */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
    }
  }
}
```

Note: the focus indicator uses the new shadcn-aliased token names (`--primary` instead of `--accent`, `--border-width-medium` instead of `--border-med`, `--spacing-0-5` instead of `--sp-0`). This is safe because the alias layer in global.css already defines these.

**Step 4 — Register custom screens:**

Add custom screen breakpoints to the `@theme inline` block in `global.css`. The project uses non-standard breakpoints that must be available as Tailwind responsive prefixes:

```css
@theme inline {
  /* Custom breakpoints — sync with BREAKPOINT_* constants in use-media-query.ts */
  --breakpoint-tablet: 1024px;
  --breakpoint-sidebar: 900px;
  --breakpoint-mobile: 768px;
  --breakpoint-small-mobile: 480px;
  /* ... existing theme entries ... */
}
```

These enable `max-tablet:`, `max-sidebar:`, `max-mobile:`, `max-small-mobile:` prefixes in Tailwind utilities.

**Step 5 — Verify fonts.css is preserved:**

Confirm `@import "./styles/fonts.css";` remains in `global.css`. Do not modify `styles/fonts.css` — `@font-face` declarations cannot be expressed as Tailwind utilities (FR#7).

**Step 6 — Build and test:**

Run `cd frontend && npm run build` and `cd frontend && npm run test` to verify nothing broke. Preflight changes how elements render by default — buttons lose background/padding, images become block-level, etc. If any tests fail due to Preflight's more aggressive reset, the failures are expected and will be addressed in subsequent tasks when those components' CSS Modules are converted.

## Focus

- Preflight is more aggressive than the current reset. Key differences: it resets `button` (removes background, border, padding), adds `border-style: solid; border-width: 0` to all elements, and makes `img` block-level. Components that relied on browser-default button styling may look unstyled until their CSS Modules are converted.
- The focus indicator rule uses `:where(:focus-visible)` for zero specificity — this must be preserved exactly. Preflight does NOT include a focus indicator.
- The custom screens must match the exact pixel values used in `frontend/src/hooks/use-media-query.ts` (`BREAKPOINT_SIDEBAR = 900`, `BREAKPOINT_MOBILE = 768`, `BREAKPOINT_SMALL_MOBILE = 480`). The `check_breakpoint_drift.py` lint tool validates this synchronization.
- `spinner.module.css` defines `@keyframes spin` — Tailwind has a built-in `animate-spin` utility. This will be handled when the spinner module is converted in a later task, not here.

## Verify

- [ ] FR#2: `grep -n 'preflight\|@import "tailwindcss"' frontend/src/global.css` shows Tailwind imported with Preflight. `ls frontend/src/styles/reset.css 2>/dev/null` returns no file. Focus indicator and reduced-motion rules exist in a `@layer base` block in global.css.
- [ ] FR#7: `ls frontend/src/styles/fonts.css` returns the file. `grep 'fonts.css' frontend/src/global.css` shows it is still imported.
- [ ] AC#7: `ls frontend/src/styles/fonts.css 2>/dev/null | wc -l` returns 1.
