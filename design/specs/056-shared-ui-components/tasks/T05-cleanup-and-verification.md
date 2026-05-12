---
task_id: "T05"
title: "Delete global CSS, update CI guards, verify build"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#11", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#8", "AC#9", "AC#10"]
---

## Summary
Delete the four `styles/*.css` files, remove their `@import` lines from `global.css`, update the CI guard scripts (allowlist and EXEMPTIONS), run a comprehensive grep to verify no raw `ht-btn/ht-badge/ht-chip/ht-card` class strings remain in TSX (with the documented diagnostics.tsx exemption), run `npm run build`, run all three CI guard scripts, and run the full test suite. Update CLAUDE.md and design/context.md documentation.

## Prompt

### 1. Delete global CSS files
Delete these four files:
- `frontend/src/styles/buttons.css`
- `frontend/src/styles/badges.css`
- `frontend/src/styles/chips.css`
- `frontend/src/styles/cards.css`

### 2. Update global.css
Remove these four `@import` lines from `frontend/src/global.css`:
```
@import "./styles/cards.css";
@import "./styles/badges.css";
@import "./styles/buttons.css";
@import "./styles/chips.css";
```

### 3. Update CI guard scripts

**`tools/check_global_css_allowlist.py`**: Remove these entries from the `ALLOWLIST` array:
- `"ht-card"`
- `"ht-badge"`
- `"ht-btn"`
- `"ht-btn-group"`
- `"ht-chip"`

**`tools/check_dead_global_css.py`**: Remove these entries from the `EXEMPTIONS` list:
- The `("ht-badge--", ...)` tuple
- The `("ht-chip--kind-", ...)` tuple

### 4. Comprehensive verification

Run these checks in order:

**AC#1 grep check** — verify no raw class strings remain:
```bash
grep -rn 'ht-btn\|ht-badge\|ht-chip\|ht-card' frontend/src/ --include='*.tsx' --include='*.ts'
```
Expected results: only `diagnostics.tsx` (AC#1 exemption), `apps.module.css` references to `[data-role=` or `[data-variant=`, and possibly `utils/status.ts` type references. Any `ht-btn`/`ht-badge`/`ht-chip`/`ht-card` in TSX files (other than the exempted diagnostics.tsx sections) is a failure.

Also check module CSS files:
```bash
grep -rn ':global(\.ht-btn\|:global(\.ht-badge\|:global(\.ht-chip\|:global(\.ht-card' frontend/src/ --include='*.module.css'
```
Expected: no results (all `:global(.ht-btn-group)` and `:global(.ht-chip--auto)` should have been migrated to data-attribute selectors in T03/T04).

**AC#4 deletion check** — verify files are gone:
```bash
ls frontend/src/styles/buttons.css frontend/src/styles/badges.css frontend/src/styles/chips.css frontend/src/styles/cards.css 2>&1
```
Expected: all four should report "No such file or directory".

**AC#5 CI guards**:
```bash
uv run python tools/check_global_css_allowlist.py
uv run python tools/check_dead_global_css.py
uv run python tools/check_css_module_globals.py
```
Expected: all three pass.

**AC#9 build check**:
```bash
cd frontend && npm run build
```
Expected: build succeeds with no errors.

**AC#8 test suite**:
```bash
timeout 300 uv run nox -s dev -- -n 2
```
Expected: all tests pass.

### 5. Documentation updates

**CLAUDE.md** CSS Architecture section — update to reflect that buttons, badges, chips, and cards are now components in `shared/`, not shared CSS files in `styles/`. Update the "When to use styles/ vs a module" guidance: remove buttons, badges, chips, cards from the `styles/` description. Update "Adding a new shared class" to note the reduced scope. Update the list of CSS files in the `styles/` description.

**design/context.md** Component Inventory / Shared Components section — add entries for Button, Badge, Chip, Card with brief descriptions matching the new component APIs.

## Focus
- `frontend/src/global.css` — currently has 10 `@import` lines; after removing 4, should have 6 remaining (fonts, reset, typography, layout, tables, utilities)
- `tools/check_global_css_allowlist.py` — the `ALLOWLIST` array; also remove `"ht-pill"` and `"ht-search"` if they appear to be dead (check first — only remove the four documented prefixes)
- `tools/check_dead_global_css.py` — the `EXEMPTIONS` list around line 30
- `CLAUDE.md` CSS Architecture section starts around line 106 — mentions `styles/` files list including `cards.css`, `badges.css`, `buttons.css`, `chips.css`
- `design/context.md` Shared Components section starts around line 308
- The diagnostics.tsx exemption means the grep check WILL find `ht-card` in that file — this is expected and correct
- The `ht-error-card` class in `error-boundary.test.tsx` should have been updated to `data-testid` in T03 — verify this

## Verify
- [ ] FR#11: All four component CSS files are co-located `.module.css` files; no global `ht-*` classes remain for buttons, badges, chips, or cards
- [ ] AC#1: grep confirms no raw `ht-btn`/`ht-badge`/`ht-chip`/`ht-card` in TSX except diagnostics.tsx exemption
- [ ] AC#2: Button component hardcodes `type="button"` (verified via T01 unit tests)
- [ ] AC#3: `npm run build` succeeds and visual appearance is preserved (no CSS value changes)
- [ ] AC#4: The four `styles/*.css` files are deleted and `@import` lines removed from `global.css`
- [ ] AC#5: All three CI CSS guard scripts pass with no violations
- [ ] AC#6: grep confirms no `--group` or `--cancelled` badge variants in any CSS or TSX file
- [ ] AC#7: grep confirms only `muted` chip variant exists (no `--auto` in CSS)
- [ ] AC#8: Full test suite passes with updated test selectors
- [ ] AC#9: Frontend builds without errors
- [ ] AC#10: TableCard internally uses Card component (verified via T03)
