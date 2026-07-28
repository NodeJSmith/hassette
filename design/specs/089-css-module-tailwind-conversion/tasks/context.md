# Context: CSS Module → Tailwind Conversion

## Problem & Motivation

The frontend carries 54 CSS Module files (~3,700 lines) and 6 global CSS files (~690 lines) alongside the Tailwind v4 + shadcn/ui stack landed in specs 020 and 088. Every component has a co-located `.module.css` that duplicates what Tailwind utilities express in a single className string. Contributors must decide between CSS Modules and Tailwind for every style declaration — AI agents produce inconsistent output because neither approach is canonical. Three layers of token indirection (`tokens.css` → `global.css` aliases → CSS Module references) exist for values that could be expressed once. Six prek hooks guard CSS Module conventions that will no longer exist after this conversion.

## Visual Artifacts

None.

## Key Decisions

1. **Tailwind utilities inline in JSX, not `@apply` in CSS files.** `@apply` creates CSS files with Tailwind syntax but loses colocation and purging benefits. All styling lives in `className` strings using `cn()`.
2. **Adopt Tailwind Preflight to replace the hand-rolled reset.** Preflight is more aggressive (resets button/input defaults, adds border-style: solid + border-width: 0). Hassette-specific rules (focus indicator, reduced motion) are preserved in `@layer base`.
3. **Register custom Tailwind screens for non-standard breakpoints.** The project uses 900px (sidebar), 768px (mobile), 480px (small mobile) — these are registered in `@theme` so `max-sidebar:`, `max-mobile:`, `max-small-mobile:` prefixes work.
4. **Inline tokens.css values into global.css, then delete tokens.css.** The alias layer in global.css already bridges old → new names. After all CSS Module files are gone and no code references old names directly, the source values move into global.css's `:root`/`[data-theme="dark"]` blocks and tokens.css is deleted.
5. **Remove CSS lint tools that guard CSS Module conventions.** Four scripts (`check_css_module_globals`, `check_dead_global_css`, `check_global_css_allowlist`, `check_undefined_css_refs`) become unnecessary. `check_dead_tokens` is updated to scan global.css. `check_breakpoint_drift` is evaluated for continued relevance.
6. **`cn()` is the sole className composition utility.** Remaining `clsx` imports (10 files) are migrated. The `clsx` direct dependency is removed.

## Constraints & Anti-Patterns

- **Do NOT change component behavior or DOM structure.** This is a styling-only migration. Wrapper elements may be removed only when they existed solely to attach a CSS Module class.
- **Do NOT introduce new design tokens or change visual output.** Every Tailwind utility must map to the same CSS property and value the module class produced.
- **Do NOT use `@apply` directives.** If a pattern is too complex for inline utilities, use `@layer components` in `global.css`.
- **Do NOT remove tokens.css until ALL CSS Module files are deleted.** The alias layer bridges old → new names, but CSS Modules reference old names directly.
- **Do NOT touch `@font-face` declarations** — self-hosted fonts have no Tailwind equivalent.
- **Non-goals:** Rewriting `design/context.md` (PR 3), regenerating doc screenshots (PR 3), changing routing/data-fetching/WebSocket.

## Design Doc References

- `## Architecture → Phase 1` — Preflight adoption and theme registration details
- `## Architecture → Phase 2` — CSS Module conversion patterns and directory batches
- `## Architecture → Phase 3` — Global CSS removal strategy per file
- `## Architecture → Phase 4` — Lint tool removal inventory
- `## Architecture → Phase 5` — StrictMode + cleanup steps
- `## Edge Cases` — animations, `:global()` overrides, complex selectors, scoped CSS variables, responsive breakpoints, StrictMode double-effects, Preflight differences
- `## Convention Examples` — before/after conversion patterns, `cn()` conditional classes, `@layer base` typography
- `## Key Constraints` — 5 named constraints to preserve

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
