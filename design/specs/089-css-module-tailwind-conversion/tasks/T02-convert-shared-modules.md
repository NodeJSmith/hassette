---
task_id: "T02"
title: "Convert shared component CSS modules to Tailwind"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#13"]
---

## Summary

Convert the 26 CSS Module files in `components/shared/` (22 in the root + 4 in log-table/) to Tailwind utility classes. These components are imported by pages and other components throughout the app, so converting them first ensures downstream conversions can use the updated API. Each module file is converted by moving its CSS rules to Tailwind utilities in the TSX, removing the `styles` import, and deleting the `.module.css` file. All `className` composition uses `cn()`.

## Target Files

- delete: `frontend/src/components/shared/action-buttons.module.css`
- modify: `frontend/src/components/shared/action-buttons.tsx`
- delete: `frontend/src/components/shared/app-link.module.css`
- modify: `frontend/src/components/shared/app-link.tsx`
- delete: `frontend/src/components/shared/breadcrumbs.module.css`
- modify: `frontend/src/components/shared/breadcrumbs.tsx`
- delete: `frontend/src/components/shared/config-schema-view.module.css`
- modify: `frontend/src/components/shared/config-schema-view.tsx`
- delete: `frontend/src/components/shared/detail-panel.module.css`
- modify: `frontend/src/components/shared/detail-panel.tsx`
- delete: `frontend/src/components/shared/detail-stats.module.css`
- modify: `frontend/src/components/shared/detail-stats.tsx`
- delete: `frontend/src/components/shared/empty-state.module.css`
- modify: `frontend/src/components/shared/empty-state.tsx`
- delete: `frontend/src/components/shared/error-banner.module.css`
- modify: `frontend/src/components/shared/error-banner.tsx`
- delete: `frontend/src/components/shared/execution-logs.module.css`
- modify: `frontend/src/components/shared/execution-logs.tsx`
- delete: `frontend/src/components/shared/execution-table.module.css`
- modify: `frontend/src/components/shared/execution-table.tsx`
- delete: `frontend/src/components/shared/icons.module.css`
- modify: `frontend/src/components/shared/icons.tsx`
- delete: `frontend/src/components/shared/mini-sparkline.module.css`
- modify: `frontend/src/components/shared/mini-sparkline.tsx`
- delete: `frontend/src/components/shared/registration-source.module.css`
- modify: `frontend/src/components/shared/registration-source.tsx`
- delete: `frontend/src/components/shared/show-more-button.module.css`
- modify: `frontend/src/components/shared/show-more-button.tsx`
- delete: `frontend/src/components/shared/sort-header.module.css`
- modify: `frontend/src/components/shared/sort-header.tsx`
- delete: `frontend/src/components/shared/source-location.module.css`
- modify: `frontend/src/components/shared/source-location.tsx`
- delete: `frontend/src/components/shared/spinner.module.css`
- modify: `frontend/src/components/shared/spinner.tsx`
- delete: `frontend/src/components/shared/stats-strip.module.css`
- modify: `frontend/src/components/shared/stats-strip.tsx`
- delete: `frontend/src/components/shared/system-health.module.css`
- modify: `frontend/src/components/shared/system-health.tsx`
- delete: `frontend/src/components/shared/table-footer.module.css`
- modify: `frontend/src/components/shared/table-footer.tsx`
- delete: `frontend/src/components/shared/theme-toggle.module.css`
- modify: `frontend/src/components/shared/theme-toggle.tsx`
- delete: `frontend/src/components/shared/traceback-viewer.module.css`
- modify: `frontend/src/components/shared/traceback-viewer.tsx`
- delete: `frontend/src/components/shared/log-table/column-picker.module.css`
- modify: `frontend/src/components/shared/log-table/column-picker.tsx`
- delete: `frontend/src/components/shared/log-table/log-detail-drawer.module.css`
- modify: `frontend/src/components/shared/log-table/log-detail-drawer.tsx`
- delete: `frontend/src/components/shared/log-table/log-table-view.module.css`
- modify: `frontend/src/components/shared/log-table/log-table-view.tsx`
- delete: `frontend/src/components/shared/log-table/log-table.module.css`
- modify: `frontend/src/components/shared/log-table/log-table-with-drawer.tsx`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

Convert all 26 CSS Module files under `frontend/src/components/shared/` (including 4 in `log-table/`) to Tailwind utility classes.

**For each `.module.css` file:**

1. Read the CSS Module file and its corresponding TSX file
2. For each CSS class in the module, identify the equivalent Tailwind utilities using the token mapping in the design doc's "Architecture → Phase 2" section
3. In the TSX file:
   - Remove the `import styles from "./<name>.module.css"` line
   - Add `import { cn } from "@/lib/utils"` if not already present
   - Replace every `styles.<className>` reference with `cn("tailwind-classes")` or inline Tailwind class strings
   - If the file imports `clsx`, replace with `cn` and update all `clsx()` calls to `cn()`
4. Delete the `.module.css` file

**Token mapping reference (old → Tailwind):**

| Old token | Tailwind utility |
|---|---|
| `var(--sp-N)` | spacing scale `p-N`, `m-N`, `gap-N` |
| `var(--ink-1)` | `text-foreground` |
| `var(--ink-2)` | `text-foreground-secondary` |
| `var(--ink-3)` | `text-muted-foreground` |
| `var(--ink-4)` | `text-foreground-faint` |
| `var(--bg-surface)` | `bg-card` |
| `var(--bg-sunken)` | `bg-muted` |
| `var(--bg-active)` | `bg-[var(--highlight-bg)]` |
| `var(--line-1)` | `border-border` |
| `var(--line-2)` | `border-[var(--border-subtle)]` |
| `var(--accent)` | `text-primary` |
| `var(--err)` | `text-destructive` |
| `var(--fs-small)` | `text-sm` |
| `var(--fs-micro)` | `text-xs` |
| `var(--fw-medium)` | `font-medium` |
| `var(--fw-semibold)` | `font-semibold` |
| `var(--font-mono)` | `font-mono` |
| `var(--r-md)` | `rounded-md` |
| `var(--r-sm)` | `rounded-sm` |

For tokens without a direct Tailwind utility, use arbitrary value syntax: `[color:var(--handler-job)]`, `max-w-[var(--size-content-narrow)]`, etc.

**Special cases:**
- `spinner.module.css` has `@keyframes spin` — use Tailwind's built-in `animate-spin`. Remove the `@keyframes` declaration entirely.
- `log-detail-drawer.module.css` (298 lines) is the largest file — work through it methodically, class by class. It has responsive `@media` queries that should use the custom Tailwind screen prefixes registered in T01.
- `config-schema-view.module.css` (204 lines) has complex nested selectors — use Tailwind's arbitrary variant syntax (`[&>:first-child]:pt-0`) or child combinators where needed.
- Files with `:global()` overrides targeting `.ht-*` classes — when both the module and the global class will be removed (the global classes are removed in T05), convert the override to direct Tailwind classes at the component level.
- Files with component-local CSS variables (`--health-card-height`, `--log-scroll-max-height`) — move to inline `style` attributes or Tailwind arbitrary values.

## Focus

- `log-table.module.css` is imported by `log-table-with-drawer.tsx`, not by a `log-table.tsx` — verify the correct consumer.
- `stats-strip.tsx`, `system-health.tsx`, `traceback-viewer.tsx`, `detail-stats.tsx`, and `error-display.tsx` still import `clsx` — migrate these to `cn()` as part of this task (FR#13 partial).
- `execution-table.tsx` has `:global(.ht-table)` overrides — the `ht-table` class will be removed in T05 (global CSS removal). For now, apply the table styles directly with Tailwind utilities at the component level.
- `table-footer.tsx` references both its own module CSS and the `column-filter-popover` module CSS (which was already deleted by spec 088). Check if this import still exists and clean it up.
- The test file `table-card.test.tsx` queries by `.ht-table-card-scroll` — this will break when the global class is removed in T05. Note this for T05's scope.

## Verify

- [ ] FR#1: `find frontend/src/components/shared -name '*.module.css' | wc -l` returns 0. All 26 shared component CSS Module files are deleted.
- [ ] FR#13: All `className` composition in modified files uses `cn()`. `grep -rn 'from "clsx"' frontend/src/components/shared/` returns no results.
