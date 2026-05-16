---
task_id: "T03"
title: "Evolve TableCard to unified table shell"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#8", "AC#1", "AC#9"]
---

## Summary
Evolve `TableCard` from its current toolbar+scroll layout to the unified table shell: search bar above, scroll area in the middle, footer below. Remove the old toolbar props (`title`, `count`, `controls`). The `Card` wrapper continues providing the border. All three pages will use this as their table container.

## Prompt
1. **Update `components/shared/table-card.tsx`** — per Architecture §5 in the design doc. Replace the current props with:
   - `search` — search input element (the caller provides the `<input>` with `ht-search` class)
   - `footer` — `TableFooter` element
   - `scrollHeight` — max height for the scroll area (existing prop, keep as-is)
   - `class` — optional class name (existing prop, keep as-is)
   - `containerRef` — optional ref (existing prop, keep as-is)
   - `children` — the `<table>` element

   Layout: search bar (with `padding: var(--sp-2) var(--sp-3)` and `border-bottom: 1px solid var(--line-2)`) above the scroll area, footer below. The `Card variant="compact"` wrapper stays for the border.

   Remove `title`, `count`, and `controls` props and the `ht-table-toolbar` rendering. These are no longer used.

2. **Verify border visibility** — the `Card` component at `components/shared/card.module.css` provides `border: 1px solid var(--line-1)`. Confirm this renders visibly in both light and dark themes. If too subtle, note it — the border token can be adjusted in a follow-up visual QA pass.

3. **Do NOT update page callers yet** — apps, handlers, and logs pages will be migrated in T04, T05, T06. This task only changes the component API. Since apps and handlers currently pass `count` and `controls`, they will temporarily break after this change — coordinate with T04/T05 to land together or stub the old props during transition.

## Focus
- `table-card.tsx` is currently 34 lines. It imports `Card` from `./card` and renders `ht-table-toolbar` markup. The toolbar markup and its class references are removed entirely.
- The `ht-search` global class is defined in `styles/utilities.css` (around line 166) — callers use it on the `<input>` they pass to the `search` prop.
- The search bar container should use the same `padding` and `border-bottom` tokens as the existing `ht-table-toolbar` spacing for visual consistency.
- `TableCard` is imported by `pages/apps.tsx` and `pages/handlers.tsx`. Both will need updating in T04/T05.

## Verify
- [ ] FR#1: TableCard renders a search input area above the scroll container when `search` prop is provided
- [ ] FR#8: TableCard is wrapped in a Card component providing a visible border via `--line-1`
- [ ] AC#1: The search input area is positioned above the table content within the card container
- [ ] AC#9: The card border is visible around the table container
