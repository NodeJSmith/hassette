# UI Systems Improvement Plan

Temporary working plan. Delete when complete.

## Context

Audit of frontend CSS against Refactoring UI principles. Strong token foundations exist for font size, color, box shadows, border radius, and spacing. Gaps in font weight, opacity, letter spacing, accent color, depth, and whitespace.

## Phase 1: Token Foundations

| Step | What | Scope |
|---|---|---|
| **1a** | Font weight tokens | Add `--fw-normal` (400), `--fw-medium` (500), `--fw-semibold` (600). Replace ~30 raw values. Zero visual change. |
| **1b** | Letter spacing consolidation | Collapse 6 raw positive values into `--tr-label` (0.05em) and `--tr-label-tight` (0.03em). ~12 raw values. |
| **1c** | Opacity tokens | Add `--opacity-disabled` (0.4), `--opacity-muted` (0.6), `--opacity-subtle` (0.8). Map ~15 scattered values. Minor visual snapping. |
| **1d** | Bump minimum font sizes | `--fs-xs`: 10px -> 11px, `--fs-micro`: 11px -> 12px. One-line token change, ~70 usages affected. Screenshot review after. |
| **1e** | Accent color system | Refactor accent tokens to oklch-derived from `--accent-hue` + `--accent-chroma`. Expand from 4 stops to 6-7. Expand status colors (ok/warn/err/mute) from 2 stops to 4-5 each. |
| **1f** | Dev tuning panel | Floating dev-only panel with sliders: density multiplier, surface contrast, shadow intensity, base font size, radius scale, accent hue/chroma. Make spacing/shadow/radius tokens derived from base values so sliders cascade. |

## Phase 2: Depth (use dev panel)

| Step | What |
|---|---|
| **2a** | Widen surface gap — adjust `--bg-page` / `--bg-surface` so cards separate from background |
| **2b** | Shadow on cards — `shadow-1` on Card, shadow-1 -> shadow-2 hover on interactive cards |
| **2c** | Inset shadows on sunken regions — `--shadow-inset` token for code blocks, scroll containers, log areas |
| **2d** | Sticky header shadows — bottom shadow on table headers and status bar when scrolled |

## Phase 3: Whitespace (use dev panel)

| Step | What |
|---|---|
| **3a** | Crank it up — increase spacing aggressively via density multiplier. Intentionally too much. |
| **3b** | Dial it back — screenshot review, tighten where too airy. Hard-code final values. |

## Other items noted

- `align-items: baseline` audit — ~25 uses of `center` that may benefit from `baseline` where font sizes mix
- Composite text styles (bundling font-size + line-height + weight + tracking) as a future consideration
