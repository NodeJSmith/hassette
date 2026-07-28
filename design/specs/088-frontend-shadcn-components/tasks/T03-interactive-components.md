---
task_id: "T03"
title: "Replace AlertDialog, Popover, Command; restyle TimePresetSelector"
status: "done"
depends_on: ["T02"]
implements: ["FR#7", "FR#8", "FR#9", "FR#10", "FR#15", "FR#16", "AC#5", "AC#6", "AC#7", "AC#8"]
---

## Summary

Generate shadcn AlertDialog, Popover, and Command via `npx shadcn@latest add`. Replace `confirm-dialog.tsx`, `info-popover.tsx`, `column-filter-popover/`, and `command-palette.tsx` with their shadcn equivalents. Restyle `time-preset-selector.tsx` with Tailwind and `cn()` (no shadcn component generation). Remove `@floating-ui/dom` as a direct dependency and delete `utils/focus-trap.ts`. Rewrite affected tests.

## Target Files

- create: `frontend/src/components/ui/alert-dialog.tsx`
- create: `frontend/src/components/ui/popover.tsx`
- create: `frontend/src/components/ui/command.tsx`
- delete: `frontend/src/components/shared/confirm-dialog.tsx`
- delete: `frontend/src/components/shared/confirm-dialog.module.css`
- delete: `frontend/src/components/shared/confirm-dialog.test.tsx`
- delete: `frontend/src/components/shared/info-popover.tsx`
- delete: `frontend/src/components/shared/info-popover.module.css`
- delete: `frontend/src/components/shared/info-popover.test.tsx`
- delete: `frontend/src/components/shared/column-filter-popover/` (entire directory)
- delete: `frontend/src/components/layout/command-palette.tsx`
- delete: `frontend/src/components/layout/command-palette.module.css`
- delete: `frontend/src/components/layout/command-palette.test.tsx`
- delete: `frontend/src/utils/focus-trap.ts`
- modify: `frontend/src/components/shared/action-buttons.tsx`
- modify: `frontend/src/components/shared/config-schema-view.tsx`
- modify: `frontend/src/components/shared/log-table/column-picker.tsx`
- modify: `frontend/src/components/shared/log-table/use-log-table.tsx`
- modify: `frontend/src/components/shared/sort-header.tsx`
- modify: `frontend/src/components/shared/table-footer.tsx`
- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/app.tsx`
- modify: `frontend/src/components/layout/time-preset-selector.tsx`
- modify: `frontend/src/components/layout/time-preset-selector.module.css`
- modify: `frontend/src/components/layout/time-preset-selector.test.tsx`
- modify: `frontend/package.json`
- read: `frontend/src/components/shared/confirm-dialog.tsx` (current API)
- read: `frontend/src/components/shared/info-popover.tsx` (current API)
- read: `frontend/src/components/shared/column-filter-popover/index.tsx` (current API)
- read: `frontend/src/components/layout/command-palette.tsx` (current API)

## Prompt

Read each current component implementation to understand the prop interfaces and behavior before replacing.

**AlertDialog** (1 consumer: `action-buttons.tsx`):
1. Generate: `npx shadcn@latest add alert-dialog`
2. Replace `confirm-dialog.tsx` with AlertDialog. The `tone` prop (`default`/`danger`) maps to AlertDialog's action button styling (`AlertDialogAction` with destructive variant for danger). The manual focus trap, Escape/Tab handling, and random-id `aria-labelledby`/`aria-describedby` are all removed -- Radix provides these.
3. Update `action-buttons.tsx` to use `AlertDialog`/`AlertDialogTrigger`/`AlertDialogContent`/`AlertDialogHeader`/`AlertDialogTitle`/`AlertDialogDescription`/`AlertDialogFooter`/`AlertDialogCancel`/`AlertDialogAction`.

**Popover** (1 info-popover consumer + 5 column-filter-popover consumers + 1 direct CSS import):
1. Generate: `npx shadcn@latest add popover`
2. Replace `info-popover.tsx` (1 consumer: `config-schema-view.tsx`) with shadcn Popover. Remove `@floating-ui/dom` positioning.
3. Replace `column-filter-popover/` (consumers: `column-picker.tsx`, `use-log-table.tsx`, `sort-header.tsx`, `table-footer.tsx`, `apps.tsx`) with shadcn Popover. Evaluate whether the `ignoreNextClick` guard is still needed with Radix's open/close state management.
4. Fix `use-log-table.tsx`'s direct `column-filter-popover/index.module.css` import -- replace the `filterStyles.tierGroup`/`filterStyles.tierBtn` styling with Tailwind utilities or inline styles since the CSS Module file is being deleted.
5. Fix `apps.tsx`'s direct `column-filter-popover/index.module.css` import similarly.

**Command** (1 consumer: `app.tsx`):
1. Generate: `npx shadcn@latest add command`
2. Replace `command-palette.tsx` with shadcn Command (wraps cmdk). Wire the existing react-query listener fetch into cmdk's item filtering. Replace manual arrow-key navigation and sentinel-div focus trap with cmdk's built-in keyboard handling. Preserve the `Cmd+K`/`Ctrl+K` trigger.

**TimePresetSelector** (1 consumer: `status-bar.tsx`):
1. Restyle with Tailwind utilities and `cn()`. Keep the existing `<select>` (mobile) and `<button aria-pressed>` (desktop) markup unchanged.
2. The `.module.css` file may be reduced or deleted once styles are in Tailwind.

**Cleanup:**
1. Remove `@floating-ui/dom` from `package.json` devDependencies/dependencies (it remains as a transitive dep of `@radix-ui/react-popper`).
2. Delete `frontend/src/utils/focus-trap.ts` -- orphaned after Radix owns focus trapping in AlertDialog and Popover.

Rewrite all affected tests — test files stay in their original locations (e.g., `components/shared/confirm-dialog.test.tsx` tests the AlertDialog replacement; `components/layout/command-palette.test.tsx` tests the Command replacement). Remove tests that directly test focus-trap logic — tests should verify the outcome (dialog traps focus) via user interaction, not the mechanism.

## Focus

- `use-log-table.tsx` (line 9) has a direct CSS-module import of `column-filter-popover/index.module.css` used for tier-filter button styling (`filterStyles.tierGroup`/`filterStyles.tierBtn`). This file is being deleted -- the tier buttons need replacement styling (Tailwind utilities).
- `apps.tsx` also has a direct CSS-module import from `column-filter-popover/` -- same treatment needed.
- `focus-trap.ts` has two consumers: `confirm-dialog.tsx` and `column-filter-popover/index.tsx`. Both are being deleted in this task, so the utility is safely orphaned.
- `command-palette.tsx` has its own separate focus-trap mechanism (sentinel div pattern, not using the shared `focus-trap.ts` utility) -- cmdk replaces this entirely.
- `@floating-ui/dom` stays as a transitive dependency (via `@radix-ui/react-popper`) -- FR#15 only removes the manual usage code and the direct `package.json` entry, not the package from node_modules.

## Verify

- [ ] FR#7: `action-buttons.tsx` uses AlertDialog compound components; no manual focus trap or keyboard handling remains
- [ ] FR#8: `config-schema-view.tsx` uses shadcn Popover instead of InfoPopover; all 5 column-filter-popover consumers use shadcn Popover; `column-filter-popover/` directory deleted
- [ ] FR#9: `app.tsx` integrates shadcn Command wrapping cmdk; react-query listener fetch works; `Cmd+K`/`Ctrl+K` trigger works
- [ ] FR#10: `time-preset-selector.tsx` restyled with Tailwind; existing `<select>`/`<button>` markup preserved; responsive behavior works
- [ ] FR#15: `grep -rn '@floating-ui' frontend/src/ --include='*.ts' --include='*.tsx' | grep -v node_modules` returns no results
- [ ] FR#16: `ls frontend/src/utils/focus-trap.ts 2>/dev/null` returns no file
- [ ] AC#5: No manual `@floating-ui/dom` usage in source code
- [ ] AC#6: `focus-trap.ts` does not exist
- [ ] AC#7: `ls frontend/src/components/shared/confirm-dialog.tsx frontend/src/components/shared/info-popover.tsx frontend/src/components/shared/column-filter-popover/index.tsx frontend/src/components/layout/command-palette.tsx 2>/dev/null` returns no files
- [ ] AC#8: `ls frontend/src/components/ui/alert-dialog.tsx frontend/src/components/ui/popover.tsx frontend/src/components/ui/command.tsx 2>/dev/null | wc -l` returns 3
