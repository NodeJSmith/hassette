# Context: Shared UI Components (Button, Badge, Chip, Card)

## Problem & Motivation
The monitoring UI uses raw CSS class strings (`ht-btn`, `ht-badge`, `ht-chip`, `ht-card`) to style buttons, badges, chips, and cards. Every consumer manually assembles class names, leading to real bugs (three buttons missing `type="button"`, inconsistent sizing across pages) and an inconsistency tax (different construction methods, dead CSS variants, duplicated chip styles). This is the natural completion of the CSS Modules migration (#736), which moved component-specific CSS into `.module.css` files but left these four shared style files as global CSS because no component existed to own them.

## Visual Artifacts
None.

## Key Decisions
1. **CSS moves into co-located `.module.css` files** — the four `styles/*.css` files are deleted and their styles absorbed into component module CSS. The `@import` lines in `global.css` are removed.
2. **Button `type` is a structural guarantee** — `type="button"` is hardcoded, not a prop. The component cannot produce a submit button. Callers needing `type="submit"` use a raw `<button>`.
3. **Badge variant type imports `StatusVariant`** — defined as `StatusVariant | "info"` via import from `utils/status.ts` for type-level coupling with existing helper functions.
4. **Chip `--auto` and `--muted` merge into `muted`** — identical CSS, single variant name.
5. **Chip `kind` variant does NOT auto-render StatusShape** — callers pass it as children, preserving the visual primitive boundary and mechanical migration.
6. **Chip emits `data-variant` attribute** — stable cross-component targeting hook for external CSS rules (e.g., `apps.module.css` hiding chips on mobile).
7. **Card variant="error" absorbs both base + override styles** — the existing non-BEM `ht-error-card` class is folded into a single module class that includes base card styles.
8. **No `forwardRef`** — callback ref props and the `containerRef` pattern from TableCard are used instead. No `preact/compat` dependency.
9. **`class` prop is layout-only** — margin, flex stretch, grid placement, position. Not visual overrides.
10. **`data-role="action-buttons"` on ActionButtons wrapper** — stable targeting hook for `apps.module.css` hover-reveal opacity rule.
11. **diagnostics.tsx `<section>` elements exempted from AC#1** — raw card classes retained to preserve semantic HTML landmarks.
12. **layout.css responsive rules move into card.module.css** — `.ht-card > .ht-table` scroll and 480px padding rules.

## Constraints & Anti-Patterns
- **No visual changes** — rendered output must be pixel-identical before and after.
- **No new design tokens** — all CSS values reference existing tokens from `tokens.css`.
- **No `preact/compat`** — stick to plain Preact APIs.
- **Do NOT componentize tables** — `styles/tables.css` and `ht-table-*` classes are out of scope.
- **Do NOT touch layout.css or typography.css** beyond removing the two card-related responsive rules.
- **Do NOT redesign any component's visual appearance.**
- **Button group stays local** — `ht-btn-group` moves to `action-buttons.module.css`, not Button.
- **Existing variant helpers stay as-is** — `statusToVariant()` and `executionStatusVariant()` return values are used directly as Badge variant props.

## Design Doc References
- ## Architecture — component structure, props, CSS module details, migration strategy
- ## Edge Cases — ActionButtons conditional variants, confirm dialog refs, layout.css cross-refs, button group
- ## Key Constraints — no visual changes, CSS Module scoping, no new tokens, variant helpers, CI guards
- ## CI guard updates — allowlist, EXEMPTIONS, module globals
- ## Test Strategy — unit tests, migration verification, build, CI guards, visual, full suite
