# Design: CSS Modules Migration

**Date:** 2026-05-11
**Status:** archived
**Scope-mode:** expand
**Research:** /tmp/claude-mine-define-research-bO7xaT/brief.md

## Problem

All component styles live in a single 4600-line file. When a component changes, its old styles stay behind because no one can safely determine which selectors are still referenced. New styles get written for things that already exist because the existing ones are buried in a monolith — the only discovery mechanism is searching through thousands of lines. Duplicated and near-duplicate styles accumulate. Every author independently reinvents patterns that already exist elsewhere in the file.

The cost compounds: each addition makes the file harder to navigate, which makes the next addition more likely to duplicate existing work. A recent quality pass manually removed ~100 lines of orphaned styles and fixed 3 duplicate utility functions — symptoms of a structural problem that manual cleanup cannot sustainably address.

## Goals

- Every component's styles are co-located in a file next to the component, discoverable by opening the component's directory
- The shared stylesheet contains only genuinely cross-cutting foundations: resets, typography, layout primitives, design system components used across 3+ files, and utilities
- The shared stylesheet is under 500 lines
- Style references are type-checked — referencing a nonexistent class name produces a build-time error
- Adding new component-specific styles to the shared stylesheet is caught automatically in CI
- Orphaned styles are detectable by tooling
- Existing test assertions that query by class name are replaced with resilient selectors
- Zero visual regressions across all pages, viewports, and themes

## Non-Goals

- **Visual redesign** — this is a structural migration; the UI must look identical before and after
- **Migrating `tokens.css`** — design tokens stay global and untouched
- **Changing the build tool** — Vite stays; its native support for the target approach is a prerequisite
- **Migrating shared design system classes to modules** — classes like `ht-btn`, `ht-card`, `ht-table`, `ht-badge` used across 3-11 files stay global. Extracting them into importable modules is a natural follow-on but out of scope
- **Removing the `ht-` prefix from global classes** — only component-specific classes that move to modules lose the prefix. Shared global classes keep `ht-` for namespacing

## User Scenarios

### Claude Session: Automation Assistant
- **Goal:** Add or modify styles for a component
- **Context:** Working on a feature branch, needs to style a new element or adjust existing styles

#### Adding styles to an existing component

1. **Opens the component directory**
   - Sees: `sidebar.tsx`, `sidebar.test.tsx`, `sidebar.module.css`
   - Decides: edits the co-located module file
   - Then: imports the style object and references the class by property name; TypeScript catches typos

2. **Needs a shared utility class**
   - Sees: the class referenced in the shared stylesheet or design context
   - Decides: uses the global class name directly alongside module-scoped classes
   - Then: combines global string literal with module reference (e.g., template literal or helper function)

#### Investigating a style bug

1. **Identifies the affected component**
   - Sees: component file and its co-located style module
   - Decides: all component-specific styles are in one place; no need to search a monolith
   - Then: finds the relevant rule immediately

### CI Pipeline: Automated Quality Gate
- **Goal:** Prevent regression to the monolith pattern
- **Context:** A PR adds new styles

#### Catching a new component class in the shared stylesheet

1. **Developer adds `.ht-new-widget__header` to the shared stylesheet**
   - Sees: CI lint guard fails — selector not on the allowlist
   - Decides: moves the class to a co-located module file
   - Then: CI passes

## Functional Requirements

- **FR#1** Component-specific styles are extracted from the shared stylesheet into co-located module files next to each component
- **FR#2** Module-scoped class names are automatically unique — no naming collisions between components
- **FR#3** Referencing a nonexistent class name from a module produces a build-time type error
- **FR#4** Global and module-scoped classes can be combined on the same element without wrapper components or indirection
- **FR#5** Contextual rules where a global parent targets a module-scoped child continue to work correctly
- **FR#6** Responsive behavior at all breakpoints (900px, 768px, 480px) is preserved after migration
- **FR#7** Dark and light theme overrides continue to function for both global and module-scoped classes
- **FR#8** Animations defined in modules are automatically scoped; shared animations remain global and accessible from modules
- **FR#9** A CI check prevents adding new component-specific selectors to the shared stylesheet
- **FR#10** A CI check detects unused selectors in the shared stylesheet
- **FR#11** Unit test assertions that query by class name are replaced with resilient `data-testid` selectors
- **FR#12** End-to-end test selectors that reference component class names are replaced with `data-testid` selectors
- **FR#13** The `ht-` prefix is removed from class names inside module files, since module scoping makes namespace prefixes redundant
- **FR#14** A conditional class composition utility is available for combining multiple classes with boolean conditions

## Edge Cases

- **Cross-component contextual selectors**: ~40 rules in the shared stylesheet reference a global parent and a component child (e.g., a layout container targeting a nested component). These must use the module system's global escape syntax to reference the unscoped parent while keeping the child scoped.
- **Mixed media query blocks**: The 900px responsive breakpoint adjusts 11+ component classes in a single block. Each component's responsive adjustments must move to its module; shared class adjustments stay global. Missing one creates a silent regression visible only at that breakpoint.
- **Dark theme overrides for shared classes**: Rules like `[data-theme="light"] .ht-card` target classes that remain global — these stay in the shared stylesheet. Rules targeting component-specific classes (e.g., code syntax highlighting overrides) move to the component's module with global escape syntax on the theme attribute selector.
- **Shared animations**: Three keyframe animations (`ht-breathe`, `ht-pulse`, `ht-spin`) are used by multiple components. These stay in the shared stylesheet. Component-specific animations (if any) move to the module where they are auto-scoped.
- **State modifier classes**: Some components use `.is-active`, `.is-blocked`, `.is-expanded` as modifier classes. Inside a module, these must be marked as global escapes to avoid being scoped, since they are applied dynamically as string literals.
- **Test assertions on class names**: ~100 unit test assertions use `querySelector(".ht-...")`. After migration, module class names are no longer predictable string literals in production. Tests must use `data-testid` attributes instead. The test environment can be configured to pass class names through un-hashed, but this creates a false sense of safety.
- **End-to-end test selectors**: ~75 Playwright selectors in Python test files reference `.ht-*` classes. These must also migrate to `data-testid`, which requires adding `data-testid` attributes to components that don't have them yet.
- **Components receiving class props**: Some components accept a `class` or `className` prop from parents (e.g., `TableCard` receives `className`). These external classes remain global strings; the component's own internal styles use modules.
- **Multi-file class ownership ambiguity**: Some classes appear in 2 files — one renders the class, the other queries it. The class belongs in the module of the component that renders it. The querying file either uses the component (class is encapsulated) or needs a shared module.
- **Components with no component-specific CSS**: Some components (e.g., `icons.tsx`, `error-boundary.tsx`) may use only global classes and have no component-specific styles to extract. These components do not get a `.module.css` file — no empty modules.
- **Migration batch introduces a regression**: If the e2e suite fails after a migration batch, the batch is reverted (`git revert`), the failing component is investigated individually, and the fix is applied before re-attempting. Batches are small enough (3-8 components) that bisecting is trivial.

## Acceptance Criteria

- **AC#1** The shared stylesheet (`global.css`) is under 500 lines (FR#1)
- **AC#2** Every component and page file that previously referenced component-specific classes from the shared stylesheet has a co-located `.module.css` file (FR#1)
- **AC#3** TypeScript compilation (`tsc --noEmit`) succeeds with no errors related to module imports (FR#3)
- **AC#4** The full end-to-end test suite passes with zero regressions (FR#6, FR#7)
- **AC#5** The full unit test suite passes with zero regressions (FR#11)
- **AC#6** No unit test file queries a class that has been migrated to a module; queries for classes in the "stays global" table remain valid. State assertions (active, expanded, blocked) use ARIA attributes (`aria-current`, `aria-expanded`) instead of class-based checks (FR#11)
- **AC#7** A CI script exits non-zero when a new component-specific selector is added to the shared stylesheet (FR#9)
- **AC#8** A CI script reports unused selectors in the shared stylesheet (FR#10)
- **AC#9** `tokens.css` is byte-identical before and after migration
- **AC#10** Playwright screenshot baselines are established before Batch 1 at 1440px, 900px, 768px, and 375px viewports in both themes for key pages (apps, app-detail, mobile sidebar). After each batch, `expect(page).to_have_screenshot()` assertions pass with no pixel-level regressions (FR#6, FR#7)
- **AC#11** No `.module.css` file contains the `ht-` prefix in its class names (FR#13)
- **AC#12** Two components that independently define a class named `.row` in their respective modules produce no naming collision in the rendered output (FR#2)
- **AC#13** At least one component renders an element with both a global class and a module-scoped class on the same element, and both styles apply correctly (FR#4)
- **AC#14** The `clsx` package is listed in `package.json` dependencies and is used in at least one component to compose conditional classes (FR#14)

## Key Constraints

- **Preact uses `class=` not `className=`** — all examples and patterns must use `class=` with template literals or the composition utility, not React's `className=`
- **No bulk migration** — components must be migratable individually or in small batches. At any point during migration, the shared stylesheet and module files must coexist without conflict
- **Shared classes must not move to modules** — classes used across 3+ component files (`ht-btn`, `ht-card`, `ht-table`, `ht-badge`, `ht-chip`, `ht-text-*`, `ht-pill`) stay global. Moving them would force every consumer to import a shared module, which is a design system extraction project, not a CSS co-location project
- **No new runtime dependencies beyond `clsx`** — `clsx` (330 bytes, zero dependencies) is justified by the volume of conditional class composition. No CSS-in-JS, no styled-components, no Tailwind

## Dependencies and Assumptions

- **Vite's native CSS Modules support**: Vite processes `*.module.css` files automatically with scoped class names. No configuration change needed.
- **Vitest CSS module proxy**: Vitest returns un-hashed class names from module imports by default (proxy behavior). Tests that check `styles.sidebar` get `"sidebar"`. No special configuration needed for class name assertions, though `css.modules.classNameStrategy: "non-scoped"` can be added if CSS rules need to apply in jsdom.
- **`clsx` package**: 330 bytes gzipped, zero dependencies. Standard in the Preact/React ecosystem for conditional class composition.
- **`vite-css-modules` plugin**: Generates per-class `.d.ts` files for CSS modules, providing TypeScript autocomplete and build-time error detection for nonexistent class names.
- **Existing `data-testid` coverage**: 132 `data-testid` attributes already exist across component files. The pattern is established; some components will need new testid attributes added.
- **Playwright e2e suite**: Used as the primary visual regression gate. Must pass at baseline before migration begins.

## Architecture

### Infrastructure changes

**Typed CSS Modules** (`vite-css-modules` plugin):
Added in Batch 1 alongside the first `.module.css` files. Generates a `.d.ts` file per module with per-class exports, providing autocomplete and build-time errors for typos (`styles.tyop` is a compile error, not a silent string). Configured in `vite.config.ts`:
```typescript
import { patchCssModules } from 'vite-css-modules';
// Update the plugins array in defineConfig:
plugins: [preact(), patchCssModules({ generateSourceTypes: true })]
```
Generated `.d.ts` files are gitignored — the dev server and build step regenerate them. The `lint.yml` CI workflow must be updated to run `npm run build` before `npx tsc --noEmit` so that `.d.ts` files are on disk when type checking runs. Without this step, every module import produces `TS2307: Cannot find module`.

**Conditional class composition** (`clsx` dependency):
Added to `package.json`. Used wherever an element combines multiple classes with boolean conditions:
```tsx
import styles from './sidebar.module.css';
// Mixing global + module + conditional
<div class={clsx(styles.appItem, isActive && styles.active, isBlocked && "is-blocked")}>
```

**CI lint guard** (`tools/frontend/check_global_css_allowlist.py`):
A Python script that extracts all `.ht-*` selectors from `global.css`, compares against an allowlist of shared class prefixes, and fails if unknown selectors are found. Added to CI pipeline (`lint.yml`). The allowlist is maintained in the script. Includes a smoke test fixture (known-allowed + known-disallowed selectors) that runs in CI.

**`:global()` correctness check** (`tools/frontend/check_css_module_globals.py`):
A Python script that greps `.module.css` files for bare state modifier patterns (e.g., `.className.is-active` without `:global()`) and exits non-zero on match. Catches the silent failure where state modifier CSS is scoped instead of global.

**CI wiring** (`lint.yml` additions in Batch 1):
The frontend job in `lint.yml` must be updated to include:
```yaml
- name: Build frontend (generates CSS module .d.ts files)
  run: npm run build
- name: Type check
  run: npx tsc --noEmit
- name: Check CSS module :global() correctness
  run: uv run python tools/frontend/check_css_module_globals.py
- name: Check global CSS allowlist
  run: uv run python tools/frontend/check_global_css_allowlist.py
- name: Check dead global CSS (warning)
  run: uv run python tools/frontend/check_dead_global_css.py || true
```
The `npm run build` step must precede `tsc --noEmit` so generated `.d.ts` files exist when type checking runs. The allowlist guard runs in diff-only mode during migration (checks `git diff` against allowlist, not the full file) and upgrades to full-file mode after migration completes.

**Dead CSS detection** (`tools/frontend/check_dead_global_css.py`):
A Python script that extracts all class selectors from `global.css` and checks each against `.tsx` files. Reports any selector not referenced in any component. Maintains an annotated exemption list for known dynamically-assembled class families (`ht-badge--*`, `ht-chip--kind-*`, `ht-detail-stats-row__value--*`, `ht-stats-strip__value--*`) and third-party injected classes (`shiki`, `line`, `line--*`). Runs in CI as a warning during migration, upgraded to blocking after migration completes.

### Module file pattern

For each component, a co-located `.module.css` file contains all component-specific styles extracted from `global.css`. Class names drop the `ht-` prefix since module scoping provides isolation:

```css
/* Before (in global.css): .ht-sidebar__app-link */
/* After (in sidebar.module.css): */
.appLink {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
```

### Cross-component contextual rules

Rules where a global parent targets a module-scoped child use `:global()` syntax:

```css
/* sidebar.module.css */
:global(.ht-drawer) .sidebar {
  display: flex;
}

:global(.ht-layout) > .sidebar {
  display: none;
}
```

Rules where both classes are global (e.g., `.ht-layout > .ht-sidebar` when `ht-layout` stays global) — if the child moves to a module, the global.css rule must be removed and the rule moves to the child's module with `:global()` on the parent.

### State modifier classes

Dynamic state classes (`.is-active`, `.is-blocked`, `.is-expanded`) applied as string literals need `:global()`:

```css
.appItem:global(.is-active) {
  background: var(--bg-active);
}
```

### Dark theme overrides

Component-specific theme overrides use `:global()` on the attribute selector:

```css
/* code-tab.module.css */
:global([data-theme="dark"]) .body :global(.shiki) span {
  color: var(--shiki-dark) !important;
}
```

Theme overrides for shared global classes (`.ht-card`, etc.) stay in `global.css`.

### Responsive media queries

In Batch 1 (infrastructure), the mixed media query blocks in `global.css` are decomposed into per-component sections with ownership annotations — still in `global.css`, but separated so each batch can grab its labeled block without parsing a mixed block. Each section header names the owning component and the batch that will migrate it (e.g., `/* ht-theme-toggle — owner: status-bar — migrates in Batch 3 */`). Single-file classes that belong to a specific component (`ht-theme-toggle`, `ht-tab-btn`, `ht-tier-toggle__btn`, `ht-time-preset-selector__btn`) must be labeled with their owner — they are NOT shared and must migrate with their component. Shared class responsive adjustments (`ht-btn--sm`, `ht-hamburger`, `ht-layout`, `ht-main`) stay in a "shared — permanent" section.

Each subsequent component batch moves its labeled responsive block from `global.css` into the component's module:

```css
/* sidebar.module.css */
@media screen and (max-width: 900px) {
  :global(.ht-layout) > .sidebar {
    display: none;
  }
}
```

### Test migration pattern

Unit tests replace class selectors with `data-testid`, and state assertions migrate from class checks to ARIA attributes:

```tsx
// Before
expect(container.querySelector(".ht-spinner")).not.toBeNull();
expect(el.className).toContain("is-active");

// After
expect(container.querySelector("[data-testid='spinner']")).not.toBeNull();
expect(el.getAttribute("aria-current")).toBe("page");
```

Components that lack `data-testid` attributes get them added as part of the migration. Components that apply `is-active`/`is-expanded`/`is-blocked` classes must also set the corresponding ARIA attributes (`aria-current`, `aria-expanded`, etc.) so tests can assert on semantic state rather than styling implementation.

### Migration order

**Atomic migration rule**: each batch commit must include the corresponding e2e test file updates. Pre-batch checklist: `grep -rn '\.ht-' tests/e2e/` for class names owned by this batch's components — all must be migrated to `data-testid` in the same PR. The e2e suite cannot serve as a regression gate if its own selectors reference hashed class names.

Components are migrated in batches ordered by risk (lowest first):

1. **Leaf components**: `spinner`, `empty-state`, `show-more-button`, `mini-sparkline`, `status-shape`, `app-link` — minimal cross-references, simple CSS. Validates the mechanics.
2. **Self-contained shared**: `confirm-dialog`, `error-banner`, `action-buttons`, `sort-header`, `tier-toolbar`, `time-preset-selector`, `stats-strip` — used by multiple pages but all classes are rendered only within the component.
3. **Layout shell**: `sidebar`, `status-bar`, `alert-banner`, `command-palette`, `table-card` — complex internal structure, cross-component contextual rules, responsive overrides. Sidebar is the single highest-risk component. **Critical sidebar checklist**: (1) Add `data-testid="sidebar"` to the root `<aside>` element — 5 e2e locators use `.ht-sidebar` directly and need a migration target. Add `data-testid` to sub-elements used as e2e locators (`.ht-sidebar__app-nav`, `.ht-sidebar__group-header`, `.ht-sidebar__app-link`, `.ht-sidebar__app-expand`, `.ht-sidebar__instance-list`). (2) Verify `:global(.ht-drawer) .sidebar { display: flex }` is present in `sidebar.module.css` and the corresponding global rule at `global.css:1968` is deleted. Test at ≤900px viewport with mobile drawer open — this rule makes the sidebar visible in the mobile drawer; if missed, the sidebar silently disappears at mobile viewports.
4. **Pages**: `apps`, `handlers`, `logs`, `diagnostics`, `config`, `not-found` — page-level classes, often mixing global layout primitives with page-specific styles.
5. **App-detail tree**: `app-detail` (page), `handlers-tab`, `overview-tab`, `unified-handler-row`, `handler-invocations`, `job-executions`, `handler-list`, `health-strip`, `code-tab`, `config-tab`, `error-cell` — the most inter-dependent component tree with shared tab-strip styles.
6. **Infrastructure finalization**: lint guard activation (blocking), dead CSS detection activation (blocking), audit of remaining `global.css` content.

### Ambiguous class adjudication

Classes used in exactly 2 files that span different migration batches:

| Class | Files | Decision | Rationale |
|-------|-------|----------|-----------|
| `ht-log-level-badge` | `log-table.tsx`, `overview-tab.tsx` | Moves to `log-table.module.css` | LogTable is the canonical owner; overview-tab imports the `<LogTable>` component (badge is encapsulated) |
| `ht-traceback` | `error-banner.tsx`, `error-cell.tsx`, `job-executions.tsx` | Stays global (3 files) | Used across 3 components in different subtrees |
| `ht-table-toolbar*`, `ht-table-card-scroll` | `log-table.tsx`, `table-card.tsx` | Stays global | Both components render toolbar markup independently; shared UI pattern |
| `ht-card--config` | `config.tsx`, `config-tab.tsx` | Stays global | `ht-card` modifier used across 2 files in different batches (T06/T08); migrating in one batch breaks the other |

Classes that appear in 0 files (orphaned — candidates for pre-migration cleanup): `ht-error-feed`, `ht-error-entry`, `ht-group-filter-bar`, `ht-group-chip`.

### What stays in global.css (~400 lines target)

| Category | Examples | Approx lines |
|----------|---------|-------------|
| Font-face declarations | `@font-face` blocks for Newsreader, Geist | ~65 |
| Reset + base typography | `*`, `body`, `h1`-`h4`, `a`, `code`, `::selection` | ~170 |
| Layout primitives | `ht-layout`, `ht-main`, `ht-page`, `ht-section`, `ht-page-header` | ~50 |
| Layout helpers | `ht-grid`, `ht-level`, `ht-flex` | ~30 |
| Design system | `ht-btn`, `ht-card`, `ht-table`, `ht-badge`, `ht-chip`, `ht-pill`, `ht-search` | ~200 |
| Utilities | `ht-text-*`, `ht-mb-*`, `ht-visually-hidden`, `ht-skip-link` | ~60 |
| Shared animations | `@keyframes ht-breathe`, `ht-pulse`, `ht-spin` | ~20 |
| Accessibility | `:where(:focus-visible)`, `prefers-reduced-motion` | ~15 |
| Mobile shell | `ht-hamburger`, `ht-drawer`, `ht-drawer-backdrop` | ~30 |
| Theme overrides (shared) | `[data-theme="light"] .ht-card` | ~15 |

## Alternatives Considered

### Keep global.css with better organization (section comments, IDE folding)

The status quo with improved navigation. Add region markers, a table of contents, or CSS custom media queries for organization.

Rejected because: does not solve the core problem. Orphaned CSS still accumulates, duplication is still invisible, and there's no type safety or CI enforcement. The TODO comment at line 1 of `global.css` already acknowledges this approach was always temporary.

### CSS-in-JS (styled-components, Emotion, Goober)

Runtime style generation co-located with components. Eliminates the separate CSS file entirely.

Rejected because: adds runtime overhead, changes the styling paradigm entirely (not just the file structure), and is moving out of favor in the ecosystem. Overkill for this project — the problem is file organization, not the CSS language itself.

### Tailwind CSS

Utility-first CSS framework. Eliminates custom CSS classes almost entirely.

Rejected because: would require rewriting every component's class references — a visual redesign's worth of effort for what should be a structural migration. The existing design system (Newsreader headings, custom tokens, BEM-structured components) would fight Tailwind's conventions.

### Scope the migration to the worst offenders only

Migrate only the largest components (sidebar, log-table, apps, app-detail) and leave smaller components in `global.css`.

Rejected because: partial migration creates a permanent dual system. Contributors must check both global.css and module files. The lint guard can't be activated because legitimate component classes still live in global.css. The Expand scope mode was chosen specifically to finish the job.

## Test Strategy

**Per-batch verification baseline** — all three commands must pass after every batch:
1. `cd frontend && npm run build` — confirms TypeScript compiles, CSS modules generate `.d.ts` files, no broken imports
2. `cd frontend && npx vitest run` — unit tests pass (broken imports, missing `data-testid`, ARIA assertions)
3. `nox -s frontend && nox -s e2e` — rebuild SPA then run Playwright e2e + screenshot baselines (visual regressions)

Running `nox -s e2e` alone will test the previously-built SPA, not the current CSS — always rebuild first via `nox -s frontend`.

**Snapshot baseline setup (Batch 1 prerequisite):** Before any component migration, establish Playwright screenshot baselines:
1. Add `.gitignore` exception: `!tests/e2e/**-snapshots/*.png` (blanket `*.png` rule blocks snapshot PNGs otherwise)
2. Create dedicated snapshot test functions targeting apps, app-detail (all tabs: overview, handlers, code, config), and mobile sidebar at 1440px, 900px, 768px, and 375px viewports in both themes
3. Generate baselines on Ubuntu (the CI platform) to avoid OS rendering divergence: `pytest --update-snapshots`
4. Commit the generated `tests/e2e/*-snapshots/` directory
5. Add `--update-snapshots` as a manual `workflow_dispatch` step in `e2e-tests.yml` for future baseline updates Tests cover navigation, responsive behavior, theme switching, and data display across all pages. All tests that pass at baseline must pass after each batch.

**Unit test suite** — run after each batch. Validates that component rendering, event handling, and data display work correctly. Tests are updated per-component to replace class selectors with `data-testid`.

**TypeScript compilation** — `tsc --noEmit` after each batch. Catches missing module imports, unused style references (with `noUnusedLocals`), and type errors in class composition.

**Manual visual check** — for the sidebar and app-detail batches (highest risk), take Playwright screenshots at 1440px, 900px, 768px, and 375px in both themes before and after migration.

**Key behaviors to verify per batch:**
- Responsive breakpoint transitions (hamburger menu appears at 900px, layout adjusts at 768px)
- Theme toggle works (dark↔light)
- Conditional classes respond to state changes (active, expanded, dimmed)
- Animations play correctly (spinner, pulse dot, breathing indicator)
- Hover states and focus indicators render correctly

## Documentation Updates

- **`CLAUDE.md`**: Add a "CSS Architecture" section describing the module pattern, the convention for adding new component styles, and the `:global()` patterns for cross-component rules
- **`design/context.md`**: No changes needed — design tokens are in `tokens.css` which is untouched
- **Component READMEs**: None needed — the co-located `.module.css` files are self-documenting

## Impact

**Files created:** ~38 new `.module.css` files (one per component/page)

**Files modified:**
- ~38 `.tsx` component/page files (add module import, replace class string literals)
- ~30 `.test.tsx` unit test files (replace `querySelector(".ht-...")` with `data-testid` queries)
- ~12 `tests/e2e/*.py` files (replace `.ht-*` selectors with `data-testid`)
- `frontend/src/global.css` (reduce from ~4600 to ~500 lines)
- `frontend/package.json` (add `clsx`, `vite-css-modules`)
- `frontend/vite.config.ts` (add `patchCssModules` plugin)
- `frontend/vitest.config.ts` (add CSS module config if needed)
- `frontend/tsconfig.json` or new `frontend/src/css-modules.d.ts` (ambient type declaration)

**Files created (tooling):**
- `tools/frontend/check_global_css_allowlist.py` (CI lint guard)
- `tools/frontend/check_dead_global_css.py` (dead CSS detection)
- `tools/frontend/check_css_module_globals.py` (`:global()` correctness check)

**Files modified (CI):**
- `.github/workflows/lint.yml` (add `vite build` before `tsc`, add CSS guard steps)

<!-- Gap check 2026-05-11: 2 gaps included — .gitignore (PNG exception, line 230) → T01 step 4, e2e-tests.yml (--update-snapshots) → T01 step 9. hooks/use-media-query.ts has global.css comments — informational only, values unchanged. -->

**Blast radius:** High — touches every frontend component file. Mitigated by incremental migration with e2e gates between batches. No backend changes. No API changes. No data model changes.

## Open Questions

(None — all technical questions resolved by research brief. Decisions captured in Architecture section.)
