# Design: Convert CSS Modules to Tailwind Utilities

**Date:** 2026-07-27
**Status:** draft
**Scope-mode:** expand
**Research:** design/research/2026-07-27-frontend-migration-part-two/brief.md

## Problem

The frontend still carries 54 CSS Module files (~3,700 lines) and 6 global CSS files (~690 lines) alongside the Tailwind v4 + shadcn/ui stack landed in specs 020 and 088. Every component has a co-located `.module.css` that duplicates what Tailwind utilities express in a single `className` string. This dual system creates three concrete costs:

1. **Cognitive overhead** — contributors must decide whether to write a CSS Module class or a Tailwind utility for every style declaration. AI agents produce inconsistent output because neither approach is canonical.
2. **Token indirection** — `tokens.css` (284 lines, 136 custom properties) defines the source-of-truth values, `global.css` aliases them to shadcn names, and CSS Modules reference the old names. Three layers for one value.
3. **Lint tool burden** — 6 prek hooks guard CSS Module / global CSS conventions (`check_css_module_globals`, `check_dead_global_css`, `check_global_css_allowlist`, `check_undefined_css_refs`, `check_dead_tokens`, `check_breakpoint_drift`). At least 4 become unnecessary once CSS Modules are gone.

Spec 088's Non-Goals section explicitly deferred this work to "PR 2." This spec is PR 2.

## Goals

- All 54 CSS Module files are deleted; their styles are expressed as Tailwind utility classes in the TSX.
- Tailwind Preflight replaces `styles/reset.css`.
- The 6 global CSS files in `styles/` are removed or consolidated into Tailwind `@layer base` rules in `global.css`.
- `tokens.css` is removed; all token values are defined directly in `global.css`'s `:root` / `[data-theme="dark"]` blocks (which the `@theme inline` block already references).
- CSS lint tools that guard CSS Module conventions are removed from prek and CI.
- Remaining `clsx` imports are migrated to `cn()`.
- React StrictMode is enabled; double-effect issues are fixed.
- Visual parity with the current UI is maintained.
- All vitest tests pass.
- The E2E suite (`nox -s e2e`) passes.

## Non-Goals

- Rewriting `design/context.md` for the new stack vocabulary (PR 3).
- Regenerating doc screenshots (PR 3).
- Changing the routing library, data fetching layer, or WebSocket protocol.
- Adding new Tailwind plugins or custom utilities beyond what the existing token set requires.
- Changing any component's rendered DOM structure or behavior — this is a styling-only migration.

## User Scenarios

### Jessica: Solo developer + AI agents

- **Goal:** Single styling approach — Tailwind utilities everywhere, no CSS Modules to maintain

#### CSS Module conversion

1. **Verify a converted component renders identically**
   - Sees: component before and after conversion side-by-side (demo stack)
   - Decides: whether visual parity is acceptable
   - Then: the CSS Module file is deleted, the TSX uses Tailwind utilities

2. **Write new styles in future work**
   - Sees: no CSS Module files, all styling via Tailwind utilities and `cn()`
   - Decides: which Tailwind utilities to use
   - Then: one approach, one mental model, consistent AI output

## Functional Requirements

- **FR#1** All 54 CSS Module files are deleted. Their styles are expressed as Tailwind utility classes in the corresponding TSX files using `cn()`.
- **FR#2** Tailwind Preflight is imported (`@import "tailwindcss/preflight.css"` in `global.css`). `styles/reset.css` is deleted. Any hassette-specific reset rules not covered by Preflight (focus indicator, reduced motion) are preserved in `global.css` via `@layer base`.
- **FR#3** `styles/typography.css` is removed. Base typography rules (`body`, `h1`–`h4`, `code`, `pre`, `a`, `strong`, `::selection`) move to `@layer base` in `global.css`.
- **FR#4** `styles/tables.css` is removed. Table styles (`.ht-table`, `.ht-table--compact`, `.ht-table--fixed`, `.ht-table-card-scroll`) move to Tailwind utilities at the component call sites or, where they define a reusable table convention used by 3+ components, to `@layer components` in `global.css`.
- **FR#5** `styles/layout.css` is removed. Layout classes (`.ht-layout`, `.ht-main`, `.ht-page`, `.ht-section`, `.ht-page-header`, `.ht-level`) move to Tailwind utilities at their TSX call sites. Responsive breakpoint rules are expressed via Tailwind's responsive prefixes (`max-md:`, `max-sm:`).
- **FR#6** `styles/utilities.css` is removed. All `.ht-*` utility classes are replaced by equivalent Tailwind utilities at each call site (e.g., `.ht-text-muted` → `text-muted-foreground`, `.ht-mb-2` → `mb-2`, `.ht-visually-hidden` → `sr-only`).
- **FR#7** `styles/fonts.css` is preserved (moved into `global.css` or kept as a standalone import). `@font-face` declarations cannot be expressed as Tailwind utilities.
- **FR#8** `tokens.css` is deleted. All token values (`:root` and `[data-theme="dark"]` blocks) are inlined into `global.css`, which already contains the shadcn alias layer. The `@theme inline` block references these values directly.
- **FR#9** Remaining `clsx` imports (10 files) are migrated to `cn()` from `@/lib/utils`. The `clsx` package is removed from `package.json` (it stays as a transitive dependency of `tailwind-merge` via `cn()`).
- **FR#10** CSS lint tools that guard CSS Module conventions are removed: `check_css_module_globals.py`, `check_dead_global_css.py`, `check_global_css_allowlist.py`, `check_undefined_css_refs.py`. Their prek hook definitions are removed from `prek.toml`. Their CI references are removed from `.github/workflows/lint.yml`.
- **FR#11** `check_dead_tokens.py` is updated to scan `global.css` (the new single source of token definitions) instead of `tokens.css`. `check_breakpoint_drift.py` is evaluated — kept if it still has value (JS/CSS breakpoint constants still need to match even with Tailwind), removed if it no longer applies.
- **FR#12** React StrictMode is enabled by wrapping the root render in `<StrictMode>`. Any double-effect issues surfaced by StrictMode are fixed.
- **FR#13** All `className` composition uses `cn()` (from `@/lib/utils`), never raw string concatenation, `clsx()`, or template literals for conditional classes.

## Edge Cases

- **Animations and keyframes** — CSS Modules that define `@keyframes` (e.g., `spinner.module.css`) cannot be expressed as pure Tailwind utilities. These use Tailwind's `animate-*` utilities with custom keyframe definitions in `global.css` via `@theme` or `@keyframes` in a `@layer base` block.
- **`:global()` overrides** — Some CSS Modules use `:global()` to target global classes from within a module scope (e.g., `.tableWrapper :global(.ht-table) tbody tr:hover`). When both the module and the global class are removed, these overrides either move to the component's `className` or become unnecessary.
- **Complex selectors** — CSS Modules with descendant selectors, pseudo-elements, or `nth-child` logic may not have clean Tailwind equivalents. These use Tailwind's arbitrary value syntax (`[&>:first-child]:pt-0`) or a minimal `@layer components` rule in `global.css`.
- **CSS custom properties scoped to a module** — Some modules define component-local CSS variables (e.g., `--health-card-height`, `--log-scroll-max-height`). These move to inline `style` attributes or Tailwind arbitrary values.
- **Responsive breakpoints in modules** — CSS Modules with `@media` queries use Tailwind responsive prefixes. The project uses non-standard breakpoints (900px for sidebar, 768px for mobile, 480px for small mobile) — these are registered as custom Tailwind screens in `@theme`.
- **StrictMode double-effects** — `useEffect` hooks that don't clean up subscriptions or timers will fire twice in development. The most likely candidates are WebSocket connections and event listeners in layout components.
- **Preflight vs. current reset differences** — Preflight resets `button` styles (removes background, border, padding) more aggressively than the current reset. Components that rely on un-reset button defaults may need explicit Tailwind classes after Preflight adoption. Preflight also adds `border-style: solid` and `border-width: 0` to all elements, which may affect components using `border` shorthand.

## Acceptance Criteria

- **AC#1** `find frontend/src -name '*.module.css' | wc -l` returns 0.
- **AC#2** `ls frontend/src/styles/reset.css frontend/src/styles/typography.css frontend/src/styles/tables.css frontend/src/styles/layout.css frontend/src/styles/utilities.css frontend/src/tokens.css 2>/dev/null | wc -l` returns 0.
- **AC#3** `cd frontend && npm run build` exits 0.
- **AC#4** `cd frontend && npm run test` reports 0 failures.
- **AC#5** `cd frontend && npm run typecheck` exits 0.
- **AC#6** `grep -rn 'from "clsx"' frontend/src/ | grep -v 'lib/utils.ts' | wc -l` returns 0. All className composition uses `cn()`. (`lib/utils.ts` legitimately imports `clsx` as the internal implementation of `cn()`.)
- **AC#7** `ls frontend/src/styles/fonts.css 2>/dev/null | wc -l` returns 1 (font declarations preserved).
- **AC#8** `grep -rn "import.*\.module\.css" frontend/src/ | wc -l` returns 0.
- **AC#9** `ls tools/frontend/check_css_module_globals.py tools/frontend/check_dead_global_css.py tools/frontend/check_global_css_allowlist.py tools/frontend/check_undefined_css_refs.py 2>/dev/null | wc -l` returns 0.
- **AC#10** `uv run nox -s e2e` passes.
- **AC#11** Demo stack (`mise run demo`) renders all pages without visual regression.
- **AC#12** `grep -n 'StrictMode' frontend/src/main.tsx` returns a match.
- **AC#13** `prek -a` passes (all remaining lint hooks clean).

## Key Constraints

- **Do not change component behavior or DOM structure.** This is a styling-only migration. If a component renders `<div><span>text</span></div>`, it must still render that after conversion. Wrapper elements may be removed only when they existed solely to attach a CSS Module class and the Tailwind class can go on the parent.
- **Do not introduce new design tokens or change visual output.** The converted component must render pixel-identical to the CSS Module version. Every Tailwind utility must map to the same CSS property and value the module class produced.
- **Preserve all responsive behavior.** Every `@media` query in a CSS Module must have an equivalent Tailwind responsive prefix. Register custom screens in `@theme` for non-standard breakpoints.
- **Do not remove `tokens.css` until all direct `var(--old-name)` references are eliminated.** The alias layer in `global.css` bridges old → new names, but CSS Modules still reference old names directly. `tokens.css` can only be removed after all CSS Module files are deleted and all remaining CSS references use the new (shadcn-aliased) names.
- **The `@font-face` declarations must survive.** Self-hosted font files (Newsreader, Geist, Geist Mono) are not available via Tailwind's font stack or any CDN. The `@font-face` rules from `styles/fonts.css` must be preserved, either in `global.css` or as a standalone import.

## Dependencies and Assumptions

- **Tailwind v4** (`@tailwindcss/vite`) is already installed and configured on `frontend-migration`.
- **`cn()` utility** at `src/lib/utils.ts` already exists (from shadcn init).
- **shadcn token aliases** in `global.css` already bridge old token names → shadcn names (from spec 088).
- **`@theme inline`** block in `global.css` already registers colors and radii — spacing, typography, and other tokens may need additional `@theme` registrations.
- **Docker + Playwright** required for AC#10 and AC#11.
- **The `frontend-migration` branch** is the target — this PR does not go to `main` directly.

## Architecture

### Phase 1: Foundation — Preflight + theme registration

Before any CSS Module can be converted, two things must be in place:

1. **Tailwind Preflight** replaces the hand-rolled reset. Compare Preflight's output with `styles/reset.css` line by line. Identify differences (Preflight is more aggressive on `button`, `input`, `img`, and adds `border-style: solid` + `border-width: 0` to all elements). Preserve hassette-specific rules (focus indicator via `:where(:focus-visible)`, reduced motion `@media`) in `@layer base`. Import Preflight in `global.css` (change `@import "tailwindcss/theme.css"` / `@import "tailwindcss/utilities.css"` to `@import "tailwindcss"` which includes Preflight). Delete `styles/reset.css`.

2. **Custom screens** for non-standard breakpoints: register `sidebar` (900px), `mobile` (768px), and `small-mobile` (480px) in the `@theme` block so responsive prefixes like `max-sidebar:`, `max-mobile:`, `max-small-mobile:` work.

3. **Verify spacing alignment** — Tailwind v4's default spacing uses `--spacing: 0.25rem` as a multiplier (`p-4` = `calc(0.25rem * 4)` = `1rem`). Confirm this matches hassette's `--sp-*` scale. If the scales align, Tailwind's built-in spacing utilities work out of the box. If they don't, register custom spacing values in `@theme`.

After this phase, all Tailwind utilities resolve correctly and Preflight is the only reset.

### Phase 2: CSS Module conversion — batch by directory

The conversion is mechanical per file:

1. Read the `.module.css` file
2. For each CSS class, identify the equivalent Tailwind utilities
3. In the TSX, replace `styles.className` references with `cn("tailwind-classes")`
4. Remove the `import styles from "./component.module.css"` line
5. Delete the `.module.css` file

**Conversion patterns:**

| CSS Module pattern | Tailwind equivalent |
|---|---|
| `var(--sp-3)` / `var(--spacing-3)` | `p-3`, `m-3`, `gap-3` |
| `var(--ink-1)` / `var(--foreground)` | `text-foreground` |
| `var(--ink-3)` / `var(--muted-foreground)` | `text-muted-foreground` |
| `var(--bg-surface)` / `var(--card)` | `bg-card` |
| `var(--line-1)` / `var(--border)` | `border-border` |
| `var(--accent)` / `var(--primary)` | `text-primary` |
| `var(--err)` / `var(--destructive)` | `text-destructive` |
| `var(--fs-small)` | `text-sm` (or custom `text-small` if scale doesn't align) |
| `var(--fw-medium)` | `font-medium` |
| `var(--font-mono)` | `font-mono` |
| `var(--r-md)` | `rounded-md` |
| `display: flex; flex-direction: column; gap: var(--sp-3)` | `flex flex-col gap-3` |
| `white-space: nowrap; overflow: hidden; text-overflow: ellipsis` | `truncate` |
| `font-size: var(--fs-micro); color: var(--ink-3)` | `text-xs text-muted-foreground` |

**Directory batches** (ordered by dependency — components used by pages come first):

1. **shared/** — 26 files, 1,567 lines (includes log-table subsystem). These components are imported by pages and other components, so converting them first means page conversions can use the new API.
2. **app-detail/** — 14 files, 934 lines. Heavy component area, uses many shared components.
3. **layout/** — 2 files, 160 lines. `alert-banner.module.css`, `status-bar.module.css`.
4. **design/** — 5 files, 250 lines. Component showcase and token display pages.
5. **pages/** — 7 files, 803 lines. Top-level page components.

**Files requiring special handling:**

- `spinner.module.css` — has `@keyframes spin`. Use Tailwind's built-in `animate-spin` or register the keyframe in `@theme`.
- `log-detail-drawer.module.css` (298 lines) — largest single file. Complex layout with responsive behavior and nested selectors.
- `config-schema-view.module.css` (204 lines) — complex nested object display with recursive indentation.
- `mini-sparkline.module.css` — SVG-specific styling; may need inline styles or arbitrary values.

### Phase 3: Global CSS removal

After all CSS Modules are converted, the global CSS files can be removed:

1. **`styles/reset.css`** — already deleted in Phase 1 (Preflight).
2. **`styles/typography.css`** — base element styles (`body`, `h1`–`h4`, `code`, `pre`, `a`, `strong`, `::selection`). Move to `@layer base` in `global.css`.
3. **`styles/tables.css`** — `.ht-table` convention. Evaluate: if the table styles are still used by shadcn Table components or any remaining table markup, move to `@layer components` in `global.css`. If all table consumers now use TanStack Table + shadcn Table (from spec 088), delete entirely.
4. **`styles/layout.css`** — `.ht-layout`, `.ht-main`, `.ht-page` etc. These are used in `app.tsx` and page components. Move to Tailwind utilities at the call sites. The responsive `@media` rules use Tailwind responsive prefixes.
5. **`styles/utilities.css`** — all `.ht-*` utility classes. Replace each with the equivalent Tailwind utility at every call site. After replacement, delete the file.
6. **`styles/fonts.css`** — kept. `@font-face` declarations have no Tailwind equivalent.

After all `styles/*.css` files are handled, `tokens.css` can be deleted: inline all remaining `:root` / `[data-theme="dark"]` token definitions into `global.css` (many are already there via the alias layer — deduplicate the source values and the aliases into a single declaration set).

### Phase 4: Lint tool removal + CI update

Remove the 4 CSS-Module-specific lint tools:

| Tool | Why it's removed |
|---|---|
| `check_css_module_globals.py` | Guards `:global()` usage in `.module.css` — no more module files |
| `check_dead_global_css.py` | Finds unreferenced selectors in `styles/*.css` — no more style files |
| `check_global_css_allowlist.py` | Blocks new `.ht-*` selectors — no more `.ht-*` classes |
| `check_undefined_css_refs.py` | Finds raw `ht-*` refs in TSX with no CSS definition — no more `ht-*` refs |

Update `check_dead_tokens.py` to scan `global.css` instead of `tokens.css`. Evaluate `check_breakpoint_drift.py` — keep if JS/CSS breakpoint constants still need to match (the JS constants in `use-media-query.ts` and the Tailwind `@theme` screen registrations from Phase 1 must stay in sync).

Remove:
- The 4 tool scripts from `tools/frontend/`
- Their hook definitions from `prek.toml`
- The `check_global_css_allowlist.py --smoke-test` step from `.github/workflows/lint.yml`
- The prek `frontend` group definition if it becomes empty (or update it to only include surviving tools)

### Phase 5: StrictMode + cleanup

1. **Enable StrictMode** — wrap `<App />` in `<StrictMode>` in `main.tsx`. Run the dev server and check the console for double-effect warnings. Fix any effects that don't clean up properly.

2. **Migrate remaining `clsx` → `cn()`** — 10 files still import `clsx`. Replace with `cn()` from `@/lib/utils`. Remove `clsx` from `package.json` direct dependencies (it remains as a transitive dep of `tailwind-merge`).

3. **Clean up `global.css`** — after tokens.css is inlined and styles/*.css files are removed, `global.css` should be the single CSS file (plus `fonts.css`). Remove the alias layer comments that reference "PR 2" since this is PR 2. Remove `@import` lines for deleted files. Verify the file is well-organized: `@import tailwindcss` → `@font-face` or font import → `@theme inline` → `:root` tokens → `[data-theme="dark"]` tokens → `@layer base` (typography, focus, reduced-motion) → `@layer components` (if any reusable patterns survived).

## Implementation Preferences

- **`cn()` for all className composition** — never raw string concatenation, `clsx()`, or template literals.
- **Tailwind utility classes in JSX** — no `@apply` directives in CSS. If a pattern is too complex for inline utilities, use `@layer components` in `global.css` with a descriptive class name.
- **Preserve exact visual output** — this is a mechanical migration, not a redesign. Every pixel should match.
- **One `.module.css` file at a time** — convert and delete each file atomically. Do not leave a file partially converted.
- **Prefer Tailwind's built-in utilities** over arbitrary values (`[color:var(--custom)]`). Use arbitrary values only when no built-in utility exists for the token.

## Convention Examples

### CSS Module → Tailwind conversion (target convention)

**Before (CSS Module):**
```css
/* empty-state.module.css */
.empty { text-align: center; padding: var(--sp-6); }
.icon { font-size: var(--fs-h1); color: var(--ink-4); margin-bottom: var(--sp-2); }
.title { font-size: var(--fs-small); font-weight: var(--fw-medium); color: var(--ink-2); margin-bottom: var(--sp-1); }
.body { font-size: var(--fs-micro); color: var(--ink-3); max-width: var(--sz-content-narrow); margin: 0 auto; }
```

```tsx
// Before
import styles from "./empty-state.module.css";
<div className={styles.empty}>
  <div className={styles.icon}>{icon}</div>
  <div className={styles.title}>{title}</div>
  <div className={styles.body}>{body}</div>
</div>
```

**After (Tailwind utilities):**
```tsx
// After
<div className="text-center p-6">
  <div className="text-2xl text-foreground-faint mb-2">{icon}</div>
  <div className="text-sm font-medium text-foreground-secondary mb-1">{title}</div>
  <div className="text-xs text-muted-foreground max-w-[var(--size-content-narrow)] mx-auto">{body}</div>
</div>
```

### Conditional classes with cn() (target convention)

```tsx
import { cn } from "@/lib/utils";

<tr className={cn(
  "border-b border-border hover:bg-muted",
  isSelected && "bg-primary/10",
  isDisabled && "opacity-50 pointer-events-none",
)}>
```

### @layer base for typography (target convention)

```css
/* In global.css */
@layer base {
  body {
    font-family: var(--font-sans);
    font-size: var(--text-body);
    line-height: var(--text-body-leading);
    color: var(--foreground);
    background: var(--background);
  }

  h1 { font-family: var(--font-heading); font-size: var(--text-h1); line-height: var(--text-h1-leading); }
  h2 { font-size: var(--text-h2); line-height: var(--text-h2-leading); font-weight: var(--font-weight-semibold); }
}
```

## Alternatives Considered

### Keep CSS Modules, only remove the global CSS files

Retain CSS Modules for component-scoped styling but eliminate the `styles/` directory. **Rejected:** this preserves the dual-system cognitive overhead and the lint tools that guard the CSS Module conventions. The whole point is a single styling approach.

### Use `@apply` directives in CSS files instead of inline utilities

Write Tailwind utilities via `@apply` in `.css` files rather than in JSX. **Rejected:** `@apply` creates a CSS file that looks like Tailwind but doesn't benefit from Tailwind's purging, colocation, or readability advantages. It's the worst of both worlds — CSS files with Tailwind syntax.

### Convert in-place: rewrite CSS Module files as Tailwind `@layer` files

Keep the `.css` file structure but rewrite contents using `@apply`. **Rejected:** same issue as above, plus it maintains the file-per-component pattern that Tailwind's utility-first approach eliminates.

### Skip Preflight, keep the hand-rolled reset

Adopt Tailwind utilities without Preflight, keeping `styles/reset.css`. **Rejected:** Preflight and the hand-rolled reset overlap significantly. Keeping both creates specificity conflicts. Preflight is the standard baseline for Tailwind projects — diverging from it makes shadcn component styling unpredictable.

## Test Strategy

### Required Test Types

- **Unit (vitest):** All existing component tests must pass after CSS Module removal. Tests that assert on CSS Module class names (e.g., `expect(element.className).toContain(styles.active)`) must be updated to assert on Tailwind classes or behavior. Prefer behavior assertions over class name assertions.
- **E2E (Playwright via `nox -s e2e`):** Existing suite must pass — behavioral parity.
- **Visual QA (demo stack):** `mise run demo` → verify all pages render correctly.

### Existing Tests to Adapt

Tests that reference CSS Module imports or assert on scoped class names need updates:

- Any test importing `styles from "./<component>.module.css"` — remove the import, update assertions
- Tests using `styles.<className>` in assertions — replace with Tailwind class strings or switch to behavioral assertions (preferred)
- Tests using `getByClassName(styles.foo)` — replace with role/text queries (preferred) or Tailwind class strings

### New Test Coverage

None required — this is a styling-only migration with no behavior changes.

### Tests to Remove

None — all existing tests should still be valid (possibly with updated selectors).

## Documentation Updates

- **CLAUDE.md (CSS Architecture section):** Complete rewrite — remove all CSS Module references, remove "When to use styles/ vs a module" guidance, document the Tailwind-only approach. Update examples to show `cn()` with Tailwind utilities.
- **CLAUDE.md (Common Commands section):** No changes needed.
- **`design/context.md`:** Deferred to PR 3.

## Impact

### Changed Files

**Cross-cutting (highest risk):**
- modify `frontend/src/global.css` — inline tokens.css values, import Preflight, add `@layer base` typography, register custom screens in `@theme`, remove `@import` lines for deleted style files
- delete `frontend/src/tokens.css`
- modify `frontend/src/main.tsx` — wrap render in `<StrictMode>`
- modify `frontend/package.json` — remove `clsx` direct dependency

**Deleted files — CSS Modules (54 files):**
- delete `frontend/src/components/app-detail/code-tab.module.css`
- delete `frontend/src/components/app-detail/config-tab.module.css`
- delete `frontend/src/components/app-detail/detail-header.module.css`
- delete `frontend/src/components/app-detail/execution-detail.module.css`
- delete `frontend/src/components/app-detail/execution-section.module.css`
- delete `frontend/src/components/app-detail/handler-chips.module.css`
- delete `frontend/src/components/app-detail/handler-detail-layout.module.css`
- delete `frontend/src/components/app-detail/handler-health-card.module.css`
- delete `frontend/src/components/app-detail/handler-list.module.css`
- delete `frontend/src/components/app-detail/handlers-tab.module.css`
- delete `frontend/src/components/app-detail/job-detail.module.css`
- delete `frontend/src/components/app-detail/overview-tab.module.css`
- delete `frontend/src/components/app-detail/registration-footer.module.css`
- delete `frontend/src/components/app-detail/unified-handler-row.module.css`
- delete `frontend/src/components/design/color-tokens.module.css`
- delete `frontend/src/components/design/component-showcase.module.css`
- delete `frontend/src/components/design/section.module.css`
- delete `frontend/src/components/design/spacing-tokens.module.css`
- delete `frontend/src/components/design/typography-tokens.module.css`
- delete `frontend/src/components/layout/alert-banner.module.css`
- delete `frontend/src/components/layout/status-bar.module.css`
- delete `frontend/src/components/shared/action-buttons.module.css`
- delete `frontend/src/components/shared/app-link.module.css`
- delete `frontend/src/components/shared/breadcrumbs.module.css`
- delete `frontend/src/components/shared/config-schema-view.module.css`
- delete `frontend/src/components/shared/detail-panel.module.css`
- delete `frontend/src/components/shared/detail-stats.module.css`
- delete `frontend/src/components/shared/empty-state.module.css`
- delete `frontend/src/components/shared/error-banner.module.css`
- delete `frontend/src/components/shared/execution-logs.module.css`
- delete `frontend/src/components/shared/execution-table.module.css`
- delete `frontend/src/components/shared/icons.module.css`
- delete `frontend/src/components/shared/log-table/column-picker.module.css`
- delete `frontend/src/components/shared/log-table/log-detail-drawer.module.css`
- delete `frontend/src/components/shared/log-table/log-table-view.module.css`
- delete `frontend/src/components/shared/log-table/log-table.module.css`
- delete `frontend/src/components/shared/mini-sparkline.module.css`
- delete `frontend/src/components/shared/registration-source.module.css`
- delete `frontend/src/components/shared/show-more-button.module.css`
- delete `frontend/src/components/shared/sort-header.module.css`
- delete `frontend/src/components/shared/source-location.module.css`
- delete `frontend/src/components/shared/spinner.module.css`
- delete `frontend/src/components/shared/stats-strip.module.css`
- delete `frontend/src/components/shared/system-health.module.css`
- delete `frontend/src/components/shared/table-footer.module.css`
- delete `frontend/src/components/shared/theme-toggle.module.css`
- delete `frontend/src/components/shared/traceback-viewer.module.css`
- delete `frontend/src/pages/app-detail.module.css`
- delete `frontend/src/pages/apps.module.css`
- delete `frontend/src/pages/design.module.css`
- delete `frontend/src/pages/diagnostics.module.css`
- delete `frontend/src/pages/handlers.module.css`
- delete `frontend/src/pages/logs.module.css`
- delete `frontend/src/pages/not-found.module.css`

**Deleted files — Global CSS (5 files):**
- delete `frontend/src/styles/reset.css`
- delete `frontend/src/styles/typography.css`
- delete `frontend/src/styles/tables.css`
- delete `frontend/src/styles/layout.css`
- delete `frontend/src/styles/utilities.css`

**Deleted files — Lint tools (4 files):**
- delete `tools/frontend/check_css_module_globals.py`
- delete `tools/frontend/check_dead_global_css.py`
- delete `tools/frontend/check_global_css_allowlist.py`
- delete `tools/frontend/check_undefined_css_refs.py`

**Modified files — TSX (consumer updates, ~68 files):**
- All TSX files that import a `.module.css` file — replace CSS Module references with Tailwind utilities
- All TSX files that reference `ht-*` global classes — replace with Tailwind utilities
- 10 TSX files that import `clsx` — migrate to `cn()`

**Modified files — Config/CI:**
- modify `prek.toml` — remove 4 hook definitions, update `check_dead_tokens` if applicable
- modify `.github/workflows/lint.yml` — remove `check_global_css_allowlist.py --smoke-test` step
- modify `tools/frontend/check_dead_tokens.py` — update to scan `global.css`
<!-- Gap check 2026-07-27: 8 gaps included — handlers-rows.test.tsx:93 (ht-text-danger selector) → T05, app.test.tsx:110 (ht-main selector) → T05, app.test.tsx:121 (ht-skip-link selector) → T05, logs.test.tsx:70 (ht-display selector) → T05, alert-banner.test.tsx:53 (ht-text-secondary selector) → T05, log-table-view.test.tsx:55 (ht-table selector) → T05, table-card.test.tsx:70 (ht-table-card-scroll selector) → T05, tests/e2e/test_navigation.py:148 (a.ht-skip-link selector) → T05 -->

### Behavioral Invariants

- All existing page routes and URL structures must continue working.
- WebSocket connection, state management, and data fetching behavior must be unchanged.
- All responsive breakpoints must produce the same layout changes at the same pixel widths.
- Dark mode toggle must produce the same visual output.
- All keyboard shortcuts and focus management must be preserved.

### Blast Radius

- **E2E tests:** May need selector updates if tests reference CSS Module class names or `ht-*` classes.
- **Doc screenshots:** Will need regeneration (deferred to PR 3).
- **`design/context.md`:** References CSS Module conventions (deferred to PR 3).
- **CLAUDE.md:** CSS Architecture section needs a full rewrite (included in this spec).

## Open Questions

None — scope and approach are defined by the PR plan in the research brief.
