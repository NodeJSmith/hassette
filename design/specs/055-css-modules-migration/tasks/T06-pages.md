---
task_id: "T06"
title: "Migrate page components"
status: "planned"
depends_on: ["T05"]
implements: ["FR#1", "FR#11", "FR#12", "FR#13", "AC#1", "AC#2", "AC#4", "AC#5", "AC#6", "AC#11"]
---

## Summary
Migrate 6 page components: apps, handlers, diagnostics, logs, config, and not-found. These are top-level views that mix global layout primitives with page-specific styles. After this batch, `global.css` should be approaching the ~500 line target.

## Prompt
**Pages (all in `frontend/src/pages/`):**

1. **`apps.tsx`** — classes: `.ht-apps-*`, `.ht-apps-filter-pill*`, `.ht-apps-row*`.
   - Dynamic class: `ht-badge--${statusToVariant(status)}` — `ht-badge` stays global, no module change for this.
   - Responsive: `.ht-apps-row__expand` touch target in labeled 900px block; `.ht-apps-table` column hiding in labeled 900px block. Move both.
   - E2e: `test_apps.py` (5 refs), `test_apps_list.py` (6 refs)
   - Unit test: `apps.test.tsx`

2. **`handlers.tsx`** — classes: `.ht-handlers-*`, `.ht-mobile-card*`.
   - Has 768px and 480px responsive overrides
   - E2e: no dedicated handlers e2e file, but check `test_navigation.py`, `test_responsive.py`
   - Unit test: `handlers.test.tsx`

3. **`diagnostics.tsx`** — classes: `.ht-diag__*` (including `.ht-diag__degraded-banner` which is a diagnostics-prefixed variant, distinct from alert-banner's `.ht-degraded-banner` migrated in T05). Grep for the actual class names in `global.css` before extracting — verify each one is exclusive to this file.
   - Unit test: `diagnostics.test.tsx`

4. **`logs.tsx`** — classes: `.ht-logs-page`.
   - Minimal page-specific CSS. The `ht-card--logs-full` modifier might be a `ht-card` variant (stays global) — check if it's only used here. If exclusive to logs, move it.
   - E2e: `test_logs.py` (11 refs — heavy, but most reference `log-table` classes already migrated or global table classes)
   - Unit test: `logs.test.tsx`

5. **`config.tsx`** — classes: `.ht-config-groups*`, `.ht-config-group*`, `.ht-config-table*`, `.ht-section-label`, `.ht-card--config`.
   - Has 768px responsive override for config table
   - E2e: `test_config.py` (1 ref)
   - Unit test: `config.test.tsx`

6. **`not-found.tsx`** — classes: `.ht-error-page`, `.ht-error-card` — check if these are shared (used by error-boundary too). If shared (2+ files), keep global. If exclusive, move.
   - Unit test: `not-found.test.tsx`

**After all pages:**
Run verification baseline. Check `wc -l frontend/src/global.css` — should be trending toward 500 lines.

## Focus
- `apps.tsx` is the largest page (~300 lines) with the most class references. Template literals with conditional classes are common — convert to `clsx`.
- `logs.tsx` is tiny (637 bytes) — may have very little page-specific CSS.
- `not-found.tsx` shares `.ht-error-page` and `.ht-error-card` with `error-boundary.tsx` — grep both files to determine ownership. If shared, keep global.
- E2e tests: `test_logs.py` has 11 `.ht-*` refs — many may reference `log-table` classes (already migrated in T04) or global table classes. Only page-specific selectors need updating here.
- After this batch, do a line count on `global.css` to track progress toward the 500-line target.

## Verify
- [ ] FR#1: Each migrated page has a co-located `.module.css` file (unless it uses only global classes)
- [ ] FR#11: Unit tests use `data-testid`/ARIA
- [ ] FR#12: E2e selectors use `data-testid`
- [ ] FR#13: No `ht-` prefix in module files
- [ ] AC#1: `global.css` line count is decreasing toward 500 (report the count)
- [ ] AC#2: Each migrated page has a `.module.css` file
- [ ] AC#4: Full e2e suite passes
- [ ] AC#5: Full unit test suite passes
- [ ] AC#6: No migrated-class queries in tests
- [ ] AC#11: No `ht-` prefix in module files
