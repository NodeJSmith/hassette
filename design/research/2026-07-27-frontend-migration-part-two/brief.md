# Frontend Migration Part 2: Component & Styling Conversion

**Date:** 2026-07-27
**Context:** Spec 020 (foundation migration) landed via PR #1466 → `frontend-migration` branch. The app runs on React 19 + Zustand + Tailwind v4 with shadcn initialized but no components generated. All 66 CSS Module files, 6 global CSS files, `tokens.css` (136 custom properties), and hand-rolled interactive components remain.

## Inventory

**Hand-rolled components → shadcn replacements:**

| Component | Files | shadcn target |
|---|---|---|
| `confirm-dialog` | tsx + module.css + test | AlertDialog |
| `info-popover` | tsx + module.css + test | Popover |
| `command-palette` | tsx + module.css + test | Command |
| `button` | tsx + module.css + test | Button |
| `badge` | tsx + module.css + test | Badge |
| `chip` | tsx + module.css + test | Badge variant |
| `card` | tsx + module.css + test | Card |
| `tooltip` | tsx + module.css + test | Tooltip |
| `column-filter-popover` | tsx + module.css | Popover / Select |
| `time-preset-selector` | tsx + module.css + test | Select |
| `execution-table` | tsx + module.css + test | Table |
| `log-table` (5 sub-components + 4 hooks) | tsx + module.css + tests | Table |
| `table-card`, `table-footer` | tsx + module.css | Table wrapper |

**CSS Module files:** 66 total (14 app-detail, 5 design, 5 layout, 33 shared, 7 pages, 2 other).

**Global CSS:** 6 files in `styles/` (fonts, layout, reset, tables, typography, utilities).

**CSS lint tools:** 9 scripts in `tools/frontend/` — at least 4 become unnecessary once CSS Modules are gone (`check_dead_global_css.py`, `check_global_css_allowlist.py`, `check_css_module_globals.py`, `check_undefined_css_refs.py`).

**Other cleanup:** `@floating-ui/dom` (used by info-popover + column-filter-popover), `focus-trap.ts` utility, `design/context.md` (780 lines, needs rewrite for shadcn vocabulary).

## PR Plan

All PRs target `frontend-migration`. After all land, one merge PR from `frontend-migration` → `main`.

### PR 1: Token rename + component replacement (single PR, ordered commits)

**Why first:** shadcn components need the token bridge to render correctly against the existing design. Shared components (`Button`, `Badge`, `Card`, etc.) are imported everywhere — replacing them first means later CSS Module conversions can use shadcn primitives directly instead of converting styling for components that are about to be deleted.

**Commit ordering:** Token rename → leaf components (Button, Badge, Card, Tooltip) → interactive components (AlertDialog, Popover, Command, Select) → tables (TanStack Table + shadcn Table) → sidebar (shadcn Sidebar) → cleanup (remove @floating-ui/dom, focus-trap.ts). Each commit leaves the app buildable and tests passing.

**Scope:**
- Adopt shadcn token names: rename all 136 `--bg-*`/`--ink-*`/`--accent-*` tokens to shadcn's `--background`/`--primary`/`--foreground` naming; update all CSS/TSX references
- Generate shadcn primitives: Button, Badge, Card, Tooltip, AlertDialog, Popover, Command, Select, Table, Sidebar
- Replace hand-rolled shared components with shadcn equivalents (button, badge, chip, card, tooltip, confirm-dialog, info-popover, command-palette, column-filter-popover, time-preset-selector)
- Replace sidebar with shadcn Sidebar (preserve Cmd+B, collapse, active-route highlighting)
- Replace tables with TanStack Table + shadcn Table (log-table subsystem, execution-table, table-card/table-footer)
- Remove `@floating-ui/dom` (orphaned after Popover replaces info-popover + column-filter-popover)
- Remove `focus-trap.ts` (orphaned after Radix owns focus trapping)
- Update tests for all replaced components

**Does not include:** CSS Module → Tailwind conversion for pages/non-shared components, global CSS file removal, lint tool removal, design/context.md rewrite, doc screenshots.

### PR 2: CSS Module → Tailwind conversion + global CSS cleanup

**Why second:** With shadcn components in place, the remaining CSS Modules are page-level and layout-level styling. Convert them to Tailwind utility classes.

**Scope:**
- Convert all remaining CSS Module files to Tailwind utilities (delete the `.module.css` files)
- Adopt Tailwind Preflight, remove `styles/reset.css`
- Remove or consolidate remaining `styles/*.css` files into Tailwind `@layer` directives
- Remove CSS lint tools that guarded CSS Module / global CSS conventions (`check_dead_global_css.py`, `check_global_css_allowlist.py`, `check_css_module_globals.py`, `check_undefined_css_refs.py`; evaluate whether `check_dead_tokens.py`, `check_breakpoint_drift.py` still apply)
- Remove `tokens.css` (token rename happened in PR 1; this removes the file once all remaining `var()` references are through Tailwind theme)
- Enable React StrictMode and fix any double-effect issues

### PR 3: Design system docs + screenshots

**Why last:** Visual output must be stable before capturing screenshots or rewriting the design reference.

**Scope:**
- Rewrite `design/context.md` for shadcn/Tailwind vocabulary (component names, token names, usage patterns)
- Regenerate all `docs/_static/web_ui_*.png` screenshots
- Update any docs pages that reference the old CSS architecture or component names
- Final visual QA pass via demo stack

## Dependencies

```
PR 1 (tokens + components) → PR 2 (CSS conversion) → PR 3 (docs + screenshots)
```

Each PR should leave the app fully buildable and visually identical (or intentionally improved where shadcn defaults are better). E2E suite must pass at each checkpoint.

## Decisions

1. **Tables → TanStack Table + shadcn Table.** Full replacement: TanStack Table for the data engine (sorting, filtering, column visibility) + shadcn Table for the markup. The log-table's 9-file subsystem gets rewritten, not just restyled. This applies to execution-table and table-card/table-footer too.
2. **Sidebar → shadcn Sidebar.** Replace with shadcn's Sidebar primitive. Preserve keyboard shortcut (Cmd+B), active-route highlighting, and collapse behavior via shadcn's collapsible API.
3. **Tokens → adopt shadcn names fully.** Replace the existing `--bg-*`/`--ink-*`/`--accent-*` naming with shadcn's `--background`/`--primary`/`--foreground` naming. All 136 tokens get renamed. Spacing/typography tokens (`--sp-*`, `--fs-*`, `--fw-*`) adopt Tailwind's built-in scale where equivalents exist.
