---
task_id: "T04"
title: "Replace log-table and execution-table with TanStack Table"
status: "planned"
depends_on: ["T03"]
implements: ["FR#11", "FR#13", "AC#1", "AC#2", "AC#3", "AC#8"]
---

## Summary

Install `@tanstack/react-table`. Generate shadcn Table and Drawer via `npx shadcn@latest add`. Convert the log-table subsystem (14 source files) from hand-written per-column JSX to TanStack `ColumnDef` declarations + shadcn Table markup. Rewrite `SortHeader` to emit inner content only (no `<th>`). Convert execution-table similarly. Replace the hand-rolled log-detail-drawer with shadcn Drawer. Preserve all existing hooks unchanged (`useLogFilters`, `useColumnVisibility`, `useRovingTabIndex`, `useLogData`).

## Target Files

- create: `frontend/src/components/ui/table.tsx`
- create: `frontend/src/components/ui/drawer.tsx`
- delete: `frontend/src/components/shared/log-table/log-table-row.tsx`
- delete: `frontend/src/components/shared/log-table/log-table-row.module.css`
- delete: `frontend/src/components/shared/log-table/log-table-header.tsx`
- delete: `frontend/src/components/shared/log-table/log-table-header.module.css`
- modify: `frontend/src/components/shared/log-table/log-table-view.tsx`
- modify: `frontend/src/components/shared/log-table/use-log-table.tsx`
- modify: `frontend/src/components/shared/log-table/log-detail-drawer.tsx`
- modify: `frontend/src/components/shared/log-table/log-table-with-drawer.tsx`
- modify: `frontend/src/components/shared/log-table/column-picker.tsx`
- modify: `frontend/src/components/shared/log-table/constants.ts`
- modify: `frontend/src/components/shared/log-table/types.ts`
- modify: `frontend/src/components/shared/log-table/index.ts`
- modify: `frontend/src/components/shared/execution-table.tsx`
- modify: `frontend/src/components/shared/sort-header.tsx`
- modify: `frontend/src/utils/app-data.ts`
- modify: `frontend/src/utils/handler-rows.ts`
- modify: `frontend/package.json`
- read: `frontend/src/components/shared/log-table/use-log-filters.ts` (preserved unchanged)
- read: `frontend/src/components/shared/log-table/use-column-visibility.ts` (preserved unchanged)
- read: `frontend/src/hooks/use-roving-tab-index.ts` (preserved unchanged)
- read: `frontend/src/components/shared/log-table/use-log-data.ts` (preserved unchanged)
- read: `frontend/src/components/shared/log-table/execution-id-link.tsx` (preserved unchanged)

## Prompt

Install `@tanstack/react-table` via `npm install @tanstack/react-table`. Generate shadcn Table and Drawer: `npx shadcn@latest add table drawer`.

**CRITICAL: Fix shadcn Table wrapper.** After generating `components/ui/table.tsx`, edit it to remove or neutralize the wrapping `<div data-slot="table-container" className="... overflow-x-auto">`. This wrapper creates a new scroll container that breaks `position: sticky` on `<thead>` (the sticky header anchors to the inner wrapper instead of the real scroll ancestor `.ht-table-card-scroll`). Either remove the wrapper entirely or set `overflow-x: visible`.

**SortHeader rewrite (MUST do first):**
Read `frontend/src/components/shared/sort-header.tsx`. Currently every return path is `<th scope="col" ...>`. Rewrite it to return only inner content (the sort button + filter popover) WITHOUT the wrapping `<th>`. `TableHead` (shadcn's styled `<th>`) will own `scope` and `aria-sort`. Thread `aria-sort` value via `column.meta` or a prop.

Also update `SortState` type in `sort-header.tsx` -- this type is imported by `utils/app-data.ts`, `utils/handler-rows.ts`, and `log-table/types.ts` (re-exported as `LogSortState`). Ensure the type change is compatible or update all three consumers.

**Log table migration:**
Read all files in `frontend/src/components/shared/log-table/` to understand the current structure.

1. Convert `constants.ts`'s `COLUMNS` array to TanStack `ColumnDef<LogEntry>[]`. Each column gets `accessorFn`, `header` (using rewritten `SortHeader` as custom renderer), and `cell` closures. Column metadata that TanStack doesn't model (`shortLabel`, `mobileWidth`, `ariaLabel`) goes in `column.meta`.
2. Rewrite `log-table-view.tsx`: replace the hand-written `<table>`/`<thead>`/`<tbody>` with `useReactTable({ data: visibleEntries, columns, getCoreRowModel: getCoreRowModel() })` + shadcn `Table`/`TableHeader`/`TableBody`/`TableRow`/`TableCell`. Use ONLY `getCoreRowModel()` -- do NOT call `getFilteredRowModel()` or `getSortedRowModel()`.
3. Add a code comment at the `useReactTable({ columns: ... })` call site documenting why TanStack's `columnVisibility` is bypassed (viewport-forced hiding via `REQUIRED_COLUMNS`/`viewportHidden` has no TanStack equivalent).
4. Column visibility: filter the `columns` array before passing to `useReactTable` using `useColumnVisibility`'s output. Do NOT use TanStack's `state.columnVisibility`.
5. `SortHeader` in header cells: render `flexRender(...)` for header cells. Since `SortHeader` no longer returns `<th>`, header cells render inside `TableHead` (shadcn's `<th>`) naturally.
6. `useRovingTabIndex` wires against `table.getRowModel().rows` (same container ref pattern as today).
7. Delete `log-table-row.tsx` and `log-table-header.tsx` -- their functionality is absorbed into `ColumnDef` declarations and the `flexRender` loop.
8. Simplify `use-log-table.tsx` (orchestrates fewer sub-components now).
9. Update `index.ts` re-exports.

**Log detail drawer -> shadcn Drawer:**
Rewrite `log-detail-drawer.tsx` using shadcn Drawer. Preserve the CSS-grid desktop / overlay mobile layout in `log-table-with-drawer.tsx`.

**Execution table migration:**
Read `frontend/src/components/shared/execution-table.tsx`. Convert its 5 hardcoded columns to TanStack `ColumnDef<ExecutionRecord>[]` + shadcn Table. Keep the `showAll`/`INITIAL_ROWS` slice logic. Use `getCoreRowModel()` only.

Rewrite all affected tests for the new TanStack Table rendering. The test files for log-table components and execution-table need to assert on the new shadcn Table markup instead of raw `<table>` elements.

## Focus

- **Key constraint**: `useLogFilters`, `useColumnVisibility`, `useRovingTabIndex`, `useLogData`, and `execution-id-link.tsx` are preserved UNCHANGED. They are the external state layer -- TanStack Table is merely controlled by them.
- **Sort state boundary**: hassette uses `{key, dir}`, TanStack uses `{id, desc}`. Keep sort handlers calling directly into `use-log-filters.ts`. Only use `column.getIsSorted()` for display (arrow direction, `aria-sort`) -- don't try to bridge TanStack's sorting model to hassette's.
- **Gap-check files**: `utils/app-data.ts` and `utils/handler-rows.ts` both import `SortState` from `sort-header.tsx`. If the type shape changes, update these consumers.
- **Render cap**: the 200-row `RENDER_CAP` stays in `use-log-filters.ts`. TanStack Table receives the already-capped data.
- **Column visibility and sorting/filtering remain external**: do NOT use TanStack's built-in visibility/sorting/filtering features. The existing hooks handle these with semantics (viewport-forced hiding, level-threshold sorting, etc.) that TanStack's equivalents can't express.
- **`table-card.tsx` and `table-footer.tsx`** are outside the log-table directory. Evaluate whether to keep them as layout wrappers or absorb them -- the design says "may keep as thin layout wrappers or absorb."

## Verify

- [ ] FR#11: Log table uses `useReactTable` + `getCoreRowModel()` + shadcn `Table`/`TableHeader`/`TableBody`/`TableRow`/`TableCell`; execution-table uses same pattern; `log-table-row.tsx` and `log-table-header.tsx` are deleted; `SortHeader` returns inner content only (no `<th>`)
- [ ] FR#13: `log-detail-drawer.tsx` uses shadcn Drawer components
- [ ] AC#1: `cd frontend && npm run build` exits 0
- [ ] AC#2: `cd frontend && npm run test` reports 0 failures
- [ ] AC#3: `cd frontend && npm run typecheck` exits 0
- [ ] AC#8: `ls frontend/src/components/ui/table.tsx frontend/src/components/ui/drawer.tsx 2>/dev/null | wc -l` returns 2
