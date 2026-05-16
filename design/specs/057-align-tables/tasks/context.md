# Context: Align Table Pattern

## Problem & Motivation
The three top-level table pages (apps, handlers, logs) evolved independently and now have visually different table patterns — different header backgrounds, different filter placement (toolbar pills vs. inline column popovers vs. footer controls), and search inputs in different locations. The inconsistency is cosmetic friction that makes the pages feel like they don't belong to the same product. This work unifies them into a single shared table pattern with five shared components and one shared type, eliminating parallel implementations.

## Visual Artifacts
None.

## Key Decisions
1. The log table's inline column filter pattern is the target — apps/handlers adopt it, not the other way around.
2. Sort and filter are two independent axes on `SortHeader` that compose freely (sort-only, sort+filter, filter-only, plain label) — not a combinatorial union of 4 variant types.
3. Each page builds a `columnFilters` map exactly once — this single map feeds both desktop column header popovers (via `SortHeader`) and the mobile consolidated filter panel (via `TableFooter`). No filter content is defined twice.
4. `LogTable` stays a pure table component — `LogsPage` wraps it in `TableCard` externally. This preserves embedded uses in `overview-tab.tsx`.
5. `ht-table` CSS defaults are updated to match the log table (`table-layout: fixed`, `vertical-align: top`, `overflow: hidden`, `text-overflow: ellipsis`). All tables use `<colgroup>` for explicit column widths.
6. `ColumnFilterPopover` gets focus management fixed during extraction (focus-on-open, focus-restore, Tab trap) — a pre-existing WCAG 2.1 Level A gap.
7. Out-of-scope `ht-table` consumers (HandlerHealthGrid, RecentActivitySection) are being removed in a separate PR, so temporary breakage is acceptable.
8. FilterPills removal loses at-a-glance status counts — accepted trade-off. StatsStrip provides ambient failure awareness.

## Constraints & Anti-Patterns
- Do NOT have `LogTable` internalize `TableCard` — the caller (`LogsPage`) provides the shell.
- Do NOT create a `sortable` prop on `SortHeader` — filter-only is achieved by omitting sort props entirely.
- Do NOT define filter content twice (once for desktop, once for mobile) — the `columnFilters` map is the single source.
- Do NOT add `ht-table` class to the log table without first updating `ht-table` defaults — the current defaults conflict.
- Do NOT leave `ht-table-toolbar` styles in `tables.css` — no consumers remain after migration.
- App detail page tables are out of scope — do not modify `overview-tab.tsx` tables or `execution-table.tsx`.
- Empty state when filters produce zero results MUST name the active filter values and provide a one-click reset.
- All CSS values must reference design tokens from `tokens.css` — no raw hex, pixel, or spacing values.

## Design Doc References
- `## Architecture` — shared component inventory, per-section implementation details
- `## Key Constraints` — ht-table unification, shared component ownership, dead code list
- `## Edge Cases` — filter composition, zero results, mobile viewport, viewport edge
- `## Acceptance Criteria` — AC#1–AC#11 verification criteria

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
