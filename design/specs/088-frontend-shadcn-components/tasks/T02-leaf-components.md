---
task_id: "T02"
title: "Replace Button, Badge, Chip, Card, Tooltip with shadcn"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#4", "FR#5", "FR#6", "AC#1", "AC#2", "AC#3", "AC#7", "AC#8"]
---

## Summary

Generate shadcn Button, Badge, Card, and Tooltip via `npx shadcn@latest add`. Customize each with hassette-specific variants/sizes. Update all consumer call sites directly to shadcn's prop API (no thin wrappers). Merge Chip into Badge as additional variants. Delete all hand-rolled component files and their CSS Modules and tests. Rewrite tests for the new APIs.

## Target Files

- create: `frontend/src/components/ui/button.tsx`
- create: `frontend/src/components/ui/badge.tsx`
- create: `frontend/src/components/ui/card.tsx`
- create: `frontend/src/components/ui/tooltip.tsx`
- delete: `frontend/src/components/shared/button.tsx`
- delete: `frontend/src/components/shared/button.module.css`
- delete: `frontend/src/components/shared/button.test.tsx`
- delete: `frontend/src/components/shared/badge.tsx`
- delete: `frontend/src/components/shared/badge.module.css`
- delete: `frontend/src/components/shared/badge.test.tsx`
- delete: `frontend/src/components/shared/chip.tsx`
- delete: `frontend/src/components/shared/chip.module.css`
- delete: `frontend/src/components/shared/chip.test.tsx`
- delete: `frontend/src/components/shared/card.tsx`
- delete: `frontend/src/components/shared/card.module.css`
- delete: `frontend/src/components/shared/card.test.tsx`
- delete: `frontend/src/components/shared/tooltip.tsx`
- delete: `frontend/src/components/shared/tooltip.module.css`
- delete: `frontend/src/components/shared/tooltip.test.tsx`
- modify: `frontend/src/components/app-detail/code-tab.tsx`
- modify: `frontend/src/components/app-detail/handlers-tab.tsx`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- modify: `frontend/src/components/app-detail/registration-footer.tsx`
- modify: `frontend/src/components/app-detail/app-detail-header.tsx`
- modify: `frontend/src/components/app-detail/detail-header.tsx`
- modify: `frontend/src/components/app-detail/execution-detail.tsx`
- modify: `frontend/src/components/app-detail/multi-instance.tsx`
- modify: `frontend/src/components/app-detail/unified-handler-row.tsx`
- modify: `frontend/src/components/app-detail/listener-detail.tsx`
- modify: `frontend/src/components/app-detail/config-tab.tsx`
- modify: `frontend/src/components/app-detail/handler-health-card.tsx`
- modify: `frontend/src/components/app-detail/handler-mode-chip.tsx`
- modify: `frontend/src/components/design/component-showcase.tsx`
- modify: `frontend/src/components/layout/error-boundary.tsx`
- modify: `frontend/src/components/layout/status-bar.tsx`
- modify: `frontend/src/components/layout/sidebar.tsx`
- modify: `frontend/src/components/shared/config-schema-view.tsx`
- modify: `frontend/src/components/shared/show-more-button.tsx`
- modify: `frontend/src/components/shared/action-buttons.tsx`
- modify: `frontend/src/components/shared/execution-table.tsx`
- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/pages/apps-table-row.tsx`
- modify: `frontend/src/pages/handlers.tsx`
- modify: `frontend/src/pages/handlers-rows.tsx`
- modify: `frontend/src/pages/diagnostics.tsx`
- modify: `frontend/src/components/shared/log-table/log-table-row.tsx`
- read: `frontend/src/components/shared/button.tsx` (current API surface)
- read: `frontend/src/components/shared/badge.tsx` (current API surface)
- read: `frontend/src/components/shared/chip.tsx` (current API surface)
- read: `frontend/src/components/shared/card.tsx` (current API surface)

## Prompt

Read the current implementations of `button.tsx`, `badge.tsx`, `chip.tsx`, `card.tsx`, and `tooltip.tsx` in `frontend/src/components/shared/` to understand their prop interfaces and consumer patterns.

**Button** (10 consumers + show-more-button, action-buttons, log-table-row, sidebar):
1. Generate: `npx shadcn@latest add button`
2. Customize the generated `components/ui/button.tsx`: add `success`/`warning`/`info`/`danger` variants. Add `xs` size. Keep `type="button"` as default. shadcn Button already uses `forwardRef`.
3. Variant mapping: `default` -> `default`, `primary` -> `default` (shadcn default is primary-colored), `ghost` boolean -> `variant="ghost"`, `icon` boolean -> `variant="ghost" size="icon"`. The `buttonRef` prop -> standard `ref`.
4. Update all consumers to import from `@/components/ui/button` and use the new prop API.

**Badge** (7 consumers) + **Chip** (9 consumers -> merged into Badge):
1. Generate: `npx shadcn@latest add badge`
2. Extend with variants covering the current `BadgeVariant` set AND the Chip's kind-based coloring (simplified from the discriminated union to flat variants).
3. Update all Badge consumers to import from `@/components/ui/badge`.
4. Update all Chip consumers to import Badge from `@/components/ui/badge` with the appropriate variant.

**Card** (5 component consumers + 1 direct CSS import):
1. Generate: `npx shadcn@latest add card`
2. Add `variant` support (`default`/`compact`/`config`/`error`) to match current Card.
3. Fix `diagnostics.tsx`'s direct `card.module.css` import -- convert to use the Card component.
4. Note: `overview-tab.tsx`, `app-logs-panel.tsx`, `execution-logs.tsx` import `TableCard`, not `Card` -- don't touch those.

**Tooltip** (1 consumer: `handler-health-card.tsx`):
1. Generate: `npx shadcn@latest add tooltip`
2. Update `handler-health-card.tsx` to use shadcn Tooltip (wrap trigger in `TooltipTrigger`, content in `TooltipContent`, wrapped in `Tooltip` and `TooltipProvider`).

Delete all old component files (`.tsx`, `.module.css`, `.test.tsx`). Rewrite tests for the new shadcn APIs — test files stay in their original locations (e.g., `components/shared/button.test.tsx` tests `components/ui/button.tsx`; the test path doesn't move to `ui/`). Use `cn()` instead of `clsx()` in all modified files.

## Focus

- **Gap-check files**: `show-more-button.tsx` and `handler-mode-chip.tsx` were found as unlisted consumers of Button and Chip respectively during the reverse-dependency check. Both must be updated.
- `diagnostics.tsx` imports `card.module.css` directly (bypassing the Card component) -- this is a known edge case, convert it to use the shadcn Card component.
- `handler-health-card.tsx` path is `frontend/src/components/app-detail/handler-health-card.tsx` (not `components/shared/`).
- `apps-table-row.tsx` path is `frontend/src/pages/apps-table-row.tsx` (not `components/shared/`).
- The Chip discriminated union (`variant: "kind"` requires `kind: ChipKind`) is intentionally being flattened to simple Badge variants. This is a conscious trade-off -- the compile-time guard is being removed in favor of a simpler API.
- `log-table-row.tsx` imports Button but is scheduled for deletion in T04 -- still update the import in this task so the codebase builds between tasks.

## Verify

- [ ] FR#3: All consumers import Button from `@/components/ui/button`; `ghost` boolean replaced with `variant="ghost"`; `buttonRef` replaced with `ref`
- [ ] FR#4: All Badge consumers import from `@/components/ui/badge`; all Chip consumers import Badge with appropriate variant; Chip files deleted
- [ ] FR#5: Card imported from `@/components/ui/card` by all consumers; `diagnostics.tsx` no longer imports `card.module.css` directly
- [ ] FR#6: `handler-health-card.tsx` uses shadcn Tooltip (`TooltipProvider`/`Tooltip`/`TooltipTrigger`/`TooltipContent`)
- [ ] AC#1: `cd frontend && npm run build` exits 0
- [ ] AC#2: `cd frontend && npm run test` reports 0 failures
- [ ] AC#3: `cd frontend && npm run typecheck` exits 0
- [ ] AC#7: `ls frontend/src/components/shared/button.tsx frontend/src/components/shared/badge.tsx frontend/src/components/shared/chip.tsx frontend/src/components/shared/card.tsx frontend/src/components/shared/tooltip.tsx 2>/dev/null` returns no files
- [ ] AC#8: `ls frontend/src/components/ui/button.tsx frontend/src/components/ui/badge.tsx frontend/src/components/ui/card.tsx frontend/src/components/ui/tooltip.tsx 2>/dev/null | wc -l` returns 4
