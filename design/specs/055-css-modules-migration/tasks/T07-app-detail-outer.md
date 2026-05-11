---
task_id: "T07"
title: "Migrate app-detail outer shell and tab components"
status: "planned"
depends_on: ["T06"]
implements: ["FR#1", "FR#5", "FR#7", "FR#11", "FR#12", "FR#13", "AC#2", "AC#4", "AC#5", "AC#6", "AC#11"]
---

## Summary
Migrate the app-detail page and its primary tab components: the app-detail page itself (instance grid, tab navigation), handlers-tab (master-detail layout, tab strip), and overview-tab. These form the outer container that the detail-pane components (T08) render within. The tab strip styles are shared between handlers-tab and overview-tab — create a shared `tabs.module.css` if needed, or let the canonical owner (handlers-tab) own them.

## Prompt
**Components:**

1. **`app-detail.tsx`** (`frontend/src/pages/app-detail.tsx`) — the page component.
   - Classes: `.ht-tab-*` (tab navigation), `.ht-instance-grid*`, `.ht-instance-card*`, `.ht-instance-switcher*`
   - `.ht-tab-btn` has a responsive override in the labeled 900px block — move it
   - E2e: `test_app_detail.py` (2 refs), `test_url_routing.py` (3 refs)
   - Unit test: `app-detail.test.tsx`

2. **`handlers-tab.tsx`** (`frontend/src/components/app-detail/handlers-tab.tsx`)
   - Classes: `.ht-master-detail*`, `.ht-detail-pane*`, `.ht-detail-stats-row*`, `.ht-chip-row`
   - Dynamic class: `.ht-detail-stats-row__value--${cell.tone}` — create explicit modifier classes in module
   - Dynamic class: `.ht-chip--kind-${listenerKind}` — `ht-chip` is global, `--kind-*` modifiers stay global too
   - Has extensive responsive overrides in 768px block
   - Unit test: `handlers-tab.test.tsx` — heavy with `.ht-detail-stats-row__cell`, `.ht-detail-stats-row__value--err`/`--warn` queries

3. **`overview-tab.tsx`** (`frontend/src/components/app-detail/overview-tab.tsx`)
   - Classes: `.ht-overview-*`
   - Uses `ht-log-level-badge` — this moved to `log-table.module.css` per adjudication table. Since overview-tab renders `<LogTable>` component, the badge is encapsulated — no change needed in overview-tab.
   - Unit test: `overview-tab.test.tsx`

**Tab strip ownership decision**: If `.ht-tab-strip` and `.ht-tab-btn` are rendered only in `app-detail.tsx`, they belong in `app-detail.module.css`. Grep to confirm before creating a separate shared module.

**After all 3 components:**
Run verification baseline. Test all 4 app-detail tabs manually (overview, handlers, code, config).

## Focus
- `handlers-tab.tsx` is the most complex component in this batch — ~400 lines, extensive CSS, dynamic classes, state modifiers.
- `handlers-tab.test.tsx` has `.ht-detail-stats-row__cell` and `.ht-detail-stats-row__value--err`/`--warn` queries at lines 262, 339, 340 — migrate to `data-testid`.
- The tab strip (`ht-tab-btn`) 900px responsive override enforces touch-target sizing — confirm the module's `@media` rule applies correctly.
- `overview-tab.tsx` references `ht-log-level-badge` — per the adjudication table, this class moved to `log-table.module.css` in T04. The `<LogTable>` component encapsulates it, so overview-tab doesn't need to import the module.
- `app-detail.tsx` is ~500 lines — scan it thoroughly for all class references.

## Verify
- [ ] FR#1: Each migrated component has a co-located `.module.css` file
- [ ] FR#5: `:global()` rules for state modifiers and contextual selectors render correctly
- [ ] FR#7: Dark theme overrides (if any in these components) function in both themes
- [ ] FR#11: Unit tests use `data-testid`/ARIA
- [ ] FR#12: E2e selectors use `data-testid`
- [ ] FR#13: No `ht-` prefix in module files
- [ ] AC#2: Each migrated component has a `.module.css` file
- [ ] AC#4: Full e2e suite passes
- [ ] AC#5: Full unit test suite passes
- [ ] AC#6: No migrated-class queries; ARIA for state
- [ ] AC#11: No `ht-` prefix in module files
