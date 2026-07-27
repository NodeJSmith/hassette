---
task_id: "T01"
title: "Add shadcn token alias layer in global.css"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "AC#4"]
---

## Summary

Add 136 new shadcn-named CSS custom properties as aliases in `global.css`, each pointing at an existing token value from `tokens.css`. Update the shadcn `@theme inline` block and `:root`/`[data-theme="dark"]` blocks to use real hassette token values instead of shadcn's defaults. This resolves the `--accent` naming collision (hassette's brand color maps to `--primary`, hassette's highlight background maps to `--accent`). CSS Modules are NOT touched -- they keep referencing old names until PR 2.

## Target Files

- modify: `frontend/src/global.css`
- read: `frontend/src/tokens.css`
- read: `design/specs/088-frontend-shadcn-components/design.md` (Architecture > Phase 1 for mapping table)

## Prompt

Read `design/specs/088-frontend-shadcn-components/design.md`, Architecture > Phase 1 for the full token mapping summary and critical aliases list. Read `frontend/src/tokens.css` to get the current token values. Read `frontend/src/global.css` to see the existing shadcn `@theme inline` block and `:root`/`[data-theme="dark"]` blocks.

Add a new alias block in `global.css` that defines all 136 shadcn-named custom properties. Each alias is a `var()` reference to the existing token name. Example: `--primary: var(--accent); --background: var(--bg-page); --foreground: var(--ink-1);`

The alias block must cover all three categories:
- **shadcn-standard** (13): `--background`, `--card`, `--muted`, `--accent`, `--foreground`, `--muted-foreground`, `--border`, `--primary`, `--primary-foreground`, `--destructive`, `--input`, `--font-sans`, `--font-mono`
- **tailwind-native** (43): spacing (`--spacing-*`), sizing (`--size-*`), font-weight, opacity, motion, radius, border-width aliases
- **custom-extend** (80): status colors (`--status-*`), handler families (`--handler-*`), type scale (`--text-*`), intermediate ink/line tiers, code, shadows, overlay, z-index, etc.

Critical collision resolution:
- `--primary: var(--accent)` (hassette's brand/action color)
- `--accent: var(--bg-active)` (hassette's highlighted background, matching shadcn's semantic role)
- `--primary-foreground: var(--accent-ink)`

Also update the shadcn `@theme inline` and `:root`/`[data-theme="dark"]` blocks already in `global.css` to reference the real hassette token values instead of shadcn's default neutral-gray OKLCH values.

Handle the radius edge case: `--r-lg` (12px) and `--r-xl` (20px) don't match shadcn's `calc()` formula output (10px, 14px). Use literal overrides, not the `calc()` chain.

Both light `:root` and dark `[data-theme="dark"]` blocks need aliases -- dark overrides use the same alias names pointing at the same old-name tokens (which `tokens.css` already overrides per theme).

## Focus

- The `--accent` naming is the single most critical call. shadcn's `--accent` is a subtle highlighted-background role (hover/active row), NOT a brand color. Hassette's old `--accent` is the brand/action color -> that maps to shadcn's `--primary`. Hassette's `--bg-active` maps to shadcn's `--accent`. Do NOT map old `--accent` to new `--accent`.
- Since these are aliases (`var()` references), declaration order doesn't matter -- no sentinel-swap hack needed.
- The alias block should go AFTER the `tokens.css` import in `global.css` so the referenced values are defined.
- `tokens.css` is NOT modified in this task. Old names stay as the source of truth.
- CSS Module files are NOT modified. They keep using `var(--bg-page)` etc. until PR 2.

## Verify

- [ ] FR#1: All 136 shadcn-named aliases are defined in `global.css` covering surfaces, ink, borders, accent/primary, status, handler, spacing, sizing, radius, typography, motion, effects, z-index
- [ ] FR#2: `--primary` resolves to hassette's brand color value (old `--accent`), `--accent` resolves to hassette's highlight background value (old `--bg-active`), confirmed by inspecting the alias declarations
- [ ] AC#4: `cd frontend && npm run build` succeeds with the alias layer in place
