---
task_id: "T03"
title: "Integrate card grid into overview tab"
status: "planned"
depends_on: ["T02"]
implements: ["FR#6", "FR#7", "FR#8", "FR#9", "AC#1", "AC#5", "AC#6", "AC#7", "AC#10"]
---

## Summary

Replace the `HandlerHealthGrid` table markup in `overview-tab.tsx` with a CSS grid of `HandlerHealthCard` components. Add a scroll wrapper that caps the grid at ~3 visible rows. Remove the now-unused table-related CSS from `overview-tab.module.css`. Update `overview-tab.test.tsx` to verify the card grid renders correctly — test the grid container behavior (responsive columns, scroll, empty state, sort order), not the individual card content (that's covered in T02).

## Prompt

### Update `frontend/src/components/app-detail/overview-tab.tsx`

1. **Import** `HandlerHealthCard` from `./handler-health-card`.

2. **Replace the `HandlerHealthGrid` component body.** Remove the `<table>` + `<thead>` + `<tbody>` markup and the `HealthGridRow` component. Replace with:
   - A scroll wrapper `<div>` with `class={styles.healthGridScroll}`.
   - Inside it, a grid container `<div>` with `class={styles.healthGrid}`.
   - Inside the grid, map over `sorted` items rendering `<HandlerHealthCard>` for each.
   - Keep the `EmptyState` fallback for zero items — render it outside the scroll wrapper.

3. **Remove `HealthGridRow`** — both the component function and its `HealthGridRowProps` interface. The `HandlerHealthCard` component replaces it entirely.

4. **Keep all existing helper functions** (`isFailing`, `itemRunCount`, `sortedByFailingFirst`, `itemErrorType`, `itemErrorMessage`, `itemKindChip`, `handlerPath`) — they are used by ErrorSpotlight and/or exported for the card component (as set up in T02).

5. **Keep the `useMemo` call** for `sortedByFailingFirst(items)` — it feeds the card grid.

6. **Section structure stays the same:** `<section>` with `data-testid="overview-health-grid"` and `<h3 class="ht-section-label">handler health</h3>`.

### Update `frontend/src/components/app-detail/overview-tab.module.css`

1. **Remove** these classes (they belong to the old table): `.healthTable`, `.healthRow`, `.healthRowFailing`, `.healthRowName`, `.healthRowLink`, `.healthRowCount`, `.healthRowError`, `.colDot`.

2. **Add** new grid classes:

   ```css
   .healthGridScroll {
     max-height: calc(3 * 140px + 2 * var(--sp-3));
     overflow-y: auto;
   }

   .healthGrid {
     display: grid;
     grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
     gap: var(--sp-3);
   }
   ```

   The `max-height` estimate: ~140px per card row (tallest case: failing card with error message + 2 stat rows) × 3 rows + 2 gaps. Adjust after visual verification if needed — the exact value should look right with real data.

3. **Responsive:** The CSS grid with `auto-fill` handles responsiveness naturally. At `<280px` container width (mobile), it collapses to a single column automatically. No media query needed for the grid itself.

### Update `frontend/src/components/app-detail/overview-tab.test.tsx`

Update tests that reference the old table structure:

1. **Change selectors** from `overview-health-row-*` to `overview-health-card-*` (matching the new `data-testid` pattern from T02).

2. **Update assertions** that checked for `<table>`, `<tr>`, `<td>` elements — the grid uses `<div>` elements now.

3. **Add/update these test cases:**
   - Grid renders correct number of cards matching total handler count
   - Failing handlers appear before healthy handlers in DOM order (sort verification)
   - Empty state renders when no handlers exist (existing test, verify it still passes)
   - Within each group (failing, healthy), cards are ordered by descending run count
   - Grid container has the scroll wrapper class applied

4. **Do NOT duplicate** individual card rendering tests — those are in `handler-health-card.test.tsx` from T02.

## Focus

- **overview-tab.tsx structure:** The file has 4 sections: ErrorSpotlight, HandlerHealthGrid, RecentActivitySection, RecentLogsSection. Only HandlerHealthGrid changes. The `OverviewTab` export at the bottom wires them together — that stays the same.
- **Scroll max-height:** The `calc(3 * 140px + 2 * var(--sp-3))` is an estimate. If cards turn out shorter or taller in practice, this value needs adjustment. The user will verify visually on real data via SSH tunnel.
- **Existing test file:** `overview-tab.test.tsx` is ~560 lines. Many tests target ErrorSpotlight and activity sections — those must not be touched. Only tests referencing `health-row`, `health-grid`, or table elements need updating.
- **CSS cleanup:** Remove only the health-table classes listed above. The spotlight styles (`.spotlight*`), activity styles (`.activity*`), and log styles (`.logScroll`, `.emptyInline`) must remain — they belong to untouched sections.
- **`data-testid` on the section:** Keep `data-testid="overview-health-grid"` on the `<section>` element (other tests and the ErrorSpotlight reference it).

## Verify

- [ ] FR#6: The card grid displays 2-3 cards per row at desktop widths (≥768px) and collapses to 1 column on mobile (<768px) via CSS grid auto-fill
- [ ] FR#7: When the grid exceeds 3 rows of cards, the section scrolls vertically — scroll wrapper has `max-height` and `overflow-y: auto`
- [ ] FR#8: When no handlers exist, the EmptyState component renders with the existing message
- [ ] FR#9: Cards are sorted with failing handlers first, then by descending run count (using existing `sortedByFailingFirst`)
- [ ] AC#1: The handler health section renders a grid of `HandlerHealthCard` components — no `<table>` or `<tr>` elements remain
- [ ] AC#5: Grid uses `repeat(auto-fill, minmax(280px, 1fr))` producing 2-3 columns on desktop and 1 on mobile
- [ ] AC#6: Scroll wrapper has `max-height` constraint allowing ~3 rows visible with vertical scroll for overflow
- [ ] AC#7: EmptyState renders correctly when `items.length === 0`
- [ ] AC#10: DOM order of cards matches failing-first, then descending run count
