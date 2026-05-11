---
task_id: "T08"
title: "Migrate app-detail detail-pane components"
status: "planned"
depends_on: ["T07"]
implements: ["FR#1", "FR#5", "FR#7", "FR#11", "FR#12", "FR#13", "AC#2", "AC#4", "AC#5", "AC#6", "AC#11"]
---

## Summary
Migrate the remaining app-detail components that render within the detail pane: unified-handler-row, handler-invocations, job-executions, handler-list, health-strip, code-tab, config-tab, and error-cell. Code-tab has the most complex migration due to Shiki dark-theme overrides using `:global([data-theme="dark"])`.

## Prompt
**Components (all in `frontend/src/components/app-detail/`):**

1. **`unified-handler-row.tsx`** — classes: `.ht-unified-row*`
   - Unit test: `unified-handler-row.test.tsx:75` queries `.ht-unified-row__desc`

2. **`handler-invocations.tsx`** — classes: `.ht-invocation-table`, `.ht-inv-col-*`
   - `.ht-invocation-table` has responsive override in labeled 900px block (horizontal scroll) — move it
   - Unit test: `handler-invocations.test.tsx`

3. **`job-executions.tsx`** — classes: `.ht-job-*`
   - Dynamic class: `ht-badge--${executionStatusVariant(ex.status)}` — `ht-badge` stays global
   - Unit test: `job-executions.test.tsx`

4. **`handler-list.tsx`** — classes: `.ht-handler-list*` (if any exist — grep to confirm)
   - Unit test: `handler-list.test.tsx`

5. **`health-strip.tsx`** — classes: `.ht-health-strip*` (if any — grep to confirm)
   - May use only global utility classes — skip if no component-specific CSS
   - Unit test: `health-strip.test.tsx`

6. **`code-tab.tsx`** — classes: `.ht-code-tab*`
   - **CRITICAL dark theme override**: `[data-theme="dark"] .ht-code-tab__body .shiki span` must become `:global([data-theme="dark"]) .body :global(.shiki) span` in the module. This is the only component with Shiki integration.
   - Has `.ht-code-tab__error` which uses `ht-card` (global) alongside component class
   - Unit test: `code-tab.test.tsx`

7. **`config-tab.tsx`** — classes: `.ht-config-tab*`, `.ht-config-field*`, `.ht-multi-overview`
   - Distinct from page-level config classes (T06)
   - Unit test: `config-tab.test.tsx`

8. **`error-cell.tsx`** — classes: `.ht-error-cell*` (if any — grep to confirm)
   - Uses `.ht-traceback` — stays global
   - Unit test: `error-cell.test.tsx`

**Per-component**: Follow the same migration pattern as T03-T06. Create `.module.css`, update `.tsx`, update `.test.tsx`, update e2e tests.

**After all components:**
Run verification baseline. Test dark mode on the code tab specifically — Shiki syntax highlighting must retain correct colors.

## Focus
- `code-tab.tsx` is the most delicate migration — the Shiki dark theme override uses `[data-theme="dark"]` targeting component-specific classes. Pattern: `:global([data-theme="dark"]) .body :global(.shiki) span { color: var(--shiki-dark) !important; }`. Test in both themes.
- `handler-invocations.tsx` has the 900px responsive override for horizontal scrolling — move from the labeled block.
- Several components here may have minimal or zero component-specific CSS — grep before creating modules. `health-strip.tsx`, `handler-list.tsx`, `error-cell.tsx` are the likely candidates for "skip — no module needed."
- `unified-handler-row.test.tsx:75` has the `.ht-unified-row__desc` null check — needs `data-testid` migration.
- E2e coverage: `test_app_detail.py` should cover these components, but many assertions may use semantic selectors already.

## Verify
- [ ] FR#1: Each migrated component with component-specific CSS has a `.module.css` file
- [ ] FR#5: Invocation table scrolls horizontally at ≤900px; code-tab Shiki theme override applies in dark mode (syntax colors change)
- [ ] FR#7: Code-tab in dark mode shows colored syntax tokens (not all-white text); light mode shows distinct token colors
- [ ] FR#11: Unit tests use `data-testid`/ARIA
- [ ] FR#12: E2e selectors use `data-testid`
- [ ] FR#13: No `ht-` prefix in module files
- [ ] AC#2: Each migrated component has a `.module.css` file
- [ ] AC#4: Full e2e suite passes
- [ ] AC#5: Full unit test suite passes
- [ ] AC#6: No migrated-class queries; ARIA for state
- [ ] AC#11: No `ht-` prefix in module files
