---
task_id: "T02"
title: "Establish screenshot baselines and decompose media queries"
status: "planned"
depends_on: ["T01"]
implements: ["FR#6", "AC#10"]
---

## Summary
Before any component migration, establish Playwright screenshot baselines at all 4 viewports x 2 themes for key pages and all app-detail tabs. Also decompose the mixed media query blocks in `global.css` into per-component labeled sections with ownership annotations. Remove the 4 orphaned CSS classes identified in the adjudication table.

## Prompt
1. **Create screenshot baseline tests**: Add a new test file `tests/e2e/test_visual_baselines.py` with parametrized screenshot tests:
   - Pages: apps list, handlers, logs, diagnostics, config
   - App-detail tabs: overview, handlers, code, config
   - Mobile sidebar (drawer open at ≤900px)
   - Viewports: 1440px, 900px, 768px, 375px width (all at 900px height)
   - Themes: light and dark (toggle via the theme button or set `data-theme` attribute)
   - Use `expect(page).to_have_screenshot(full_page=True)` for each combination
   - Use descriptive snapshot names: `{page}-{viewport}w-{theme}.png`

2. **Generate baselines**: Run `cd tests/e2e && pytest test_visual_baselines.py --update-snapshots` to create the initial baseline PNGs. These must be generated on Ubuntu (CI platform) to avoid OS rendering divergence. If running locally on a different OS, note this in a comment and re-generate in CI.

3. **Decompose the 900px media query block** (`frontend/src/global.css:1955-2032`): Split into per-component sections with ownership annotations. Each section gets a header comment naming the owning component and which batch migrates it:
   - `/* shared — permanent */` — `.ht-hamburger`, `.ht-layout` grid, `.ht-main`, `.ht-btn--sm`/`--xs`/`--icon`
   - `/* ht-layout > .ht-sidebar + .ht-drawer .ht-sidebar — owner: sidebar — migrates in T05 */`
   - `/* ht-theme-toggle — owner: status-bar — migrates in T04 */`
   - `/* ht-tab-btn — owner: app-detail — migrates in T07 */`
   - `/* ht-tier-toggle__btn — owner: tier-toolbar — migrates in T04 */`
   - `/* ht-time-preset-selector__btn — owner: time-preset-selector — migrates in T04 */`
   - `/* ht-sidebar__app-expand — owner: sidebar — migrates in T05 */`
   - `/* ht-apps-row__expand — owner: apps — migrates in T06 */`
   - `/* ht-apps-table — owner: apps — migrates in T06 */`
   - `/* ht-invocation-table — owner: handler-invocations — migrates in T08 */`

4. **Decompose other mixed media query blocks**: Apply the same treatment to the 768px and 480px blocks that mix component classes. Use `grep -n '@media' frontend/src/global.css` to find them all.

5. **Remove orphaned CSS classes**: Delete rules for `ht-error-feed`, `ht-error-entry`, `ht-group-filter-bar`, `ht-group-chip` from `global.css` — these have zero references in `.tsx` files.

6. **Run verification baseline**: Execute all three verification commands:
   - `cd frontend && npm run build`
   - `cd frontend && npx vitest run`
   - `nox -s frontend && nox -s e2e`

## Focus
- The 900px block at `global.css:1955-2032` has 13 selector groups. See the design doc's "Responsive media queries" section for the full ownership mapping.
- Playwright screenshots are OS-sensitive — Ubuntu baselines won't match macOS renders. CI runs on `ubuntu-latest`.
- The e2e conftest at `tests/e2e/conftest.py` has the existing test fixtures. Use the same app fixture pattern.
- `tests/e2e/mock_fixtures.py` provides mock data for the test harness.
- The orphaned classes (`ht-error-feed`, etc.) can be verified with `grep -r "ht-error-feed" frontend/src/ --include='*.tsx'` returning zero results.
- The `hooks/use-media-query.ts` file has comments referencing `global.css` breakpoints — these are informational and don't need updating since the breakpoint values stay the same.

## Verify
- [ ] FR#6: All three verification commands pass with zero failures
- [ ] AC#10: Screenshot baseline tests exist at `tests/e2e/test_visual_baselines.py` covering apps, app-detail (4 tabs), and mobile sidebar at 1440px, 900px, 768px, and 375px viewports in both light and dark themes; `expect(page).to_have_screenshot()` assertions are present
