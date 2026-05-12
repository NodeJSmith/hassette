# Design: Shared UI Components (Button, Badge, Chip, Card)

**Date:** 2026-05-12
**Status:** archived
**Scope-mode:** expand

## Problem

The monitoring UI uses raw CSS class strings to style buttons, badges, chips, and cards. Every consumer manually assembles class names (`ht-btn ht-btn--ghost ht-btn--sm`), leading to two categories of pain:

1. **Bugs from missing or incorrect classes** — three buttons are missing the `type="button"` attribute (defaulting to submit), one navigation link is semantically mistyped as a button, and size/variant choices are inconsistent across pages showing the same data.
2. **Inconsistency tax** — each new feature requires re-learning which `ht-*` classes to combine, which sizes to use, and how to compose them. Different files use different construction methods (plain strings, template literals, `clsx`) for the same visual element. Two chip variants (`--auto` and `--muted`) have identical CSS but different names. Two badge variants (`--group` and `--cancelled`) exist in CSS but are never used.

This is the natural completion of the CSS Modules migration (#736), which moved component-specific CSS into `.module.css` files but left these four shared style files as global CSS because no component existed to own them.

## Goals

- Eliminate all direct `ht-btn`, `ht-badge`, `ht-chip`, and `ht-card` class usage from TSX files — all styling goes through component props
- Prevent the `type="button"` class of bug structurally — the component defaults it
- Consolidate inconsistent size and variant usage into a prop-driven API with sensible defaults
- Move CSS from `styles/*.css` into co-located `.module.css` files, completing the #736 migration
- Remove dead CSS (unused badge variants, duplicated chip variants)

## Non-Goals

- Table componentization (`styles/tables.css`, `ht-table-*` classes) — these are more complex (column width helpers, toolbar subcomponents) and are better addressed separately
- Layout or typography classes (`styles/layout.css`, `styles/typography.css`) — these are genuine global utilities, not component-scoped
- Redesigning the visual appearance of any component — this is a structural refactor, not a visual change

## User Scenarios

### Developer: automation author extending the monitoring UI

- **Goal:** Add a new UI element (button, status indicator, metadata label, or content container) that looks consistent with the rest of the application
- **Context:** Working in a TSX file, needs to render a styled element

#### Adding a status badge to a new view

1. **Import the Badge component**
   - Sees: TypeScript autocomplete showing available props (variant, size, children)
   - Decides: Which variant matches the semantic meaning (success, danger, warning, neutral)
   - Then: Renders `<Badge variant="success" size="sm">running</Badge>` — no class string assembly needed

#### Adding action buttons to a new panel

1. **Import the Button component**
   - Sees: Available props (variant, size, ghost, icon, disabled, etc.)
   - Decides: Which combination fits the context
   - Then: Renders `<Button variant="ghost" size="sm">view details</Button>` — `type="button"` is automatic

### Maintainer: reviewing a PR that touches UI

- **Goal:** Verify that new UI elements follow established patterns
- **Context:** Reading a diff in a pull request

#### Checking consistency of a new badge

1. **Read the component usage in the diff**
   - Sees: `<Badge variant="danger" size="sm">failing</Badge>` — variant and size are explicit props
   - Decides: Whether the variant choice is semantically correct for the data being displayed
   - Then: Approves or requests a variant change — no need to verify raw CSS class strings

## Functional Requirements

- **FR#1** A reusable Button component renders a `<button>` element with `type="button"` hardcoded — callers cannot override it to `type="submit"`
- **FR#2** The Button component accepts variant, size, ghost, and icon props that map to the existing visual styles without requiring manual class composition
- **FR#3** The Button component supports `disabled`, `ref` forwarding, `data-testid`, `aria-label`, `aria-expanded`, and `title` attributes via pass-through props
- **FR#4** A reusable Badge component renders a `<span>` element with variant and size props
- **FR#5** The Badge component accepts children that may include icons (e.g., StatusShape) alongside text
- **FR#6** A reusable Chip component renders a `<span>` element with a variant prop covering the semantic categories: modifier, schedule, kind, origin, and muted
- **FR#7** The Chip `kind` variant accepts a required `kind` prop (ok, warn, err, mute) that applies the corresponding border color and layout (gap + border-color per value). Callers pass `<StatusShape>` as a child — the component does not auto-render it, preserving the visual primitive boundary and keeping migration mechanical
- **FR#8** The Chip component accepts an `aria-label` pass-through for kind and origin variants
- **FR#9** A reusable Card component renders a `<div>` element with variant props (default, compact, config, error)
- **FR#10** The Card component supports `ref` forwarding and pass-through of `class`, `data-testid`, and `style` attributes
- **FR#11** All four component CSS files are co-located `.module.css` files — no global `ht-*` classes remain for these elements
- **FR#12** The existing `TableCard` component is refactored to compose the generic Card component internally
- **FR#13** Every TSX file that currently uses raw `ht-btn`, `ht-badge`, `ht-chip`, or `ht-card` class strings is migrated to use the corresponding component
- **FR#14** The `<a>` element in the not-found page is restyled as a standard link rather than a button-styled link
- **FR#15** Dead CSS variants (badge `--group`, badge `--cancelled`) are removed
- **FR#16** The duplicate chip variants `--auto` and `--muted` are merged into a single `muted` variant

## Edge Cases

- **ActionButtons conditional variants** — the stop button renders as `--warning` in icon mode but `--danger` in text mode. The component API must support this without falling back to raw class strings.
- **Confirm dialog refs** — the cancel and confirm buttons use `useRef` internally for focus management. Confirm-dialog owns its refs directly; it does not need to forward refs through Button. The Button component accepts an optional `ref` callback prop for other consumers that may need it.
- **Badge with icon child** — one badge instance (`app-detail.tsx:317`) embeds a `<StatusShape>` icon alongside text. The Badge component must handle mixed children without breaking layout.
- **Chip kind + StatusShape as children** — kind chips include a StatusShape icon passed as a child by callers. The component provides the border coloring and layout; callers control the icon. This keeps migration mechanical (children stay as-is) and avoids coupling Chip to a domain type.
- **Module CSS class composition** — components may need to accept an additional `class` prop for cases where consumers apply module-scoped layout styles alongside the component (e.g., `error-cell.tsx` adds `styles.tracebackToggle` to a button).
- **layout.css cross-references** — `layout.css:162–167` (768px breakpoint) targets `.ht-card > .ht-table` for horizontal table scrolling; `layout.css:189–191` (480px) overrides `.ht-card` padding on small phones. Both rules become dead CSS when `cards.css` is deleted. Move both into `card.module.css`: the table-scroll rule uses `.card :global(.ht-table)` (module class containing a global table class), and the 480px padding rule is a straightforward internal responsive override. Remove the original rules from `layout.css`.
- **Button group** — `ht-btn-group` is only used in `action-buttons.tsx`. Since it's a single-use flex container, it stays as a local style in that component's module CSS rather than becoming a separate component. The wrapper div must emit a `data-role="action-buttons"` attribute as a stable targeting hook, because `apps.module.css` uses `:global(.ht-btn-group)` to control action-button opacity on row hover — after migration the scoped class name would break this rule. Update `apps.module.css` to target `[data-role="action-buttons"]` instead.

## Acceptance Criteria

- **AC#1** No TSX file contains a raw `ht-btn`, `ht-badge`, `ht-chip`, or `ht-card` class string (verifiable via grep), except for the three `<section>` elements in `diagnostics.tsx` where Card's `<div>` would cause a semantic regression — these retain raw card class strings with a documented exemption [FR#11, FR#13]
- **AC#2** The `type="button"` attribute is present on every rendered `<button>` element produced by the Button component without consumers needing to specify it [FR#1]
- **AC#3** All existing visual appearances are preserved — no visual regression in any component across light and dark themes, with the accepted exception that `code-tab.tsx` and `config-tab.tsx` error containers change from `--sp-6` to `--sp-5` padding (4px reduction) by using the default Card variant [FR#2, FR#4, FR#6, FR#9]
- **AC#4** The four `styles/*.css` files (buttons.css, badges.css, chips.css, cards.css) are deleted and their `@import` lines removed from `global.css` [FR#11]
- **AC#5** The three CI CSS guard scripts (`check_global_css_allowlist.py`, `check_dead_global_css.py`, `check_css_module_globals.py`) pass with no violations [FR#11]
- **AC#6** Badge variants `--group` and `--cancelled` do not appear in any CSS or TSX file [FR#15]
- **AC#7** Only one chip variant name exists for the previously-duplicated auto/muted styling [FR#16]
- **AC#8** All existing unit tests pass, with class-querying tests updated to use `data-testid` instead of CSS class selectors — specifically `job-executions.test.tsx` (badge selectors) and `error-boundary.test.tsx` (error-card selector) [FR#13]
- **AC#9** The frontend builds without errors (`npm run build`) [FR#11]
- **AC#10** The `TableCard` component internally uses the generic Card component [FR#12]

## Key Constraints

- **No visual changes** — this is a structural refactor. The rendered output must be pixel-identical before and after. Any visual differences are bugs, not features.
- **CSS Module scoping** — moving from global `ht-*` classes to module-scoped classes means class names change at runtime. Any test that queries by CSS class name (`.ht-badge--success`) must be updated to use `data-testid` or ARIA attributes.
- **No new design tokens** — all CSS values must reference existing tokens from `tokens.css`. Do not introduce new tokens or raw values.
- **Existing variant helpers are inputs, not replacements** — `statusToVariant()` and `executionStatusVariant()` in `utils/status.ts` return variant strings that become props to the Badge component. They stay as-is; the component accepts their return type.
- **Button group stays local** — `ht-btn-group` is used in exactly one file (`action-buttons.tsx`). It moves into that component's module CSS, not into the Button component.
- **CI guard script updates** — removing `ht-btn`, `ht-badge`, `ht-chip`, and `ht-card` prefixes from `styles/*.css` means the allowlist in `check_global_css_allowlist.py` must be updated to remove those entries. The dead-CSS checker scope narrows to the remaining `styles/*.css` files.

## Dependencies and Assumptions

- **Preact + Signals** — the existing framework; components use Preact's `h`/JSX and may interact with Signal values via props
- **CSS Modules via Vite** — `.module.css` files are scoped at build time; this is the established pattern from #736
- **clsx** — already a project dependency; used for conditional class composition inside components
- **StatusShape component** — already exists in `shared/status-shape.tsx`; the Chip `kind` variant will import and render it
- **Design tokens** — all values in `tokens.css`; no new tokens needed
- **Assumption**: the `--group` and `--cancelled` badge variants are genuinely dead — if a feature is in flight that depends on them, removal would break it

## Architecture

### Component structure

Four new files in `frontend/src/components/shared/`, each with a co-located `.module.css`:

**`button.tsx` + `button.module.css`**
- Absorbs all styles from `styles/buttons.css`
- Props: `variant` (default | primary | success | warning | info | danger), `size` (default | sm | xs), `ghost` (boolean), `icon` (boolean), `disabled`, plus standard HTML button attributes via spread — except `type`, which is hardcoded to `"button"` and not accepted as a prop. This is a structural guarantee: the Button component cannot produce a submit button. Callers needing `type="submit"` use a raw `<button>` element.
- Accepts an optional `ref` callback prop (`ref?: (el: HTMLButtonElement | null) => void`) for consumers needing a handle to the underlying element. No `forwardRef` — plain Preact callback refs work without `preact/compat`, and the primary use case (confirm-dialog) already manages its own refs internally
- Additional `class` prop merged via `clsx` for consumer layout overrides

**`badge.tsx` + `badge.module.css`**
- Absorbs styles from `styles/badges.css`, minus the dead `--group` and `--cancelled` variants
- Props: `variant` (success | danger | warning | info | neutral), `size` (default | xs | sm | md), `children`
- The `variant` prop type is defined as `StatusVariant | "info"` by importing `StatusVariant` from `../../utils/status` — this ensures type-level coupling so that `statusToVariant()` return values are always valid Badge variants. The `info` addition covers `config-tab.tsx` usage which is not a status variant.
- Accepts mixed children (text, icons, or both) — the existing `inline-flex` + `gap` styling handles this

**`chip.tsx` + `chip.module.css`**
- Absorbs styles from `styles/chips.css`, merging `--auto` and `--muted` into `muted`
- Props: `variant` (modifier | schedule | kind | origin | muted), `size` (default | sm)
- When `variant="kind"`: requires `kind` prop (ok | warn | err | mute) for border coloring and layout. Callers pass `<StatusShape>` as a child — the component does not auto-render it
- Emits `data-variant={variant}` on the root element as a stable cross-component targeting hook (e.g., `apps.module.css` targets `[data-variant="muted"]` to hide auto chips on mobile)
- Pass-through for `aria-label` and standard span attributes

**`card.tsx` + `card.module.css`**
- Absorbs styles from `styles/cards.css`
- Props: `variant` (default | compact | config | error), `children`
- All variants inherit the base card styles (background, border, border-radius). Variant-specific rules are additive overrides. `variant="error"` is distinct: the existing markup applies `ht-card` and `ht-error-card` as two independent selectors (not a BEM modifier), so the module CSS must absorb both sets of styles into a single class — base card styles plus the error-specific overrides (`padding: var(--sp-6); text-align: center`)
- Accepts an optional `containerRef` prop (`preact.Ref<HTMLDivElement>`) following the existing `TableCard` pattern — no `forwardRef` needed
- Additional `class`, `data-testid`, `style` pass-through

### `class` prop contract

The `class` prop on all four components is for **layout composition only** — margin, flex stretch, grid placement, and position overrides. It is not for visual overrides (padding, color, typography, border changes). Consumers needing a visual variation that doesn't exist should propose a new variant prop value, not use `class`. This gives reviewers a clear standard: if a module CSS class passed via `class` changes anything other than the element's position or size within its parent, it should be a variant instead.

### Migration strategy

Each consumer file is updated to:
1. Replace raw class string with component import + props
2. Remove any `clsx` calls that only existed for class composition of these elements
3. Keep `clsx` calls that combine component usage with module-scoped layout classes (via the `class` prop)

### Existing code reuse

- `styles/buttons.css` → absorbed into `button.module.css` (rename classes from `ht-btn*` to module-scoped names)
- `styles/badges.css` → absorbed into `badge.module.css` (drop `--group`, `--cancelled`)
- `styles/chips.css` → absorbed into `chip.module.css` (merge `--auto`/`--muted` to `muted`)
- `styles/cards.css` → absorbed into `card.module.css`
- `shared/table-card.tsx` → refactored to compose `<Card variant="compact">` internally
- `shared/action-buttons.tsx` → refactored to use `<Button>` with props; `ht-btn-group` moves to `action-buttons.module.css`
- `shared/show-more-button.tsx` → refactored to use `<Button variant="ghost" size="xs">`
- `shared/confirm-dialog.tsx` → refactored to use `<Button>` (keeps internal `useRef` for focus management — no ref forwarding needed)
- `utils/status.ts` → `statusToVariant()` and `executionStatusVariant()` return values used directly as Badge `variant` props; no changes needed

### CI guard updates

- `check_global_css_allowlist.py`: remove `ht-btn`, `ht-badge`, `ht-chip`, `ht-card` from the allowlist (they no longer exist in `styles/*.css`)
- `check_dead_global_css.py`: remove the `ht-badge--` and `ht-chip--kind-` entries from the EXEMPTIONS list (these dynamically-assembled classes will no longer exist in global CSS after migration); scope also narrows since the deleted files are no longer scanned
- `check_css_module_globals.py`: new module files are automatically included in the scan

## Alternatives Considered

**Keep global CSS, add components as wrappers** — components would apply global `ht-*` classes internally. This preserves the existing CSS but defeats the purpose of CSS Modules scoping and leaves the global namespace polluted. Rejected because it doesn't complete the #736 migration.

**Polymorphic `as` prop on Button** — a single Button component that can render as `<a>`, `<button>`, or any element. Adds type complexity for a single use case (the not-found.tsx link). Rejected in favor of restyling that link as a standard `<a>`.

**Separate ButtonLink component** — a dedicated component for `<a>` elements with button styling. Only one instance exists in the codebase. Rejected as over-engineering for a single link on a 404 page.

**Keep `--auto` and `--muted` as separate chip variant names** — maintains semantic distinction ("this is auto-loaded" vs "this is muted metadata"). Rejected because the CSS is identical and the semantic distinction doesn't map to any visual difference — the variant name `muted` covers both use cases.

## Test Strategy

- **Unit tests** for each component: verify correct class application for each prop combination, default `type="button"` on Button, ref forwarding, children rendering (including mixed content for Badge)
- **Migration verification**: update existing tests in `job-executions.test.tsx` to query by `data-testid` instead of `.ht-badge--*` CSS classes
- **Build verification**: `npm run build` succeeds with no errors
- **CI guard verification**: all three CSS lint scripts pass
- **Visual verification**: screenshot comparison before/after to confirm no visual regression (existing Playwright infrastructure from #736)
- **Full test suite**: `uv run nox -s dev` passes with no regressions

## Documentation Updates

- **CLAUDE.md** CSS Architecture section: update to reflect that buttons, badges, chips, and cards are now components, not shared CSS files. Update the "Adding a new shared class" guidance to note the reduced scope of `styles/*.css`.
- **`design/context.md`** Component Inventory / Shared Components section: add Button, Badge, Chip, Card entries.

## Impact

**Files modified (migration):**
- `frontend/src/components/shared/action-buttons.tsx` — Button component usage
- `frontend/src/components/shared/show-more-button.tsx` — Button component usage
- `frontend/src/components/shared/confirm-dialog.tsx` — Button component usage + ref forwarding
- `frontend/src/components/shared/table-card.tsx` — Card component composition
- `frontend/src/components/app-detail/handlers-tab.tsx` — Button, Badge, Chip usage
- `frontend/src/components/app-detail/handler-invocations.tsx` — Chip usage
- `frontend/src/components/app-detail/job-executions.tsx` — Badge usage
- `frontend/src/components/app-detail/unified-handler-row.tsx` — Badge usage
- `frontend/src/components/app-detail/overview-tab.tsx` — Chip usage
- `frontend/src/components/app-detail/code-tab.tsx` — Button, Card usage
- `frontend/src/components/app-detail/config-tab.tsx` — Badge, Card usage
- `frontend/src/components/app-detail/error-cell.tsx` — Button usage
- `frontend/src/components/layout/error-boundary.tsx` — Button, Card usage
- `frontend/src/components/layout/sidebar.tsx` — Chip usage
- `frontend/src/pages/apps.tsx` — Button, Badge, Chip usage
- `frontend/src/pages/app-detail.tsx` — Badge, Chip, Card usage
- `frontend/src/pages/not-found.tsx` — link restyling (remove button classes)
- `frontend/src/pages/handlers.tsx` — Chip usage
- `frontend/src/pages/logs.tsx` — Card usage
- `frontend/src/pages/diagnostics.tsx` — Card usage
- `frontend/src/pages/config.tsx` — Card usage

**Files created:**
- `frontend/src/components/shared/button.tsx` + `button.module.css`
- `frontend/src/components/shared/badge.tsx` + `badge.module.css`
- `frontend/src/components/shared/chip.tsx` + `chip.module.css`
- `frontend/src/components/shared/card.tsx` + `card.module.css`
- `frontend/src/components/shared/action-buttons.module.css` (btn-group styles moved from global)

**Files deleted:**
- `frontend/src/styles/buttons.css`
- `frontend/src/styles/badges.css`
- `frontend/src/styles/chips.css`
- `frontend/src/styles/cards.css`

**Files updated (infrastructure):**
- `frontend/src/global.css` — remove 4 `@import` lines
- `tools/check_global_css_allowlist.py` — remove deleted prefixes from allowlist
- `frontend/src/components/app-detail/job-executions.test.tsx` — update badge selectors
- `frontend/src/components/layout/error-boundary.test.tsx` — update error-card selector

**Blast radius:** Moderate — touches 21+ TSX files but each change is mechanical (replace class string with component import + props). No behavioral logic changes. Visual output is identical.

## Open Questions

None — all design decisions resolved during discovery.
