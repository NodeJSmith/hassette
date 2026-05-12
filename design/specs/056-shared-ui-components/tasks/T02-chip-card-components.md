---
task_id: "T02"
title: "Create Chip and Card components with module CSS"
status: "planned"
depends_on: []
implements: ["FR#6", "FR#7", "FR#8", "FR#9", "FR#10", "FR#16"]
---

## Summary
Create the Chip and Card reusable components in `frontend/src/components/shared/`, each with co-located `.module.css` files. Chip merges the duplicate `--auto`/`--muted` variants into `muted` and emits `data-variant` for stable external targeting. Card absorbs all card styles including the non-BEM `ht-error-card`, ensures all variants inherit base styles, and moves two responsive rules from `layout.css` into `card.module.css`. Unit tests for both components.

## Prompt
Create two new components in `frontend/src/components/shared/`:

### Chip (`chip.tsx` + `chip.module.css`)

1. Read `frontend/src/styles/chips.css` for the full CSS. Convert to module-scoped names. **Merge `.ht-chip--auto` and `.ht-chip--muted` into a single `.muted` class** — they have identical CSS. The resulting variants are: `modifier`, `schedule`, `kind`, `origin`, `muted`.

2. For the `kind` variant, the CSS has a shared `.ht-chip--kind` base class plus per-color sub-rules (`.ht-chip--kind-ok`, etc.). In module CSS, structure this as: `.kind` (base with `gap` and `border`) plus `.kindOk`, `.kindWarn`, `.kindErr`, `.kindMute` color classes. Both the base `.kind` and the color class are applied via `clsx`.

3. Component props interface:
   - `variant`: `"modifier" | "schedule" | "kind" | "origin" | "muted"` (required)
   - `kind`: `"ok" | "warn" | "err" | "mute"` (required when `variant="kind"`, ignored otherwise)
   - `size`: `"default" | "sm"` (default: `"default"`)
   - `class`: `string` (optional, merged via `clsx`)
   - `children`: `preact.ComponentChildren`
   - Standard span attributes pass-through (`aria-label`, `data-testid`, `title`, etc.)

4. The component MUST emit `data-variant={variant}` on the root `<span>` element. This is a stable cross-component targeting hook — `apps.module.css` targets `[data-variant="muted"]` to hide auto chips on mobile.

5. The component does NOT auto-render `<StatusShape>`. Callers pass StatusShape as a child when using `variant="kind"`.

6. Write unit tests in `chip.test.tsx`: verify each variant applies correct classes, verify `kind` prop applies color classes when `variant="kind"`, verify `data-variant` attribute is rendered, verify `size="sm"` works, verify `aria-label` pass-through, verify children render.

### Card (`card.tsx` + `card.module.css`)

1. Read `frontend/src/styles/cards.css`. Convert to module-scoped names: `.card` (base), `.compact`, `.config`, `.error`.

2. **Critical: `variant="error"` handling** — The existing CSS has `.ht-card` and `.ht-error-card` as two independent selectors (NOT BEM modifier). The `.error` module class must absorb BOTH the base card styles (background, border, border-radius from `.ht-card`) AND the error-specific overrides (`padding: var(--sp-6); text-align: center` from `.ht-error-card`). The other variants (compact, config) are true modifiers that only override specific properties and inherit the base via a separate `.card` class applied alongside them.

3. **Move responsive rules from `layout.css`** into `card.module.css`:
   - From `layout.css:162-167` (768px breakpoint): `.ht-card > .ht-table` horizontal scroll. In module CSS: `.card :global(.ht-table), .card > div > :global(.ht-table) { display: block; overflow-x: auto; }` (tables are staying global).
   - From `layout.css:189-191` (480px breakpoint): `.ht-card { padding: var(--sp-3); }`. In module CSS: `@media (max-width: 480px) { .card { padding: var(--sp-3); } }`.
   - After adding these to `card.module.css`, **remove the original rules** from `frontend/src/styles/layout.css`.

4. Component props interface:
   - `variant`: `"default" | "compact" | "config" | "error"` (default: `"default"`)
   - `class`: `string` (optional, merged via `clsx`)
   - `containerRef`: `preact.Ref<HTMLDivElement>` (optional — following existing `TableCard` pattern)
   - `children`: `preact.ComponentChildren`
   - Standard div attributes pass-through (`data-testid`, `style`, etc.)

5. Rendering: all variants apply `.card` base class. Variants `compact`, `config` additionally apply their modifier class. Variant `error` applies `.error` only (which already includes base styles). The `containerRef` is applied as the `ref` on the root `<div>`.

6. Write unit tests in `card.test.tsx`: verify each variant, verify `class` prop merges, verify `containerRef` is applied, verify `data-testid` and `style` pass through, verify `variant="error"` renders correct combined styles.

## Focus
- `frontend/src/styles/chips.css` — full CSS to absorb; note `--auto` and `--muted` are identical
- `frontend/src/styles/cards.css` — full CSS; note `ht-error-card` is NOT a BEM modifier
- `frontend/src/styles/layout.css:162-167,189-191` — two responsive rules to move into `card.module.css` then DELETE from layout.css
- `frontend/src/components/shared/table-card.tsx` — reference for `containerRef` prop pattern
- `frontend/src/components/shared/status-shape.tsx` — Chip kind callers will pass this as children
- `frontend/src/utils/status.ts` — `StatusKind` type if needed for Chip's `kind` prop (check what type StatusShape accepts)
- `data-variant` attribute on Chip is critical for `apps.module.css:199` mobile hide rule

## Verify
- [ ] FR#6: Chip renders `<span>` with variants `modifier`, `schedule`, `kind`, `origin`, `muted`
- [ ] FR#7: Chip `kind` variant accepts `kind` prop for border coloring; does NOT auto-render StatusShape
- [ ] FR#8: Chip passes through `aria-label` on the root element
- [ ] FR#9: Card renders `<div>` with variants `default`, `compact`, `config`, `error`
- [ ] FR#10: Card supports `containerRef`, `class`, `data-testid`, and `style` pass-through
- [ ] FR#16: Only one chip variant name (`muted`) exists for the previously-duplicated auto/muted CSS
