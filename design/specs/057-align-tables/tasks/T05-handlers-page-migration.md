---
task_id: "T05"
title: "Migrate handlers page to unified table pattern"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#2", "FR#3", "FR#10", "AC#2", "AC#3", "AC#6"]
---

## Summary
Migrate the handlers page to the unified table pattern: build a `columnFilters` map for tier and app filtering, replace `TierToolbar` with `SortHeader` column filters, move search above the table via `TableCard`, add `TableFooter` with record count, add `<colgroup>`, and remove the `TierToolbar` component and its test file.

## Prompt
1. **Build `columnFilters` map in `pages/handlers.tsx`** — two entries per Architecture §10 in the design doc:
   - `kind`: tier filter (All/Apps/Framework toggle) — mark `active` when `tierFilter !== "app"` (default is "app")
   - `app`: app dropdown — mark `active` when `selectedApp !== ""`

   The filter content for `kind` is the tier toggle buttons (reuse the tier toggle UI from `TierToolbar`). The filter content for `app` is the app dropdown select (reuse the app select from `TierToolbar`).

2. **Replace `TierToolbar` with `SortHeader` filters** — on the TYPE column's `SortHeader`, pass `filterContent` from `columnFilters.kind`. On the APP column's `SortHeader`, pass `filterContent` from `columnFilters.app`. Both get `hasActiveFilter` from their respective `columnFilters` entries.

3. **Update `TableCard` usage** — replace the old `count`/`controls` props with:
   - `search` — the search input (currently inside `TierToolbar`)
   - `footer` — a `TableFooter` with `count` showing handler/job counts (`pluralize(..., "handler") + " · " + pluralize(..., "job")`), `columnFilters`, and `onResetFilters`

4. **Add `<colgroup>`** — define explicit column widths for the handlers table's 10 columns (TYPE, APP, NAME, TRIGGER, RUNS, FAILED, TIMED OUT, ERROR RATE, AVG, NEXT RUN). Use percentage-based widths.

5. **Remove `TierToolbar`** — delete `components/shared/tier-toolbar.tsx`, `tier-toolbar.module.css`, `tier-toolbar.module.css.d.ts`, and `tier-toolbar.test.tsx`.

6. **Update `pages/handlers.test.tsx`** — update selectors: search is above the table, tier/app filters are via funnel icons on column headers. Remove any tests that reference `TierToolbar` testids.

7. **Clean up `pages/handlers.module.css`** — remove any toolbar-related styles no longer needed.

## Focus
- `TierToolbar` at `components/shared/tier-toolbar.tsx` (73 lines) combines tier toggle + app dropdown + search. The tier toggle and app dropdown become popover content; the search moves to `TableCard`.
- `TierToolbar` has a test file at `tier-toolbar.test.tsx` (197 lines) — delete it entirely.
- The handlers table currently has `class="ht-table ${styles.handlersTable}"` at line 365. Keep this.
- `handlers.module.css` has `.handlersTable td` with `white-space: nowrap` and `max-width: 200px` — verify these still work with `table-layout: fixed` and `<colgroup>`.
- The mobile card layout (`MobileCard` component, lines 138–149) is out of scope — it renders instead of the table on mobile, so table changes don't affect it.
- `handlers.tsx` defines a local `TierFilter` type (line 80) — keep it; it's used for the filter state regardless of UI.

## Verify
- [ ] FR#2: The handlers page footer displays a record count that updates when filters change
- [ ] FR#3: The handlers table `<thead>` row has `var(--bg-sunken)` background matching apps and log tables
- [ ] FR#10: The TYPE column header has a funnel icon opening a popover with tier filter options; the APP column header has a funnel icon opening a popover with app filter dropdown
- [ ] AC#2: The handlers table footer shows "N handlers · M jobs" count
- [ ] AC#3: The handlers table `<thead>` row background is `var(--bg-sunken)` matching the other two tables
- [ ] AC#6: Active tier or app filters show a dot indicator on their respective funnel icons
