---
task_id: "T01"
title: "Add shadcn token alias layer in global.css"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "AC#4"]
---

## Summary

Add 136 new shadcn-named CSS custom properties as aliases in `global.css`, each pointing at an existing token value from `tokens.css`. Update the shadcn `@theme inline` block and `:root`/`[data-theme="dark"]` blocks to use real hassette token values instead of shadcn's defaults. This resolves the `--accent` naming collision WITHOUT redefining `--accent` itself: hassette's brand color maps to `--primary` (sourced from `--accent-hue`/`--accent-chroma` primitives, not `var(--accent)`), and hassette's highlight background maps to a new, non-colliding property `--highlight-bg`, which Tailwind's `@theme inline` `--color-accent` mapping sources from instead of `--accent`. The literal `--accent` property is left untouched. CSS Modules are NOT touched -- they keep referencing old names (including `var(--accent)`, which keeps resolving to the brand color) until PR 2.

**Revision note (post-T01-attempt-1):** the original plan for this task literally redefined `--accent: var(--bg-active)`. Review (spec + code + integration, all three independently, verified via runtime `getComputedStyle`) found this silently breaks ~25 existing CSS Module files that reference `var(--accent)` expecting the brand color — CSS custom properties have no per-consumer scoping, so a single document-wide redefinition affects every reader regardless of source order. User decided (given the choice between accepting this regression or fixing it) to fix it: expose the new semantic role under `--highlight-bg` instead of reusing `--accent`. This revision reflects that decision.

## Target Files

- modify: `frontend/src/global.css`
- read: `frontend/src/tokens.css`
- read: `design/specs/088-frontend-shadcn-components/design.md` (Architecture > Phase 1 for mapping table)

## Prompt

Read `design/specs/088-frontend-shadcn-components/design.md`, Architecture > Phase 1 for the full token mapping summary and critical aliases list. Read `frontend/src/tokens.css` to get the current token values. Read `frontend/src/global.css` to see the existing shadcn `@theme inline` block and `:root`/`[data-theme="dark"]` blocks.

Add a new alias block in `global.css` that defines all 136 shadcn-named custom properties. Most aliases are a `var()` reference to the existing token name, e.g. `--background: var(--bg-page); --foreground: var(--ink-1);`. `--primary` and `--highlight-bg` are the two exceptions — see "Critical collision resolution" below.

The alias block must cover all three categories:
- **shadcn-standard** (13): `--background`, `--card`, `--muted`, `--highlight-bg` (exposes shadcn's "accent" role — see Focus section; NOT a `var(--accent)` alias), `--foreground`, `--muted-foreground`, `--border`, `--primary`, `--primary-foreground`, `--destructive`, `--input`, `--font-sans`, `--font-mono`
- **tailwind-native** (43): spacing (`--spacing-*`), sizing (`--size-*`), font-weight, opacity, motion, radius, border-width aliases
- **custom-extend** (80): status colors (`--status-*`), handler families (`--handler-*`), type scale (`--text-*`), intermediate ink/line tiers, code, shadows, overlay, z-index, etc.

Critical collision resolution:
- `--primary: oklch(<L> var(--accent-chroma) var(--accent-hue))` (hassette's brand/action color, sourced from the underlying primitives — NOT `var(--accent)`, since `--accent` must not be read anywhere in a ruleset that could later redefine it)
- `--highlight-bg: var(--bg-active)` (hassette's highlighted background, matching shadcn's semantic role — deliberately a NEW property name, not `--accent`)
- Tailwind's `@theme inline` `--color-accent` maps to `var(--highlight-bg)`, not `var(--accent)`
- `--accent` itself is NOT redeclared anywhere in this task — it keeps its original tokens.css meaning (brand color) for both `--primary` and the ~25 legacy CSS Module consumers
- `--ring`, `--chart-5`, `--sidebar-primary`, `--sidebar-ring` source from `var(--primary)`, not `var(--accent)`
- `--primary-foreground: var(--accent-ink)`

Also update the shadcn `@theme inline` and `:root`/`[data-theme="dark"]` blocks already in `global.css` to reference the real hassette token values instead of shadcn's default neutral-gray OKLCH values.

Handle the radius edge case: `--r-lg` (12px) and `--r-xl` (20px) don't match shadcn's `calc()` formula output (10px, 14px). Use literal overrides, not the `calc()` chain.

Both light `:root` and dark `[data-theme="dark"]` blocks need aliases -- dark overrides use the same alias names pointing at the same old-name tokens (which `tokens.css` already overrides per theme).

## Focus

- The `--accent` naming is the single most critical call, and it is the ONE alias in this whole layer that cannot be done as a simple `var()` reference under the target name, because the target name (`--accent`) is identical to hassette's pre-existing name. shadcn's `--accent` is a subtle highlighted-background role (hover/active row), NOT a brand color. Hassette's old `--accent` is the brand/action color -> alias it to shadcn's `--primary`, sourced from `--accent-hue`/`--accent-chroma` directly (not `var(--accent)`). Hassette's `--bg-active` maps to shadcn's accent *role*, but expose it under a new property name, `--highlight-bg` -- do NOT declare a new `--accent` custom property anywhere in this file.
- For every OTHER alias in this layer (the other 135), declaration order genuinely doesn't matter since old and new names differ -- no sentinel-swap hack needed. `--accent` is the sole exception, precisely because old-name == new-name for that one token; do not generalize the "order doesn't matter" reasoning to it.
- The alias block should go AFTER the `tokens.css` import in `global.css` so the referenced values are defined.
- `tokens.css` is NOT modified in this task. Old names stay as the source of truth.
- CSS Module files are NOT modified. They keep using `var(--bg-page)` etc. — and, critically, `var(--accent)` for the brand color — until PR 2.
- **Verification for this specific alias must be runtime, not textual.** Attempt 1 of this task passed a textual/static read of the declarations while being broken at runtime (CSS custom properties resolve `var()` against final cascaded value, not declaration-order value). For `--primary`/`--highlight-bg`/`--accent` specifically, confirm actual computed values (build + inspect the generated CSS, or a quick browser/Playwright check), in both light and dark themes, rather than trusting that the declarations read correctly.

## Verify

- [ ] FR#1: All 136 shadcn-named aliases are defined in `global.css` covering surfaces, ink, borders, accent/primary, status, handler, spacing, sizing, radius, typography, motion, effects, z-index
- [ ] FR#2: `--primary` resolves to hassette's brand color value (verified via computed style, not just textual inspection, in both themes); `--highlight-bg` resolves to hassette's highlighted background value (old `--bg-active`); Tailwind's `--color-accent` mapping sources from `--highlight-bg`; the literal `--accent` custom property is NOT redeclared anywhere in `global.css` and still resolves to the brand color (confirm this holds for at least one existing CSS Module consumer of `var(--accent)`, e.g. `button.module.css`, without modifying that file)
- [ ] AC#4: `cd frontend && npm run build` succeeds with the alias layer in place
