---
task_id: "T02"
title: "Extend SortHeader with filter support"
status: "done"
depends_on: ["T01"]
implements: ["FR#4", "FR#11", "AC#4", "AC#8", "AC#10"]
---

## Summary
Extend `SortHeader` to support an orthogonal filter axis alongside its existing sort axis. Sort and filter compose independently: sort-only, sort+filter, filter-only, or plain label. This is the single column header component for all three tables. Existing callers (apps, handlers, app detail tables) continue working unchanged — the extension is backward compatible.

## Prompt
1. **Extend `components/shared/sort-header.tsx`** — add the filter prop group per Architecture §4 in the design doc. The existing `ManualProps | ManagedProps<K>` discriminated union stays unchanged. Add an orthogonal `FilterProps` interface with `filterContent` and `hasActiveFilter`. Add `ariaLabel` to `BaseProps`.

   When `filterContent` is provided, render an inline-flex wrapper containing: the sort button (or plain label when no sort props) + filter trigger button using `FilterIcon` from `components/shared/filter-icon.tsx` + `ColumnFilterPopover` from `components/shared/column-filter-popover/`. The wrapper layout matches the existing `HeaderCell` pattern from `log-table-header.tsx`.

   When `ariaLabel` is provided, apply it to the `<th>`, sort button (`Sort by ${ariaLabel}`), and filter button (`Filter ${ariaLabel}`).

   The popover open/close state uses `useSignal` + `useRef` locally within each instance.

2. **Update `components/shared/sort-header.module.css`** — add styles for the inline-flex wrapper, filter button, filter dot indicator, and filter-active state. Reference the existing styles in `log-table-header.module.css` (`.headerInner`, `.filterBtn`, `.filterActive`, `.filterDot`) as the source patterns. Use design tokens only.

3. **Verify backward compatibility** — the existing callers in `pages/apps.tsx`, `pages/handlers.tsx`, and any app detail tables must compile and render identically without changes. The four composition cases must all work: sort-only (existing), sort+filter, filter-only, neither (plain label).

4. **Write tests** — create `components/shared/sort-header.test.tsx`. Test all four composition cases: sort-only renders sort button without filter icon; sort+filter renders both sort button and filter icon with popover; filter-only renders plain label with filter icon; neither renders plain label only. Test `ariaLabel` prop applies to th/sort/filter buttons. Test `hasActiveFilter` shows the dot indicator. Test popover opens/closes. Use Vitest + @testing-library/preact.

## Focus
- The existing `SortHeader` has two API shapes (`ManualProps` and `ManagedProps<K>`) via a discriminated union at `sort-header.tsx:33`. The filter props are additive and orthogonal — they do NOT create new union variants.
- `SortHeader` currently has NO test file — this task creates it from scratch.
- The `SortState` type is exported from `sort-header.tsx` and imported by `pages/handlers.tsx` and `utils/app-data.ts` — preserve this export.
- `sort-header.module.css` currently has `.sortHeader`, `.active` classes. The new filter-related classes (`.headerInner`, `.filterBtn`, `.filterActive`, `.filterDot`) should follow the same naming convention.
- The inline-flex wrapper must be added only when `filterContent` is present — sort-only rendering should not change DOM structure to avoid visual regressions in existing callers.

## Verify
- [ ] FR#4: SortHeader renders a clickable funnel icon when `filterContent` is provided, opening a `ColumnFilterPopover`
- [ ] FR#11: Sort buttons continue to show ascending/descending arrows and trigger sort callbacks when filter props are also present
- [ ] AC#4: The filter-only case (no sort props, filterContent provided) renders a plain label with only the filter icon
- [ ] AC#8: When `hasActiveFilter` is true, a dot indicator is visible on the funnel icon
- [ ] AC#10: Sort arrows on column headers function correctly alongside filter icons in the sort+filter case
