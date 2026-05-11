---
task_id: "T05"
title: "Migrate layout shell components"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "FR#5", "FR#7", "FR#11", "FR#12", "FR#13", "AC#2", "AC#4", "AC#5", "AC#6", "AC#9", "AC#11"]
---

## Summary
Migrate 5 layout shell components: sidebar, status-bar, alert-banner, command-palette, and table-card. This is the highest-risk batch — sidebar has the most complex internal class structure, cross-component contextual rules (`:global(.ht-drawer) .sidebar`), and the mobile-critical drawer rule. All require careful `:global()` usage and responsive media query migration.

## Prompt
**Components:**

1. **`sidebar.tsx`** (`frontend/src/components/layout/sidebar.tsx`) — THE highest-risk component.
   - Classes: All `.ht-sidebar*`, `.ht-nav-list`, `.ht-nav-item`, `.ht-wordmark`, `.ht-brand-link`, `.ht-sidebar-brand`, `.ht-sidebar-footer`, `.ht-sidebar__cmdkey*`
   - **CRITICAL**: Add `data-testid="sidebar"` to the root `<aside>` element. Add `data-testid` to sub-elements used as e2e locators: app-nav, group-header, app-link, app-expand, instance-list.
   - **CRITICAL**: `:global(.ht-drawer) .sidebar { display: flex; }` MUST be present in `sidebar.module.css`. Delete the corresponding `global.css:1968` rule. Test at ≤900px viewport with mobile drawer open.
   - `:global(.ht-layout) > .sidebar { display: none; }` — also from the 900px "shared" block, but this targets sidebar specifically. Move to `sidebar.module.css`.
   - State modifiers: `.ht-nav-item.is-active` → `.navItem:global(.is-active)`. Same for `.ht-sidebar__app-item.is-active`, `.is-blocked`.
   - **ARIA attributes for state migration**: `is-active` nav items need `aria-current="page"`. `is-blocked` app items need `aria-disabled="true"` (or equivalent) added to the component so tests can migrate from `className.toContain("is-blocked")` to ARIA assertions. Add these ARIA attributes in the same commit.
   - Responsive: move sidebar-labeled 900px rules from `global.css` into the module.
   - E2e tests: `test_navigation.py` (18 refs), `test_responsive.py` (17 refs) — heavy migration.

2. **`status-bar.tsx`** (`frontend/src/components/layout/status-bar.tsx`)
   - Classes: `.ht-status-bar*`, `.ht-ws-indicator`, `.ht-pulse-dot*`, `.ht-theme-toggle`
   - `.ht-pulse-dot` uses `@keyframes ht-breathe` (shared animation — keep in global, reference by name)
   - Responsive: move `ht-theme-toggle` touch-target rule from labeled 900px block
   - E2e: `test_responsive.py`, `test_theme.py`

3. **`alert-banner.tsx`** (`frontend/src/components/layout/alert-banner.tsx`)
   - Classes: `.ht-alert*`, `.ht-alert-list`, `.ht-degraded-banner`, `.ht-degraded-banner--warn`, `.ht-degraded-banner__text` (the file exports both `AlertBanner` and `TelemetryDegradedBanner` — migrate all classes from both components)
   - Contextual rule: `.ht-main > .ht-alert` → `:global(.ht-main) > .alert` in module
   - Test: `alert-banner.test.tsx:22, 59` query `.ht-alert--danger`, `.ht-text-secondary`

4. **`command-palette.tsx`** (`frontend/src/components/layout/command-palette.tsx`)
   - Classes: All `.ht-cmd-palette*`
   - Has 768px responsive override for footer
   - E2e: `test_cmd_k.py` (4 refs)

5. **`table-card.tsx`** (`frontend/src/components/shared/table-card.tsx`)
   - Classes: `.ht-table-toolbar*`, `.ht-table-card-scroll`
   - NOTE: `table-card.tsx:18` accepts a `className` prop for external classes — those stay as global strings
   - 768px responsive override for toolbar

**After all 5 components:**
Run verification baseline. Additionally, manually test:
- Mobile drawer open/close at 375px and 900px
- Theme toggle in status bar
- Command palette Ctrl+K opens and closes

## Focus
- Sidebar is the single biggest migration target. `sidebar.tsx` has 30+ class references. `test_navigation.py` has 18 `.ht-*` references — the largest e2e migration.
- The drawer/sidebar interaction is split across two files: `app.tsx` owns `.ht-drawer` (stays global), `sidebar.tsx` owns `.ht-sidebar` (moves to module). The `:global(.ht-drawer) .sidebar` pattern bridges them.
- `tokens.css` must remain byte-identical (AC#9). Do not modify it.
- `table-card.tsx` mixes the `className` prop (global) with its own classes (module). Use: `class={clsx("ht-card ht-card--compact", className, styles.card)}` pattern — but `ht-card` is global so it stays as a string.

## Verify
- [ ] FR#1: Each migrated component has a co-located `.module.css` file
- [ ] FR#5: `:global(.ht-drawer) .sidebar { display: flex }` renders correctly at ≤900px — sidebar visible in mobile drawer
- [ ] FR#7: Theme toggle in status bar works in both light and dark mode
- [ ] FR#11: Unit tests use `data-testid`/ARIA, not migrated class names
- [ ] FR#12: E2e selectors for migrated components use `data-testid`
- [ ] FR#13: No `ht-` prefix in module files
- [ ] AC#2: Each migrated component has a `.module.css` file
- [ ] AC#4: Full e2e suite passes with zero regressions
- [ ] AC#5: Full unit test suite passes
- [ ] AC#6: No migrated-class queries; ARIA for state assertions
- [ ] AC#9: `tokens.css` is byte-identical (verify with `git diff frontend/src/tokens.css`)
- [ ] AC#11: No `ht-` prefix in module files
