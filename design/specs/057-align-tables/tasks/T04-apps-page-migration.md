---
task_id: "T04"
title: "Migrate apps page to unified table pattern"
status: "done"
depends_on: ["T02", "T03"]
implements: ["FR#2", "FR#3", "FR#9", "AC#2", "AC#3", "AC#5", "AC#11"]
---

## Summary
Migrate the apps page to the unified table pattern: build a `columnFilters` map for status filtering, replace `FilterPills` and toolbar with `SortHeader` column filters, move search above the table via `TableCard`, add `TableFooter` with record count, and add `<colgroup>` for explicit column widths.

## Prompt
1. **Build `columnFilters` map in `pages/apps.tsx`** — one entry for `status` per Architecture §9 in the design doc. The filter content is a vertical list of status options (all/running/failed/stopped/disabled/blocked) with per-status counts, reusing the existing status data from `statusCounts`. Each option shows the `StatusShape` icon and count. Mark `active` when `filter !== "all"`.

2. **Replace `FilterPills` with `SortHeader` filter** — on the STATUS column's `SortHeader`, pass `filterContent` from `columnFilters.status.content` and `hasActiveFilter` from `columnFilters.status.active`. Remove the `FilterPills` component entirely (lines 76–106).

3. **Update `TableCard` usage** — replace the old `count`/`controls` props with:
   - `search` — the existing search `<input>` (move from controls to search prop)
   - `footer` — a `TableFooter` with `count={pluralize(filtered.length, "app")}`, `columnFilters`, and `onResetFilters` that clears the status filter

4. **Add `<colgroup>`** — define explicit column widths for the apps table's 6 columns (APP, STATUS, LAST ERROR, RUNS, LAST FIRED, ACTIONS). Use percentage-based widths that match the current visual layout.

5. **Update empty state** — when filters produce zero results, the empty state message must name the active filter (e.g., "No apps match status: failed") and provide a one-click "clear filters" reset. The existing clear-filters logic at `apps.tsx:329-333` should be adapted.

6. **Update `pages/apps.test.tsx`** — update selectors: search input is now above the table (in TableCard's search slot), filter interaction is via funnel icon on STATUS column header opening a popover. Remove tests for `FilterPills` (`data-testid="apps-filter-pills"`). Add tests for the new column filter interaction.

7. **Clean up `pages/apps.module.css`** — remove `.filters`, `.filterPill`, `.filterPillActive`, `.filterPillCount` and any other toolbar-related styles that are no longer used.

## Focus
- `FilterPills` is defined inline in `apps.tsx` (lines 76–106) — not a shared component. Just delete it.
- The `FILTER_OPTIONS` and `FILTER_TONES` constants at the top of `apps.tsx` (lines 31–40) should be preserved — they're used for the filter logic and can be reused in the popover content.
- The apps table currently has `class="ht-table ${styles.appsTable}"` at line 336. Keep this — `ht-table` now provides `table-layout: fixed` so the `<colgroup>` will control widths.
- `apps.module.css` has `.appsTable thead th` with `letter-spacing: 0.08em` override — verify this still works with `SortHeader`'s rendering.
- The `SortHeader` import already exists in `apps.tsx` (line 23). Just add filter props to the STATUS column's `SortHeader`.

## Verify
- [ ] FR#2: The apps page footer displays a record count that updates when the status filter or search changes
- [ ] FR#3: The apps table `<thead>` row has `var(--bg-sunken)` background (inherited from `ht-table`)
- [ ] FR#9: The STATUS column header has a clickable funnel icon that opens a popover with status filter options including counts; selecting a status filters the table
- [ ] AC#2: The apps page footer shows the filtered app count (e.g., "3 apps")
- [ ] AC#3: The apps table `<thead>` row background is `var(--bg-sunken)` matching the other two tables
- [ ] AC#5: Clicking the STATUS column funnel opens a popover; selecting "failed" filters to only failed apps; selecting "all" shows all apps
- [ ] AC#11: When the status filter produces zero results, the empty state names the filter value and provides a reset button
