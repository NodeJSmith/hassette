---
task_id: "T04"
title: "Convert layout, design, and page CSS modules to Tailwind"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1"]
---

## Summary

Convert the remaining 14 CSS Module files across three directories: `components/layout/` (2 files, 160 lines), `components/design/` (5 files, 250 lines), and `pages/` (7 files, 803 lines). These are the last CSS Module files in the codebase. After this task, AC#1 (`find frontend/src -name '*.module.css' | wc -l` returns 0) is achievable.

## Target Files

- delete: `frontend/src/components/layout/alert-banner.module.css`
- modify: `frontend/src/components/layout/alert-banner.tsx`
- delete: `frontend/src/components/layout/status-bar.module.css`
- modify: `frontend/src/components/layout/status-bar.tsx`
- delete: `frontend/src/components/design/color-tokens.module.css`
- modify: `frontend/src/components/design/color-tokens.tsx`
- delete: `frontend/src/components/design/component-showcase.module.css`
- modify: `frontend/src/components/design/component-showcase.tsx`
- delete: `frontend/src/components/design/section.module.css`
- modify: `frontend/src/components/design/section.tsx`
- delete: `frontend/src/components/design/spacing-tokens.module.css`
- modify: `frontend/src/components/design/spacing-tokens.tsx`
- delete: `frontend/src/components/design/typography-tokens.module.css`
- modify: `frontend/src/components/design/typography-tokens.tsx`
- delete: `frontend/src/pages/app-detail.module.css`
- modify: `frontend/src/pages/app-detail.tsx`
- modify: `frontend/src/components/app-detail/multi-instance.tsx`
- modify: `frontend/src/components/app-detail/app-detail-header.tsx`
- delete: `frontend/src/pages/apps.module.css`
- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/pages/apps-table-row.tsx`
- delete: `frontend/src/pages/design.module.css`
- modify: `frontend/src/pages/design.tsx`
- delete: `frontend/src/pages/diagnostics.module.css`
- modify: `frontend/src/pages/diagnostics.tsx`
- delete: `frontend/src/pages/handlers.module.css`
- modify: `frontend/src/pages/handlers.tsx`
- modify: `frontend/src/pages/handlers-rows.tsx`
- delete: `frontend/src/pages/logs.module.css`
- modify: `frontend/src/pages/logs.tsx`
- delete: `frontend/src/pages/not-found.module.css`
- modify: `frontend/src/pages/not-found.tsx`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

Convert all remaining CSS Module files to Tailwind utility classes. Follow the same conversion pattern as T02 and T03.

**Layout components (2 files):**
- `alert-banner.module.css` → `alert-banner.tsx` — alert styling with tone variants. `alert-banner.tsx` imports `clsx` — migrate to `cn()`.
- `status-bar.module.css` → `status-bar.tsx` — fixed/sticky status bar with responsive behavior. Has `@media (max-width: 768px)` rules that become `max-mobile:` prefixes.

**Design components (5 files):**
These are the design system showcase pages — they display tokens, colors, spacing, and typography samples. They have relatively simple CSS but may reference raw token names for display purposes (showing the token name as text, not as a CSS value). Only convert the *styling* — preserve any token name strings used as display content.

**Page components (7 files):**
- `apps.module.css` → `apps.tsx` — table layout with filter/search bar.
- `handlers.module.css` → `handlers.tsx` — similar table layout.
- `logs.module.css` → `logs.tsx` — log table page with toolbar.
- `app-detail.module.css` → `app-detail.tsx` — tab-based detail layout with responsive behavior. `app-detail.tsx` imports `clsx` — migrate to `cn()`.
- `diagnostics.module.css` → `diagnostics.tsx` — diagnostic panels layout.
- `design.module.css` → `design.tsx` — design system page layout.
- `not-found.module.css` → `not-found.tsx` — 404 page styling.

For tokens without direct Tailwind equivalents, use arbitrary value syntax. Use `max-mobile:`, `max-small-mobile:`, and `max-sidebar:` for responsive rules.

## Focus

- `status-bar.module.css` has z-index (`var(--z-status-bar)`) and fixed/absolute positioning with mobile responsive rules — use `z-[var(--z-status-bar-layer)]` or register the z-index in `@theme`.
- `apps.module.css` and `handlers.module.css` contain page-level layout and filter/search bar styles. Read the actual file contents — do not assume specific class names.
- The `design/` components exist solely for the design system showcase page — they display token values visually. Their CSS is straightforward (grid layouts, color swatches, font specimens).
- `diagnostics.tsx` previously imported `card.module.css` directly (fixed in spec 088 to use shadcn Card). Verify this is clean.

## Verify

- [ ] FR#1: `find frontend/src/components/layout frontend/src/components/design frontend/src/pages -name '*.module.css' | wc -l` returns 0. All 14 remaining CSS Module files are deleted.
