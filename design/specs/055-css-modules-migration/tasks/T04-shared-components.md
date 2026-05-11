---
task_id: "T04"
title: "Migrate self-contained shared components"
status: "planned"
depends_on: ["T03"]
implements: ["FR#1", "FR#5", "FR#8", "FR#11", "FR#12", "FR#13", "AC#2", "AC#4", "AC#5", "AC#6", "AC#11"]
---

## Summary
Migrate 8 self-contained shared components: confirm-dialog, error-banner, action-buttons, sort-header, tier-toolbar, time-preset-selector, stats-strip, and log-table. These are used by multiple pages but all classes are rendered only within the component itself. Includes first use of `:global()` for state modifiers and responsive media query migration from labeled blocks.

## Prompt
For each component, follow the same migration pattern as T03:

**Components (in `frontend/src/components/shared/` unless noted):**
1. `confirm-dialog.tsx` — classes: `.ht-confirm-dialog*`. Has `is-active` state modifier — use `:global(.is-active)` pattern. Test file `confirm-dialog.test.tsx:87` queries `.ht-confirm-dialog__backdrop`.
2. `error-banner.tsx` — classes: `.ht-error-banner*`, `.ht-traceback` (STAYS GLOBAL — 3 files). Only move `ht-error-banner*` classes.
3. `action-buttons.tsx` — scan for component-specific classes. This component heavily uses `ht-btn` (global). Only extract action-button-specific classes if any exist.
4. `sort-header.tsx` — classes: `.ht-sort-header*` including `:hover`, `:focus-visible`, `--active` modifier.
5. `tier-toolbar.tsx` — classes: `.ht-tier-toolbar`, `.ht-tier-toggle*`. Has responsive override in the 900px block (labeled `/* ht-tier-toggle__btn — owner: tier-toolbar */` from T02). Move that responsive block into the module.
6. `time-preset-selector.tsx` (in `frontend/src/components/layout/`, not `shared/`) — classes: `.ht-time-preset-selector*`. Has responsive override in the 900px block (labeled from T02). Move it.
7. `stats-strip.tsx` — classes: `.ht-stats-strip*`. Has responsive override in 768px block. Move it.
8. `log-table.tsx` — classes: `.ht-table-log*`, `.ht-log-message-cell*`, `.ht-log-message__text`, `.ht-log-expanded-row*`, `.ht-log-source__fn`, `.ht-log-source-inline`, `.ht-log-level-badge*`, `.ht-log-table-container`. Per the adjudication table, `ht-log-level-badge` moves here (canonical owner). NOTE: `ht-table-toolbar*` and `ht-table-card-scroll` are shared with `table-card.tsx` (both render toolbar markup independently) — these stay global per the adjudication table (2-file shared class). Do NOT extract them here. Has 1024px media query for source column hiding. Has extensive responsive overrides in 768px block.

**Key patterns for this batch:**
- `:global()` for state modifiers: `.dialog:global(.is-active) { ... }`
- Responsive rules from labeled 900px/768px blocks move into the module's own `@media` block
- `error-banner.tsx` uses `.ht-traceback` which stays global (3 files) — reference it as a plain string, not from the module

**After all 8 components:**
Run the verification baseline:
- `cd frontend && npm run build`
- `cd frontend && npx vitest run`
- `nox -s frontend && nox -s e2e`

## Focus
- `confirm-dialog.test.tsx:87` has `querySelector(".ht-confirm-dialog__backdrop")` — needs data-testid migration.
- `tier-toolbar.tsx:33` uses template literal for conditional active class — convert to `clsx(styles.btn, tierFilter === t && styles.active)`.
- `tier-toolbar.tsx:41` uses `ht-pill ht-pill--mute ht-pill--interactive` — these are global pill classes. Keep as string: `class={clsx("ht-pill ht-pill--mute ht-pill--interactive", ...)}`.
- `stats-strip.tsx:25` has dynamic `ht-stats-strip__value--${c.tone}` — in the module, create explicit modifier classes (`.valueOk`, `.valueWarn`, `.valueErr`) and map tone to class.
- `error-banner.tsx` does NOT have a test file — no test migration needed.
- For e2e tests: `grep -rn` the class names against `tests/e2e/` to find selectors to update.

## Verify
- [ ] FR#1: Each migrated component has a co-located `.module.css` file
- [ ] FR#5: Confirm-dialog with `is-active` class renders its active state (backdrop visible, dialog centered) — `:global(.is-active)` pattern works
- [ ] FR#8: Any component-specific animations are scoped; shared animations referenced from modules work
- [ ] FR#11: Unit tests use `data-testid` and ARIA attributes, not migrated class names
- [ ] FR#12: E2e test selectors for migrated components use `data-testid`, not `.ht-*` classes
- [ ] FR#13: No `.module.css` file contains `ht-` prefix
- [ ] AC#2: Each migrated component has a `.module.css` file
- [ ] AC#4: E2e test suite passes with zero regressions
- [ ] AC#5: Unit test suite passes with zero regressions
- [ ] AC#6: No migrated-class queries in unit tests; state assertions use ARIA
- [ ] AC#11: No `ht-` prefix in module files
