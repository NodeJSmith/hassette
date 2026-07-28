---
task_id: "T03"
title: "Convert app-detail CSS modules to Tailwind"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1"]
---

## Summary

Convert the 14 CSS Module files in `components/app-detail/` to Tailwind utility classes. This is the densest component area (934 lines of CSS) with complex layout patterns including grids, responsive behavior, and status-driven conditional styling. Several of these components import shared components that may also be converted in T02 (which targets the disjoint `components/shared/` directory). No file conflicts exist between T02 and T03 — they can run in parallel.

## Target Files

- delete: `frontend/src/components/app-detail/code-tab.module.css`
- modify: `frontend/src/components/app-detail/code-tab.tsx`
- delete: `frontend/src/components/app-detail/config-tab.module.css`
- modify: `frontend/src/components/app-detail/config-tab.tsx`
- delete: `frontend/src/components/app-detail/detail-header.module.css`
- modify: `frontend/src/components/app-detail/detail-header.tsx`
- delete: `frontend/src/components/app-detail/execution-detail.module.css`
- modify: `frontend/src/components/app-detail/execution-detail.tsx`
- delete: `frontend/src/components/app-detail/execution-section.module.css`
- modify: `frontend/src/components/app-detail/execution-section.tsx`
- delete: `frontend/src/components/app-detail/handler-chips.module.css`
- modify: `frontend/src/components/app-detail/handler-chips.tsx`
- delete: `frontend/src/components/app-detail/handler-detail-layout.module.css`
- modify: `frontend/src/components/app-detail/handler-detail-layout.tsx`
- delete: `frontend/src/components/app-detail/handler-health-card.module.css`
- modify: `frontend/src/components/app-detail/handler-health-card.tsx`
- delete: `frontend/src/components/app-detail/handler-list.module.css`
- modify: `frontend/src/components/app-detail/handler-list.tsx`
- delete: `frontend/src/components/app-detail/handlers-tab.module.css`
- modify: `frontend/src/components/app-detail/handlers-tab.tsx`
- delete: `frontend/src/components/app-detail/job-detail.module.css`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- delete: `frontend/src/components/app-detail/overview-tab.module.css`
- modify: `frontend/src/components/app-detail/overview-tab.tsx`
- delete: `frontend/src/components/app-detail/registration-footer.module.css`
- modify: `frontend/src/components/app-detail/registration-footer.tsx`
- delete: `frontend/src/components/app-detail/unified-handler-row.module.css`
- modify: `frontend/src/components/app-detail/unified-handler-row.tsx`
- modify: `frontend/src/components/app-detail/error-spotlight.tsx`
- modify: `frontend/src/components/app-detail/recent-activity-section.tsx`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

Convert all 14 CSS Module files under `frontend/src/components/app-detail/` to Tailwind utility classes. Follow the same conversion pattern as T02 (see context.md Convention Examples).

For each `.module.css` file: read the CSS, identify Tailwind equivalents, update the TSX to use `cn()` with Tailwind utilities, remove the `styles` import, delete the module file.

**Files that still import `clsx`:** `overview-tab.tsx`, `error-spotlight.tsx`, `recent-activity-section.tsx` — migrate to `cn()` as part of this task.

Use the token mapping from context.md and the design doc's "Architecture → Phase 2" section. For tokens without direct Tailwind equivalents, use arbitrary value syntax.

**Responsive patterns:** CSS modules in this directory use `@media (max-width: 768px)` and `@media (max-width: 480px)`. Convert to `max-mobile:` and `max-small-mobile:` Tailwind prefixes (registered in T01).

**Complex patterns to watch:**
- `overview-tab.module.css` (170 lines) — has a health-grid with `grid-template-columns: repeat(auto-fill, minmax(...))`, local CSS variables (`--health-card-height`, `--health-card-min-width`, `--health-grid-rows`), activity table styles with descendant selectors, and a log scroll constraint. The grid uses `auto-fill` with complex `minmax` — use Tailwind's arbitrary grid syntax or an inline `style` attribute for the `grid-template-columns` value.
- `unified-handler-row.module.css` (159 lines) — status-driven color classes, expandable row patterns, nested layout.
- `handler-health-card.module.css` (109 lines) — uses handler-family tokens (`--job`, `--listener`) that map to `--handler-job`/`--handler-listener` aliases.

## Focus

- `overview-tab.tsx` has `:first-child` and descendant selectors that need Tailwind arbitrary variants (`[&>:first-child]:pt-0`, `[&_td]:font-mono`).
- The error spotlight section in `overview-tab.module.css` uses `color-mix(in srgb, var(--err) 30%, transparent)` for a semi-transparent border — this needs an arbitrary value: `border-[color-mix(in_srgb,var(--destructive)_30%,transparent)]` or an inline style.
- `handler-health-card.tsx` uses Tooltip from shadcn (already converted in spec 088) — verify the import path is correct after conversion.

## Verify

- [ ] FR#1: `find frontend/src/components/app-detail -name '*.module.css' | wc -l` returns 0. All 14 app-detail CSS Module files are deleted.
