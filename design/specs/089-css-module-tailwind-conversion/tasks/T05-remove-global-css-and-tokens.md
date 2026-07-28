---
task_id: "T05"
title: "Remove global CSS files and inline tokens into global.css"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#3", "FR#4", "FR#5", "FR#6", "FR#8", "AC#1", "AC#2", "AC#8"]
---

## Summary

Remove the 5 remaining global CSS files in `styles/` (reset.css was already removed in T01), replace all `.ht-*` class usages with Tailwind utilities at call sites, inline `tokens.css` values into `global.css`, and remove the `tokens.css` import from `main.tsx`. After this task, the only CSS files are `global.css` and `styles/fonts.css`.

## Target Files

- delete: `frontend/src/styles/typography.css`
- delete: `frontend/src/styles/tables.css`
- delete: `frontend/src/styles/layout.css`
- delete: `frontend/src/styles/utilities.css`
- delete: `frontend/src/tokens.css`
- modify: `frontend/src/global.css`
- modify: `frontend/src/main.tsx`
- modify: `frontend/src/app.tsx`
- modify: `frontend/src/pages/apps.tsx`
- modify: `frontend/src/pages/handlers.tsx`
- modify: `frontend/src/pages/handlers-rows.tsx`
- modify: `frontend/src/pages/logs.tsx`
- modify: `frontend/src/pages/diagnostics.tsx`
- modify: `frontend/src/components/shared/log-table/log-table-view.tsx`
- modify: `frontend/src/components/shared/table-card.tsx`
- modify: `frontend/src/components/shared/execution-table.tsx`
- modify: `frontend/src/components/layout/alert-banner.tsx`
- modify: `frontend/src/components/app-detail/overview-tab.tsx`
- modify: `frontend/src/pages/config.tsx`
- modify: `frontend/src/pages/handlers-rows.test.tsx`
- modify: `frontend/src/app.test.tsx`
- modify: `frontend/src/pages/logs.test.tsx`
- modify: `frontend/src/components/layout/alert-banner.test.tsx`
- modify: `frontend/src/components/shared/log-table/log-table-view.test.tsx`
- modify: `frontend/src/components/shared/table-card.test.tsx`
- modify: `tests/e2e/test_navigation.py`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

Remove all global CSS files except `fonts.css`, replace `ht-*` class usages with Tailwind utilities, inline token definitions into `global.css`, and fix tests that query by `ht-*` class selectors.

**Step 1 — Move typography.css to `@layer base` in global.css:**

Move `styles/typography.css` rules into a `@layer base` block in `global.css`:
- `body` styles (font-family, font-size, line-height, color, background)
- `h1`–`h4` styles
- `code`, `pre`, `kbd` styles
- `a` styles (color, hover)
- `strong` styles
- `::selection` styles

Use the shadcn-aliased token names (e.g., `var(--font-sans)` not `var(--font-body)`, `var(--foreground)` not `var(--ink-1)`).

Remove `@import "./styles/typography.css"` from global.css and delete the file.

**Step 2 — Replace tables.css `ht-*` classes:**

The `.ht-table`, `.ht-table--fixed`, `.ht-table--compact`, and `.ht-table-card-scroll` classes are used in:
- `log-table-view.tsx` (`.ht-table`, `.ht-table--fixed`)
- `execution-table.tsx` (`.ht-table`, `.ht-table--fixed`)
- `table-card.tsx` (`.ht-table-card-scroll`)
- `overview-tab.tsx` (`.ht-table--compact`)
- `apps.tsx`, `handlers.tsx` (via table components)

Replace each `ht-table*` class reference with equivalent Tailwind utilities directly at the call site. For the shared table styling pattern (width 100%, border-collapse, sticky thead, hover rows), apply Tailwind utilities directly on each table component. If a shared `@layer components` rule is needed for a pattern used by 3+ components, use a descriptive non-`ht-` name (e.g., `.data-table`).

Remove `@import "./styles/tables.css"` from global.css and delete the file.

**Step 3 — Replace layout.css `ht-*` classes:**

The `.ht-layout`, `.ht-main`, `.ht-page`, `.ht-section`, `.ht-page-header`, `.ht-level`, `.ht-level-start`, `.ht-level-end`, `.ht-level-item`, `.ht-display` classes are used in `app.tsx` and page components. Replace each with Tailwind utilities at the call site. The responsive `@media` rules use `max-sidebar:` and `max-mobile:` prefixes.

Remove `@import "./styles/layout.css"` from global.css and delete the file.

**Step 4 — Replace utilities.css `ht-*` classes:**

Replace every `ht-*` utility class with Tailwind equivalents at each TSX call site:
- `.ht-text-muted` (11 uses) → `text-muted-foreground`
- `.ht-text-danger` (11 uses) → `text-destructive`
- `.ht-text-mono` (32 uses) → `font-mono`
- `.ht-text-sm` (26 uses) → `text-sm`
- `.ht-text-xs` (6 uses) → `text-xs`
- `.ht-text-warning` (6 uses) → `text-[var(--status-warning)]`
- `.ht-text-secondary` (5 uses) → `text-foreground-secondary`
- `.ht-text-cancel` (4 uses) → `text-[var(--status-cancel)]`
- `.ht-text-semibold` → `font-semibold`
- `.ht-mb-2` / `.ht-mb-3` / `.ht-mb-4` → `mb-2` / `mb-3` / `mb-4`
- `.ht-ml-2` → `ml-2`
- `.ht-block` → `block`
- `.ht-visually-hidden` → `sr-only`
- `.ht-skip-link` → Tailwind utilities (see focus section below)
- `.ht-search` → Tailwind utilities
- `.ht-alert` / `.ht-alert--danger` / `.ht-alert--warning` → Tailwind utilities
- `.ht-log-level-badge` → Tailwind utilities
- `.ht-traceback` → Tailwind utilities
- `.ht-detail-label` → Tailwind utilities
- `.ht-section-label` → Tailwind utilities
- `.ht-table-section` → Tailwind utilities

**`config.tsx` (no module file — uses `ht-*` globals directly):**
`frontend/src/pages/config.tsx` uses `ht-page`, `ht-page-header`, `ht-display`, `ht-alert`, `ht-alert--danger` directly without a CSS Module. Replace all five with Tailwind utilities as part of this step.

Remove `@import "./styles/utilities.css"` from global.css and delete the file.

**Step 5 — Inline tokens.css into global.css:**

The `:root` and `[data-theme="dark"]` blocks in `tokens.css` define the source token values. The `:root` and `[data-theme="dark"]` blocks in `global.css` define the shadcn alias layer that references them. Now that no CSS Module files reference old token names directly, merge the source values from `tokens.css` INTO the existing blocks in `global.css`. The result is a single `:root` block with all values (surfaces, ink, lines, accent, status colors, spacing, sizing, shadows, opacity, motion, z-index) plus the shadcn aliases that reference them.

In `main.tsx`, remove the `import "./tokens.css"` line. Delete `frontend/src/tokens.css`.

**Step 6 — Fix tests that query by `ht-*` class selectors:**

These tests will break because the `ht-*` classes no longer exist:

- `handlers-rows.test.tsx` — uses `td.ht-text-danger`, `td.ht-text-warning`, `td.ht-text-cancel`, `span.ht-text-danger`. Replace with behavioral assertions or Tailwind class queries (e.g., `.text-destructive`).
- `app.test.tsx` — uses `main.ht-main`, `.ht-skip-link`. Replace with semantic queries (`main` element, `[data-testid]`, role queries).
- `logs.test.tsx` — uses `h1.ht-display`. Replace with `getByRole("heading")`.
- `alert-banner.test.tsx` — uses `.ht-text-secondary`. Replace with behavioral assertion.
- `log-table-view.test.tsx` — uses `.ht-table`, `.ht-table--fixed`. Replace with `[data-testid="log-table"]` or the `table` element query.
- `table-card.test.tsx` — uses `.ht-table-card-scroll`. Replace with `[data-testid]` or a role query.

**Step 7 — Fix E2E test:**

`tests/e2e/test_navigation.py` uses `a.ht-skip-link` selector. Replace with a `data-testid` selector (add `data-testid="skip-link"` to the skip link element in `app.tsx`).

## Focus

- The `.ht-skip-link` class has complex focus-visible behavior (hidden off-screen, appears on focus). Convert to Tailwind utilities: `sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[var(--z-skip-link)] focus:p-2 focus:px-4 focus:bg-card focus:text-foreground focus:border-2 focus:border-primary focus:rounded-md`. Note it uses `:focus` not `:focus-visible` — the skip link must be visible on ALL focus types.
- The `.ht-table td a` styles in typography.css add underline decoration to links inside table cells. This must be preserved either as a `@layer base` rule or as Tailwind classes on the relevant `<a>` elements inside table cells.
- `tokens.css` defines both light and dark theme values. When inlining, the light values go in `:root` and the dark values go in `[data-theme="dark"]`. The existing blocks in global.css already have dark-mode overrides for the shadcn aliases — merge carefully, keeping source values separate from aliases for readability.
- The `migrateKey("ht-theme", "theme")` call in `main.tsx` is a localStorage migration, NOT a CSS class — leave it unchanged.

## Verify

- [ ] FR#3: `ls frontend/src/styles/typography.css 2>/dev/null` returns no file. Typography rules exist in `@layer base` in global.css.
- [ ] FR#4: `ls frontend/src/styles/tables.css 2>/dev/null` returns no file. Table styles are expressed as Tailwind utilities or `@layer components` rules.
- [ ] FR#5: `ls frontend/src/styles/layout.css 2>/dev/null` returns no file. Layout classes replaced by Tailwind utilities.
- [ ] FR#6: `ls frontend/src/styles/utilities.css 2>/dev/null` returns no file. `grep -rnoP '(?<!["\w-])ht-(?!theme)[a-zA-Z0-9_-]+' frontend/src --include='*.tsx' | wc -l` returns 0 (matches `ht-*` class-name tokens, excludes `ht-theme` localStorage key; uses word-boundary-aware per-token matching so a `data-testid` on the same line doesn't mask a real `ht-*` class).
- [ ] FR#8: `ls frontend/src/tokens.css 2>/dev/null` returns no file. `grep "tokens.css" frontend/src/main.tsx` returns no match. Token values are inlined in global.css's `:root` and `[data-theme="dark"]` blocks.
- [ ] AC#1: `find frontend/src -name '*.module.css' | wc -l` returns 0.
- [ ] AC#2: `ls frontend/src/styles/reset.css frontend/src/styles/typography.css frontend/src/styles/tables.css frontend/src/styles/layout.css frontend/src/styles/utilities.css frontend/src/tokens.css 2>/dev/null | wc -l` returns 0.
- [ ] AC#8: `grep -rn "import.*\.module\.css" frontend/src/ | wc -l` returns 0.
