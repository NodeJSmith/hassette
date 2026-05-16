# Design: Align Table Pattern

**Date:** 2026-05-15
**Status:** approved
**Scope-mode:** hold
**Research:** /tmp/claude-mine-define-research-xTbfED/brief.md

## Problem

The three main data pages — apps, handlers, and logs — each display a table of records, but they evolved independently. The result is three visually different takes on the same pattern: different header backgrounds, different filter placement (toolbar pills vs. inline column popovers vs. footer controls), and the search input in different locations. The inconsistency is cosmetic friction — nothing is broken, but the pages don't feel like they belong to the same product.

## Goals

- All three table pages share the same five structural elements: (1) search input above the table, (2) inline column filter popovers in the header, (3) `var(--bg-sunken)` header background, (4) record count in the footer, (5) card border around the table container.
- Zero page-specific filter UI remains outside the table header — all filtering happens via column header popovers or the search bar.
- `SortHeader` is the single column header component used by all three tables — the log table's `HeaderCell` is eliminated, not kept as a parallel implementation.

## Non-Goals

- App detail page tables (overview tab handler health, recent activity, handler detail execution tables) — those are a separate effort.
- New filter types or columns not already present on each page.
- Mobile layout redesign — no ground-up rethink of mobile. On mobile, the log table currently moves filters out of column headers into a consolidated filter icon in the footer (search also in footer). Apps and handlers should adopt this same mobile pattern: filters consolidated into the footer, not inline in headers. The handlers card layout on mobile is fine to keep as-is.

## User Scenarios

### Operator: Home automation hobbyist

- **Goal:** Find, filter, and monitor records across the three table pages
- **Context:** Pulls up the UI with a question, finds the answer, closes the tab

#### Scan and filter

1. **Lands on a table page**
   - Sees: search bar above the table, data rows with sortable column headers, record count in the footer
   - Decides: whether to search, filter a column, or just scan
   - Then: interacts with the table or navigates away

2. **Filters by a column value**
   - Sees: a funnel icon on filterable column headers
   - Decides: clicks the funnel to open an inline popover with filter options
   - Then: selects a filter value; table updates immediately; a dot appears on the funnel indicating an active filter

3. **Searches for a specific record**
   - Sees: search input above the table
   - Decides: types a keyword
   - Then: table filters to matching rows; record count in footer updates

#### Monitor mode

1. **Leaves a table page open**
   - Sees: table with filters set once, data updating in real time
   - Decides: glances periodically
   - Then: notices changes via updated counts, new rows, or status changes

## Functional Requirements

- **FR#1** All three table pages display a search input above the table content.
- **FR#2** All three table pages display a record count in the table footer area.
- **FR#3** All three table pages use the same header row background color for the `<thead>` row.
- **FR#4** All three table pages use inline column filter popovers for filterable columns, activated by a funnel icon in the column header.
- **FR#5** Active column filters display a visual indicator (dot) on the funnel icon.
- **FR#6** Column filter popovers close on Escape key press or click outside.
- **FR#7** Column filter popovers position themselves using floating-ui to stay within the viewport.
- **FR#8** All three table containers have a consistent visible border.
- **FR#9** The apps page status filter (all/running/failed/stopped/disabled/blocked) appears as a column filter popover on the STATUS column header.
- **FR#10** The handlers page tier filter (All/Apps/Framework) and app filter appear as column filter popovers on the appropriate column headers.
- **FR#11** Existing sort functionality on all three tables continues to work alongside the new inline filters.

## Edge Cases

- **No filter options**: If a filter column has no options to show (e.g., zero apps loaded), the filter icon should still appear but the popover shows a meaningful empty state.
- **All filters active simultaneously**: Multiple column filters can be active at once; the funnel dot should appear on each active column independently.
- **Viewport edge**: Filter popovers near the right or bottom edge of the viewport must flip/shift to stay visible (handled by floating-ui's `flip()` and `shift()` middleware).
- **Search + column filter interaction**: Search and column filters should compose — a user can search "garage" AND filter status to "running" simultaneously, and the record count in the footer reflects the combined result.
- **Zero results**: When filters + search produce zero matches, the table shows an empty state message that names the active filter values (e.g., "No apps match status: Failed") and provides a one-click "clear filters" reset. The footer count shows "0".
- **Mobile viewport**: On mobile, all three tables consolidate their column filters into a single filter icon in the footer (matching the log table's existing mobile pattern). Inline column header filter buttons are hidden on mobile — the footer filter panel replaces them.

## Acceptance Criteria

- **AC#1** On each of the three table pages, a search input is visible above the table content and filters rows as the user types. (FR#1)
- **AC#2** On each of the three table pages, a record count is visible in a footer bar and updates when filters change. (FR#2)
- **AC#3** The `<thead>` row on all three tables has the same background color (`var(--bg-sunken)`). (FR#3)
- **AC#4** At least one column header on each page has a clickable funnel icon that opens a filter popover. (FR#4)
- **AC#5** The apps page STATUS column has a clickable funnel icon that opens a popover with status filter options; selecting a status filters the table. (FR#9)
- **AC#6** The handlers page has column filter popovers for tier and app filtering. (FR#10)
- **AC#7** All filter popovers close on Escape or click-outside. (FR#6)
- **AC#8** Active column filters show a dot indicator on the funnel icon. (FR#5)
- **AC#9** All three tables are visually contained with a consistent border. (FR#8)
- **AC#10** Sort arrows on column headers continue to function correctly alongside filter icons. (FR#11)
- **AC#11** When column filters or search produce zero results, the empty state message names the active filter values and includes a one-click reset to clear all filters. (FR#4)

## Key Constraints

- `ht-table` is updated to reflect the log table's defaults (`table-layout: fixed`, `vertical-align: top`, `overflow: hidden`, `text-overflow: ellipsis`). The log table adopts `ht-table`. All tables use `<colgroup>` for explicit column widths. Out-of-scope `ht-table` consumers without `<colgroup>` (HandlerHealthGrid and RecentActivitySection — both in `overview-tab.tsx`) are being removed in a separate PR, so temporary breakage is acceptable. Note: `overview-tab.tsx` also embeds a `LogTable` instance for app-scoped logs — that usage is unaffected because `LogTable` stays a pure component and doesn't internalize `TableCard` (see Architecture §5). ConfigTable already uses `--compact` with `table-layout: fixed` and is unaffected.
- Five shared components (`ColumnFilterPopover`, `SortHeader`, `FilterIcon`, `TableCard`, `TableFooter`) own all table structure. No page should contain its own table chrome — only data, column definitions, and filter content.
- The apps page `FilterPills` becomes popover content — the always-visible pill strip disappears. Deliberate trade-off: consistency over at-a-glance filter visibility.
- Dead code removed after migration: `TierToolbar`, `LogTableFooter`, `HeaderCell`, `FilterPills`, log table's `.table` module class.

## Dependencies and Assumptions

- `@floating-ui/dom` (`^1.7.6`) is already a project dependency — no new packages needed.
- The `ColumnFilterPopover` component in `log-table/column-filter.tsx` is already fully generic (no log-table-specific logic) and can be extracted as-is.
- The existing `useSignal` and `useSubscribe` hooks from the project's signal system are available for managing popover open/close state.

## Architecture

### Shared component inventory

Five shared components + one shared type form the unified table pattern. Each page provides its own data, column definitions, and a `columnFilters` map — the shared components handle all structure, interaction, and styling.

| Component | Location | Role |
|---|---|---|
| `ColumnFilters` type | `components/shared/table-types.ts` | `Record<string, ColumnFilter>` where `ColumnFilter = { active: boolean; label: string; content: preact.ComponentChildren }` — the single-source map each page builds. Fed to both `SortHeader` (desktop) and `TableFooter` (mobile). |
| `ColumnFilterPopover` | `components/shared/column-filter-popover/` | Floating-ui positioned popover shell. Accepts arbitrary filter content as children. |
| `SortHeader` | `components/shared/sort-header.tsx` | Single `<th>` component for all table column headers. Two independent axes (sort, filter) compose freely: sort-only, sort+filter, filter-only, or plain label. |
| `FilterIcon` | `components/shared/filter-icon.tsx` | The funnel SVG + optional active dot. Used by `SortHeader` (desktop) and `TableFooter` (mobile). Single source for the icon. |
| `TableCard` | `components/shared/table-card.tsx` | Unified table shell: search bar → scroll area → footer. All three pages use this as their table container. |
| `TableFooter` | `components/shared/table-footer.tsx` | Footer bar with record count (left), optional extras (center/right), and auto-generated mobile filter panel from `columnFilters`. Replaces `LogTableFooter`. |

### 1. Extract `ColumnFilterPopover` to shared

Move `components/shared/log-table/column-filter.tsx` and `column-filter.module.css` to `components/shared/column-filter-popover/`. A subdirectory (not a flat file) because the component has both a `.tsx` and `.module.css` — matching the project's convention for co-located component + styles. The component is already generic — accepts `open`, `onClose`, `triggerRef`, and `children`.

**Fix focus management during extraction.** The existing component uses `role="dialog"` but never moves focus into the popover on open — a WCAG 2.1 Level A failure. Before extracting to shared (where it propagates to all three pages), add: (1) on open, focus the first focusable child (or the popover container with `tabIndex={-1}`); (2) on close, restore focus to `triggerRef.current`; (3) trap Tab/Shift-Tab within the popover while open.

The filter content styles (`.heading`, `.tierGroup`, `.tierBtn`) move with the component since they are reusable across all three pages.

### 2. Create `FilterIcon`

Extract the inline funnel SVG from `log-table-header.tsx` `HeaderCell` into a tiny shared component. It currently appears in two places (header filter button and mobile footer filter button) and will appear in `SortHeader` + `TableFooter` — four potential copies without extraction.

```tsx
interface FilterIconProps { size?: number; }
export function FilterIcon({ size = 12 }: FilterIconProps) { /* funnel SVG */ }
```

### 3. Column filters map — the single-source pattern

Each page defines its filter content exactly once as a `columnFilters` map. This map is the single source of truth — it feeds both the desktop column header popovers (via `SortHeader`) and the mobile consolidated filter panel (via `TableFooter`). No page defines filter content twice.

```tsx
type ColumnFilter = { active: boolean; label: string; content: preact.ComponentChildren };
type ColumnFilters = Record<string, ColumnFilter>;

// Example: log table
const columnFilters: ColumnFilters = {
  level:    { active: level !== DEFAULT_LEVEL, label: "Level",    content: <LevelSelect ... /> },
  app:      { active: tier !== defaultTier,    label: "App",      content: <AppTierFilter ... /> },
  function: { active: fnFilter !== "",         label: "Function", content: <FnInput ... /> },
};

// Example: apps page
const columnFilters: ColumnFilters = {
  status: { active: filter !== "all", label: "Status", content: <StatusFilterList ... /> },
};

// Example: handlers page
const columnFilters: ColumnFilters = {
  kind: { active: tierFilter !== "app", label: "Type", content: <TierToggle ... /> },
  app:  { active: selectedApp !== "",   label: "App",  content: <AppDropdown ... /> },
};
```

The `label` field is used by `TableFooter` to label each filter group in the mobile panel. The `content` is the same JSX rendered in the desktop popover and the mobile panel — defined once, used in both contexts.

### 4. Extend `SortHeader` — the single column header component

Sort and filter are two independent axes that compose, not a combinatorial union. `SortHeader` keeps its existing sort props (managed or manual) and gains an orthogonal filter prop group:

```tsx
// Sort axis — unchanged, existing discriminated union
interface ManualSortProps { active: boolean; direction: "asc" | "desc"; onClick: () => void; }
interface ManagedSortProps<K> { sortKey: K; sort: SortState<K>; onSort: (s: SortState<K>) => void; }

// Filter axis — new, optional, independent of sort
interface FilterProps {
  filterContent: preact.ComponentChildren;
  hasActiveFilter: boolean;
}

// Common props — always present
interface BaseProps {
  ariaLabel?: string;
  class?: string;
  children: preact.ComponentChildren;
}
```

The two axes compose freely:
- **Sort only** (existing behavior): `<SortHeader sortKey="name" sort={sort} onSort={onSort}>name</SortHeader>`
- **Sort + filter**: `<SortHeader sortKey="status" ... filterContent={...} hasActiveFilter={...}>status</SortHeader>`
- **Filter only** (no sort props): `<SortHeader filterContent={...} hasActiveFilter={...}>type</SortHeader>`
- **Neither** (plain label): `<SortHeader>actions</SortHeader>`

When `filterContent` is provided, `SortHeader` renders an inline-flex wrapper containing the sort button (or plain label when no sort props) + filter trigger button (`FilterIcon`) + `ColumnFilterPopover`. This wrapper layout matches the existing `HeaderCell` pattern from `log-table-header.tsx`.

When no filter props are provided, `SortHeader` renders exactly as today — backward compatible.

The `ariaLabel` prop, when provided, applies `aria-label` to the `<th>`, `aria-label={`Sort by ${ariaLabel}`}` to the sort button, and `aria-label={`Filter ${ariaLabel}`}` to the filter button. This preserves the accessibility attributes currently on the log table's `HeaderCell`.

The popover open/close state uses `useSignal` + `useRef` locally within each `SortHeader` instance.

**The log table adopts `SortHeader` too.** The log table's `HeaderCell` in `log-table-header.tsx` is replaced by `SortHeader` instances. `LogTableHeader` becomes a loop that maps each visible column to a `SortHeader`, pulling `filterContent` and `hasActiveFilter` from the `columnFilters` map. The `HeaderCell` component and its duplicate sort+filter rendering logic are removed. The `filterFor()` switch in `LogTableHeader` is also removed — the `columnFilters` map is built upstream (in `LogTable` or a hook) and passed to `LogTableHeader` as a prop.

This means `SortHeader` is the single component responsible for rendering every `<th>` across all three tables. No parallel implementations.

### 5. Evolve `TableCard` — the unified table shell

`TableCard` becomes the single container for all three tables. Its layout:

```
┌─────────────────────────────┐
│ search bar                  │  ← search slot
├─────────────────────────────┤
│ table header + rows         │  ← scroll area (children)
├─────────────────────────────┤
│ count │        │ mobile flt  │  ← footer slot
└─────────────────────────────┘
```

Props:
- `search` — search input element or render prop (value, onChange, placeholder)
- `footer` — `TableFooter` element (or rendered automatically from footer-related props)
- `scrollHeight` — max height for the scroll area (existing prop)
- `children` — the `<table>` element

The existing `title`, `count`, and `controls` toolbar props are removed — there is no toolbar in the new pattern. The `Card` wrapper provides the border.

`LogTable` remains a pure table component — it does not internalize `TableCard`. Instead, `LogsPage` wraps `LogTable` in `TableCard` externally, providing the search bar and footer via `TableCard`'s slots. This preserves compatibility with embedded uses (`overview-tab.tsx` app detail logs section) where `TableCard` chrome would not belong.

### 6. Create shared `TableFooter` — replaces `LogTableFooter`

`LogTableFooter` (176 lines, heavily log-specific) is replaced by a shared `TableFooter` component that all three pages use. Props:

```tsx
interface TableFooterProps {
  count: preact.ComponentChildren;          // "10 apps", "19 handlers · 14 jobs", "showing 500 of 927"
  columnFilters?: ColumnFilters;            // same map used by SortHeader — auto-generates mobile panel
  onResetFilters?: () => void;              // "Reset to defaults" button in mobile panel
  extras?: preact.ComponentChildren;        // slot for page-specific additions (e.g., log table's paused indicator, column picker)
}
```

On desktop, `TableFooter` renders: count on the left, extras on the right.

On mobile (`useMediaQuery(BREAKPOINT_MOBILE)`), it additionally renders a `FilterIcon` button that opens a `ColumnFilterPopover`. The popover content is **auto-generated** from the `columnFilters` map: each entry becomes a labeled group (using the `label` field) containing the entry's `content` JSX, stacked vertically. If any entry has `active: true`, the `FilterIcon` shows the active dot. If `onResetFilters` is provided, a "Reset to defaults" button appears at the bottom of the panel.

This eliminates the duplication where each page would otherwise define filter content twice (once for desktop column headers, once for the mobile panel). The `columnFilters` map is the single source — `SortHeader` reads it for desktop popovers, `TableFooter` reads it for the mobile panel.

Log-table-specific features (paused indicator, column picker) pass through the `extras` slot. They are not in the shared component's core API.

### 7. Unify `ht-table` defaults

Update `styles/tables.css` `.ht-table` to reflect the log table's defaults:
- Add `table-layout: fixed` — gives predictable column widths, eliminates browser auto-distribution that causes uneven whitespace. All three tables will need explicit column widths via `<colgroup>`.
- Change `td` `vertical-align` from `middle` to `top` — better for variable-height content across all tables.
- Add `overflow: hidden` and `text-overflow: ellipsis` on `td` — prevents content blowout. These only work with `table-layout: fixed`, so the two are a package deal.

The log table adopts the `ht-table` class and removes duplicate rules from `log-table.module.css`. Apps and handlers tables add `<colgroup>` elements to define column widths (the log table already has this).

The log table header background (`var(--bg-sunken)`) comes for free from `ht-table`'s `thead tr` rule once the log table adopts the class.

Verify `ht-table th` styles (mono font, 0.04em letter-spacing) don't conflict with `log-table-header.module.css` `.th` styles (body font, 0.03em). Module CSS should win specificity — confirm during implementation.

The `ht-table--compact` variant's `table-layout: fixed` is now redundant with the base class. Remove or repurpose `--compact` to only carry its reduced padding.

### 8. Table border consistency

All three tables are wrapped in `Card` via `TableCard`. `Card` already provides `border: 1px solid var(--line-1)`. Verify this border is visually sufficient in both light and dark themes. If `--line-1` (`#E6E6E2` light / `#272A30` dark) is too subtle, consider `--line-strong` (`#D0D0CC` light / `#3A3E46` dark) — but start with `--line-1` and assess visually.

### 9. Apps page filter migration

Build a `columnFilters` map with one entry for `status` (vertical list of status options with counts as popover content). Pass it to both `SortHeader` (STATUS column gets `filterContent`) and `TableFooter` (auto-generates mobile panel). Remove `FilterPills` and `ht-table-toolbar`.

Add `<colgroup>` with explicit column widths for the apps table.

### 10. Handlers page filter migration

Build a `columnFilters` map with entries for `kind` (tier toggle) and `app` (app dropdown). Pass to `SortHeader` and `TableFooter`. Remove `TierToolbar` component and its test file.

Add `<colgroup>` with explicit column widths for the handlers table.

### 11. Log table migration

- Build the `columnFilters` map inside `LogTable` (which already owns the filter state via `useLogFilters`) with entries for `level`, `app`, and `function`. This replaces the `filterFor()` switch currently in `LogTableHeader`. `LogsPage` passes `columnFilters` to both `LogTableHeader` (via `LogTable`) and `TableFooter` (via `TableCard`).
- Replace `log-table-header.tsx`'s `HeaderCell` with `SortHeader` instances. `LogTableHeader` becomes a loop: for each visible column, render `SortHeader` pulling `filterContent` and `hasActiveFilter` from the `columnFilters` map.
- Replace `LogTableFooter` with shared `TableFooter`, passing `columnFilters` (auto-generates mobile panel) and paused indicator + column picker via `extras`.
- Move search from footer to `TableCard`'s search slot.
- Replace `.table` module class with `ht-table` global class. Keep `<colgroup>` for column widths.
- Remove `log-table-header.module.css` styles that are now covered by `SortHeader`'s module CSS. Retain only styles unique to the log table (e.g., sticky positioning).
- Update the `.thead` sticky rule in `log-table-header.module.css` from `background: var(--bg-surface)` to `background: var(--bg-sunken)` — the sticky `<thead>` element needs to match the `ht-table thead tr` background to prevent content showing through during scroll.

### 12. Dead code removal

After migration, remove:
- `components/shared/tier-toolbar.tsx` + test file
- `components/shared/log-table/column-filter.tsx` + `.module.css` (moved to shared)
- `components/shared/log-table/log-table-footer.tsx` + `.module.css` (replaced by shared `TableFooter`)
- `components/shared/log-table/log-table-header.tsx`'s `HeaderCell` component (replaced by `SortHeader`)
- `FilterPills` inline component in `pages/apps.tsx` (becomes popover content)
- `ht-table--compact`'s `table-layout: fixed` rule (now in base class)
- `ht-table-toolbar` and related styles (`.ht-table-toolbar__title`, `.ht-table-toolbar__heading`, `.ht-table-toolbar__note`, `.ht-table-toolbar__controls`) in `tables.css` — no consumers remain after apps and handlers migrate

### 13. Test updates

- `apps.test.tsx` — update selectors for search location and filter interaction (popover instead of pills)
- `handlers.test.tsx` — update selectors for search and filter interaction (popover instead of toolbar)
- `tier-toolbar.test.tsx` — remove (component deleted)
- `log-table.test.tsx` — update for `SortHeader` usage, search location change, `TableFooter` replacement
- `sort-header.test.tsx` — add tests for `filterContent`, `hasActiveFilter`, `ariaLabel` props and the four composition cases (sort-only, sort+filter, filter-only, neither)
- Add tests for shared `TableFooter` (count display, mobile filter panel open/close, extras slot)
- Add tests for shared `FilterIcon` (renders SVG, shows dot when active)
- Add tests for `ColumnFilterPopover` focus management (focus-on-open, focus-restore-on-close, Tab trap)

## Convention Examples

### Column filter popover pattern

**Source:** `components/shared/log-table/column-filter.tsx` (pre-extraction location)

```tsx
export function ColumnFilterPopover({ open, onClose, triggerRef, children }: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !triggerRef.current || !popoverRef.current) return;
    const cleanup = autoUpdate(trigger, popover, () => {
      void computePosition(trigger, popover, {
        strategy: "fixed",
        placement: "bottom-start",
        middleware: [offset(4), flip(), shift({ padding: 8 })],
      }).then(({ x, y }) => { /* position */ });
    });
    return cleanup;
  }, [open, triggerRef]);

  if (!open) return null;
  return <div ref={popoverRef} class={styles.popover}>{children}</div>;
}
```

### HeaderCell — the pattern SortHeader absorbs (being replaced)

**Source:** `components/shared/log-table/log-table-header.tsx` (being replaced)

This is the reference implementation for sort+filter in a single `<th>`. `SortHeader` absorbs this pattern — the inline-flex wrapper, sort button, filter trigger button with `FilterIcon`, `ColumnFilterPopover`, and active dot. After migration, `HeaderCell` is deleted.

```tsx
function HeaderCell({ columnId, sortConfig, onSort, hasActiveFilter, filterContent }: HeaderCellProps) {
  const filterOpen = useSignal(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  return (
    <th scope="col" class={clsx(styles.th, col.mono && styles.mono)}>
      <div class={styles.headerInner}>
        {col.sortKey ? (
          <button class={clsx(styles.sortBtn, isActive && styles.sortActive)} onClick={() => onSort(col.sortKey!)}>
            {displayLabel}
            {isActive && <span class={styles.sortArrow}>{direction === "asc" ? " ↑" : " ↓"}</span>}
          </button>
        ) : <span>{displayLabel}</span>}
        {col.filterable && filterContent && (
          <>
            <button ref={triggerRef} class={clsx(styles.filterBtn, hasActiveFilter && styles.filterActive)}
              onClick={() => { filterOpen.value = !filterOpen.value; }}>
              <FilterIcon />
              {hasActiveFilter && <span class={styles.filterDot} />}
            </button>
            <ColumnFilterPopover open={filterOpen.value} onClose={() => { filterOpen.value = false; }} triggerRef={triggerRef}>
              {filterContent}
            </ColumnFilterPopover>
          </>
        )}
      </div>
    </th>
  );
}
```

### SortHeader — current API (to be extended)

**Source:** `components/shared/sort-header.tsx` (current, pre-extension)

The existing sort-only component. Gets an orthogonal `filterContent` + `hasActiveFilter` prop group and an `ariaLabel` prop added. Backward compatible — existing callers without filter props continue to work unchanged.

```tsx
export function SortHeader<K extends string = string>(props: Props<K>) {
  const arrow = active ? (direction === "asc" ? " ↑" : " ↓") : "";
  return (
    <th scope="col" class={className} aria-sort={ariaSortValue}>
      <button type="button" class={clsx(styles.sortHeader, active && styles.active)} onClick={onClick}>
        {children}<span aria-hidden="true">{arrow}</span>
      </button>
    </th>
  );
}
```

### Footer count display

**Source:** `components/shared/log-table/log-table-footer.module.css` (being replaced by shared `TableFooter`)

```css
.footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-3);
  border-top: 1px solid var(--line-2);
  background: var(--bg-surface);
}

.count {
  font-family: var(--font-body);
  font-size: var(--fs-micro);
  color: var(--ink-3);
  white-space: nowrap;
}
```

### Card container border

**Source:** `components/shared/card.module.css`

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--line-1);
  border-top: 1px solid var(--line-2);
  border-radius: var(--r-md);
  padding: var(--sp-5);
}
```

## Alternatives Considered

### Keep toolbar filters, just align visually

Keep the apps filter pills and handlers tier toolbar above the table, but standardize their styling and add a search bar + footer count. This would be less disruptive but doesn't achieve the "same interaction pattern" goal — users would still encounter three different filter mechanisms.

**Rejected because:** The inline column filter pattern is strictly better for consistency and scales to more columns without growing the toolbar. The log table already proves it works.

### Keep log table's parallel implementations

Keep `HeaderCell` alongside `SortHeader`, keep `LogTableFooter` alongside a new shared footer, keep the log table's own `.table` class alongside `ht-table`. Touch only apps and handlers pages.

**Rejected because:** This leaves three parallel implementations of the same patterns (sort+filter header, footer, table styling). Every future change to table behavior would need to be applied in multiple places. The whole point of this work is unification — half-unifying creates maintenance burden without eliminating inconsistency.

## Test Strategy

- **Unit tests**: Extend `SortHeader` tests to cover the new `filterContent` and `hasActiveFilter` props — verify popover opens/closes, filter dot appears, backward compatibility when props are omitted.
- **Integration tests**: Update apps page tests and handlers page tests to exercise the new inline column filter interaction (click funnel → popover opens → select filter → table updates). Update search input selectors to reflect the new above-table position.
- **Cleanup**: Remove `TierToolbar` tests after the component is deleted.
- **Visual verification**: Screenshot all three pages (desktop, both themes) before and after to confirm visual alignment.

## Documentation Updates

- Update `design/context.md` Component Inventory sections for Apps Page, Handlers Page, and Logs Page to reflect the new table structure (search above, inline column filters, footer count). Update the Shared Components section to document `ColumnFilterPopover`, `FilterIcon`, `TableFooter`, and the `ColumnFilters` type.

## Impact

**Files modified:**
- `components/shared/sort-header.tsx` + `.module.css` — extended with filter support, absorbs `HeaderCell`'s sort+filter rendering
- `components/shared/log-table/log-table-header.tsx` — replace `HeaderCell` with `SortHeader` instances; remove `filterFor()` switch (filter content now comes from `columnFilters` prop); becomes a loop mapping visible columns to `SortHeader`
- `components/shared/log-table/log-table.tsx` — adopt `ht-table` class, build `columnFilters` map, expose it for `LogsPage` to pass to `TableCard`/`TableFooter`
- `components/shared/log-table/log-table.module.css` — remove rules now covered by `ht-table` (keep only log-specific overrides like sticky positioning)
- `components/shared/table-card.tsx` — evolve from toolbar+scroll to search+scroll+footer shell
- `styles/tables.css` — update `ht-table` defaults (table-layout, vertical-align, overflow, text-overflow); clean up `--compact` redundancy; remove `ht-table-toolbar` styles
- `pages/apps.tsx` + `.module.css` — use `TableCard` with `SortHeader` filters, add `<colgroup>`, remove toolbar
- `pages/handlers.tsx` + `.module.css` — use `TableCard` with `SortHeader` filters, add `<colgroup>`, remove toolbar
- `pages/logs.tsx` — switch from `Card` to `TableCard`

**Files created:**
- `components/shared/table-types.ts` — `ColumnFilter` and `ColumnFilters` types
- `components/shared/column-filter-popover/index.tsx` + `.module.css` — extracted from log-table, with focus management fix
- `components/shared/filter-icon.tsx` — funnel SVG + active dot
- `components/shared/table-footer.tsx` + `.module.css` — shared footer (count + mobile filter panel + extras slot)

**Files removed:**
- `components/shared/tier-toolbar.tsx` + test file — decomposed into column filter popovers
- `components/shared/log-table/column-filter.tsx` + `.module.css` — moved to shared
- `components/shared/log-table/log-table-footer.tsx` + `.module.css` — replaced by shared `TableFooter`

<!-- Gap check 2026-05-15: 1 gap found — column-picker.tsx imports ColumnFilterPopover (file:line column-picker.tsx) → T01 Prompt item 2 updates its import path -->

**Blast radius:** Medium-high — three pages change their table interaction pattern, shared components are restructured, and `ht-table` defaults change. However, data fetching, state management, and routing are untouched. The `SortHeader` extension is backward-compatible, so app detail page tables (which also use `SortHeader`) get filter support for free without breaking existing sort-only usage.

## Open Questions

None — all decisions resolved during discovery.
