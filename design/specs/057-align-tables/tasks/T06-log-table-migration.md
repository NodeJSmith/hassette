---
task_id: "T06"
title: "Migrate log table to unified table pattern"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3"]
---

## Summary
Migrate the log table to the unified shared components: replace `HeaderCell` with `SortHeader`, replace `LogTableFooter` with shared `TableFooter`, build a `columnFilters` map to replace `filterFor()`, move search to `TableCard`, adopt `ht-table` class, and fix the sticky thead background token. `LogTable` stays a pure component — `LogsPage` wraps it in `TableCard` externally.

## Prompt
1. **Build `columnFilters` map in `log-table.tsx`** — per Architecture §11 in the design doc. Three entries:
   - `level`: level dropdown select (content from current `filterFor("level")` in `log-table-header.tsx:104-119`)
   - `app`: tier toggle + app dropdown (content from current `filterFor("app")` in `log-table-header.tsx:121-155`)
   - `function`: function name text input (content from current `filterFor("function")` in `log-table-header.tsx:157-174`)

   Expose `columnFilters` from `LogTable` so `LogsPage` can pass it to `TableFooter`.

2. **Replace `HeaderCell` with `SortHeader` in `log-table-header.tsx`** — `LogTableHeader` becomes a loop mapping each visible column to a `SortHeader` instance, pulling `filterContent` and `hasActiveFilter` from the `columnFilters` map (received as a prop). Remove the `HeaderCell` component and the `filterFor()` switch. Pass `ariaLabel` from the column definition's `ariaLabel` field.

3. **Replace `LogTableFooter` with shared `TableFooter`** — in `LogsPage` (not in `LogTable`), render `TableFooter` with:
   - `count` — the existing count label (truncated vs total)
   - `columnFilters` — passed through from `LogTable` for auto-generated mobile panel
   - `onResetFilters` — the existing `resetFilters` callback
   - `extras` — the paused indicator button and `ColumnPicker` component (desktop only)

   Move search from `LogTableFooter` to `TableCard`'s `search` slot in `LogsPage`.

4. **Update `LogsPage` in `pages/logs.tsx`** — switch from `Card variant="compact"` to `TableCard`. Provide `search` (the search input), `footer` (the `TableFooter`), and `children` (the `LogTable`). `LogTable` must expose search state and filter state so `LogsPage` can wire them to `TableCard`/`TableFooter`.

5. **Adopt `ht-table` class** — in `log-table.tsx`, replace `class={styles.table}` with `class="ht-table"` on the `<table>` element. Keep the existing `<colgroup>` for column widths.

6. **Clean up `log-table.module.css`** — remove `.table` and `.table td` rules (now covered by `ht-table`). Keep `.wrapper`, `.drawerOpen`, `.tableArea`, `.scroll`, and the mobile `@media` rules that aren't covered by `ht-table`.

7. **Fix sticky thead background** — in `log-table-header.module.css`, change `.thead` `background` from `var(--bg-surface)` to `var(--bg-sunken)` to match the `ht-table thead tr` rule and prevent content showing through during scroll.

8. **Remove dead files** — delete `log-table-footer.tsx`, `log-table-footer.module.css`, and `log-table-footer.module.css.d.ts`. Remove `log-table-header.module.css` styles that are now covered by `SortHeader`'s module CSS (keep sticky positioning and any log-specific overrides).

9. **Update `pages/logs.test.tsx`** — update selectors for search location (above table, not in footer) and any footer-related assertions. The log table mock may need updating if `LogTable`'s props interface changes.

## Focus
- `LogTable` must stay a pure component — it does NOT internalize `TableCard`. The CSS grid layout in `.wrapper` (for the detail drawer) is incompatible with being nested inside `TableCard`. `LogsPage` wraps `LogTable` in `TableCard` externally.
- `LogTable` is also embedded in `overview-tab.tsx:394-407` (app detail logs section) — this embedded use must continue working without `TableCard` chrome.
- The `LogTable` component currently manages search state internally via `useSignal` in `log-table.tsx:47`. To expose search to `LogsPage` for the `TableCard` search slot, either lift the state or expose it via a callback/signal. The `useLogFilters` hook already returns `setSearch` — expose the `searchInput` signal or add `onSearchChange` + `search` props.
- `log-table-header.module.css` has `.thead` sticky positioning styles (position: sticky, top: 0, z-index) — these must be preserved even after removing other header-specific styles.
- The `ColumnPicker` component in `log-table/column-picker.tsx` imports `ColumnFilterPopover` — its import was already updated in T01. It should pass through `TableFooter`'s `extras` slot on desktop only.
- The `RENDER_CAP` constant and "showing X of Y" count logic is in `log-table-footer.tsx` — extract the count formatting to `LogsPage` or a utility before deleting the file.
- `log-table/types.ts` exports types used by other log-table files — these are NOT being deleted or moved.

## Verify
- [ ] FR#1: The log table search input is above the table content in `LogsPage`'s `TableCard` search slot (moved from footer)
- [ ] FR#2: The log table footer displays a record count (showing truncation when applicable) that updates when filters change
- [ ] FR#3: The log table `<thead>` row has `var(--bg-sunken)` background matching apps and handlers tables
- [ ] AC#1: Search input is visible above the log table without scrolling in the `LogsPage` layout
- [ ] AC#2: The log table footer shows the record count (e.g., "showing 500 of 927" or "42 entries")
- [ ] AC#3: The log table uses `ht-table` class and its header row visually matches the other two tables' header rows
