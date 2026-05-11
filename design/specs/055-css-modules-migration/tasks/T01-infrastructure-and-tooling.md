---
task_id: "T01"
title: "Add CSS Modules infrastructure and CI tooling"
status: "planned"
depends_on: []
implements: ["FR#3", "FR#9", "FR#10", "FR#14", "AC#3", "AC#7", "AC#8", "AC#14"]
---

## Summary
Install `clsx` and `vite-css-modules`, configure `vite.config.ts` for typed CSS module generation, write three Python CI guard scripts (`check_global_css_allowlist.py`, `check_dead_global_css.py`, `check_css_module_globals.py`), update `lint.yml` with build + guard steps, and add the `.gitignore` exception for Playwright snapshot PNGs. This establishes all infrastructure before any component migration begins.

## Prompt
1. **Install dependencies**: In `frontend/`, run `npm install clsx` and `npm install --save-dev vite-css-modules`.

2. **Configure vite.config.ts** (`frontend/vite.config.ts`): Add `import { patchCssModules } from 'vite-css-modules';` and update the plugins array to `plugins: [preact(), patchCssModules({ generateSourceTypes: true })]`.

3. **Add generated .d.ts to gitignore**: Add `frontend/src/**/*.module.css.d.ts` to the root `.gitignore`.

4. **Add snapshot PNG exception**: Add `!tests/e2e/**-snapshots/*.png` to `.gitignore` (the blanket `*.png` at line 230 blocks Playwright snapshots).

5. **Write `tools/check_global_css_allowlist.py`**: Python script that extracts all `.ht-*` selectors from `frontend/src/global.css`, compares against an allowlist of shared class prefixes (see design doc "What stays in global.css" table for the list: `ht-layout`, `ht-main`, `ht-page`, `ht-section`, `ht-page-header`, `ht-grid`, `ht-level`, `ht-flex`, `ht-card`, `ht-table`, `ht-badge`, `ht-btn`, `ht-chip`, `ht-pill`, `ht-search`, `ht-text-`, `ht-mb-`, `ht-mt-`, `ht-ml-`, `ht-mr-`, `ht-p-`, `ht-w-`, `ht-visually-hidden`, `ht-skip-link`, `ht-display`, `ht-icon`, `ht-heading`, `ht-subheading`, `ht-label`, `ht-select`, `ht-hamburger`, `ht-drawer`, `ht-live-pulse`, `ht-block`, `ht-nowrap`, `ht-error-page`, `ht-error-card`, `ht-instance-row`, `ht-traceback`, `ht-table-toolbar`, `ht-table-card-scroll`), and exits non-zero if unknown selectors are found. Supports `--diff-only` mode that checks only `git diff HEAD -- frontend/src/global.css`. Include a smoke test with known-allowed + known-disallowed selectors.

6. **Write `tools/check_dead_global_css.py`**: Python script that extracts all class selectors from `frontend/src/global.css`, checks each against `.tsx` files, and reports unreferenced selectors. Maintains an annotated exemption list for dynamically-assembled classes (`ht-badge--*`, `ht-chip--kind-*`, `ht-detail-stats-row__value--*`, `ht-stats-strip__value--*`) and third-party injected classes (`shiki`, `line`, `line--*`). Exit code 0 always (warning mode during migration).

7. **Write `tools/check_css_module_globals.py`**: Python script that greps `.module.css` files for bare state modifier patterns (`.className.is-active`, `.className.is-blocked`, `.className.is-expanded`, `.className.is-open` without `:global()`) and exits non-zero on match.

8. **Update `.github/workflows/lint.yml`**: In the `frontend` job, add steps after `npm ci`:
   - `npm run build` (generates CSS module .d.ts files) — before `tsc --noEmit`
   - `uv run python tools/check_css_module_globals.py` — after tsc
   - `uv run python tools/check_global_css_allowlist.py --diff-only` — after tsc
   - `uv run python tools/check_dead_global_css.py || true` — warning mode
   The build step must install `uv` first (add `astral-sh/setup-uv@v6` step). Also add `tools/**` to the frontend path filter.

9. **Update `.github/workflows/e2e-tests.yml`**: Add a `workflow_dispatch` input for `--update-snapshots` so baselines can be regenerated from CI.

## Focus
- Existing `tools/` scripts are all Python — follow the same conventions (argparse, sys.exit, `if __name__ == "__main__"` guard). See `tools/check_schemas_fresh.py` for a representative pattern.
- `lint.yml` currently has `frontend` job at lines 77-101. The uv setup step already exists in the `python` job — replicate the pattern.
- The allowlist regex must handle BEM modifiers: `ht-btn--sm` should match allowlist entry `ht-btn`. Match on prefix, not exact name.
- The dead CSS script will have false negatives for dynamic classes like `ht-badge--${variant}` — the exemption list handles this by prefix matching.
- `.gitignore` line 230 has `*.png` with `!docs/_static/*.png` exception at line 231.

## Verify
- [ ] FR#3: `cd frontend && npm run build && npx tsc --noEmit` succeeds with zero errors
- [ ] FR#9: Running `tools/check_global_css_allowlist.py` against current `global.css` exits 0 (all existing classes are on the allowlist); adding a fake `.ht-new-widget__header` class to global.css causes exit 1
- [ ] FR#10: Running `tools/check_dead_global_css.py` reports known orphaned classes (`ht-error-feed`, `ht-error-entry`, `ht-group-filter-bar`, `ht-group-chip`)
- [ ] FR#14: `clsx` is in `package.json` dependencies
- [ ] AC#3: `npx tsc --noEmit` succeeds
- [ ] AC#7: The allowlist script exits non-zero for unknown selectors
- [ ] AC#8: The dead CSS script reports unreferenced selectors
- [ ] AC#14: `clsx` is listed in `package.json`
