# Design Direction: Hassette Web UI

**Date:** 2026-03-19
**Updated:** 2026-03-19
**Completeness:** full

## Intent
- **Who**: A developer at their desk — either verifying a fresh deployment is green, or mid-incident figuring out why the garage door automation didn't fire. Pulls up the UI with a question already in mind, not for passive monitoring.
- **Task**: Diagnose. Verify. Confirm or refute a hypothesis fast. "Did my handler fire? What values did it see? Did it error? What was the exception?" — then close the tab.
- **Feel**: Like opening a well-organized toolbox. Everything has a place, you grab what you need, close it, move on. Not a dashboard you stare at — a diagnostic instrument you reach for.

## References
- **Linear**: The information density and monospace meta text. Compact rows that expand on click. Dense but scannable. Everything where you expect it.
- **Vercel dashboard**: The KPI strip, status badges, flat-but-not-flat surface hierarchy. Quiet confidence.
- **Terminal aesthetic (grown up)**: The dark mode direction — near-black with emerald and amber — has the vibe of a terminal that evolved into a product. Data-forward, chrome-minimal.

## Domain
- **Concepts**: Wiring (handlers connected to entities), Pulse (system liveness via WebSocket), Threshold (state transitions trigger actions), Trace (following what happened from effect to cause), Registry (what's registered, active, dormant)
- **Color world**: The green LED on a running Raspberry Pi. The cool gray of a breaker panel. The red blink of a low-battery smoke detector. The soft glow of a phone screen in a dark room pulling up the UI at midnight. The matte black of a well-made tool.
- **Signature**: The breathing pulse dot — a slow inhale/exhale animation on the WebSocket connection indicator. Emerald when connected (breathing). Red and static when disconnected. The only continuously animated element. It exists because the system maintains a persistent WebSocket to Home Assistant — the dot breathes because the connection is alive.
- **Rejected defaults**:
  - Cool slate/amber (the current palette) → rejected by user as "doesn't fit the vibe"
  - Indigo/violet accent (Tailwind default) → zero personality, every AI-generated UI uses this
  - Dark sidebar on light page → jarring mixed-mode contrast that fights for attention
  - Borders-only depth (current system) → makes the UI feel flat and cheap at low information density

## Tokens

### Color — Light Mode (Chalk + Emerald)

| Token | Value | Role |
|-------|-------|------|
| `--ht-bg` | `#f7f7f8` | Page canvas — cool chalk, no warmth |
| `--ht-surface` | `#ffffff` | Cards, panels, list rows |
| `--ht-surface-recessed` | `#f0f0f2` | Hover states, inset areas, expanded details |
| `--ht-border` | `rgba(0, 0, 0, 0.06)` | Default separation — visible when you look, invisible when you don't |
| `--ht-border-strong` | `rgba(0, 0, 0, 0.10)` | Interactive element borders (inputs, buttons, toggles) |
| `--ht-text` | `#111113` | Primary text — near-black graphite, not pure black |
| `--ht-text-secondary` | `#55555e` | Secondary labels, meta text |
| `--ht-text-dim` | `#9898a0` | Tertiary text, timestamps, placeholders |
| `--ht-accent` | `#059669` | Primary accent — emerald. Entity names, active states, links |
| `--ht-accent-light` | `rgba(5, 150, 105, 0.07)` | Accent backgrounds (badges, highlights) |
| `--ht-value` | `#b45309` | State values in handler summaries (`open`, `home`) — amber, distinct from accent |
| `--ht-success` | `#059669` | Healthy/running — same as accent (emerald = "all systems go") |
| `--ht-success-light` | `rgba(5, 150, 105, 0.07)` | Success badge backgrounds |
| `--ht-danger` | `#dc2626` | Error, failed, disconnected |
| `--ht-danger-light` | `rgba(220, 38, 38, 0.07)` | Error badge/trace backgrounds |
| `--ht-warning` | `#a16207` | Warning states, elevated error rates |
| `--ht-warning-light` | `rgba(161, 98, 7, 0.06)` | Warning badge backgrounds |

### Color — Dark Mode (Graphite + Emerald)

| Token | Value | Role |
|-------|-------|------|
| `--ht-bg` | `#111113` | Page canvas — near-black graphite |
| `--ht-surface` | `#1a1a1e` | Cards, panels, list rows |
| `--ht-surface-recessed` | `#222226` | Hover states, inset areas, expanded details |
| `--ht-border` | `rgba(255, 255, 255, 0.06)` | Default separation |
| `--ht-border-strong` | `rgba(255, 255, 255, 0.10)` | Interactive element borders |
| `--ht-text` | `#ececef` | Primary text |
| `--ht-text-secondary` | `#9898a0` | Secondary labels |
| `--ht-text-dim` | `#5c5c66` | Tertiary text |
| `--ht-accent` | `#34d399` | Primary accent — brighter emerald for dark backgrounds |
| `--ht-accent-light` | `rgba(52, 211, 153, 0.10)` | Accent backgrounds |
| `--ht-value` | `#fbbf24` | State values — amber, high contrast on dark |
| `--ht-success` | `#34d399` | Healthy/running |
| `--ht-success-light` | `rgba(52, 211, 153, 0.10)` | Success badge backgrounds |
| `--ht-danger` | `#f87171` | Error, failed, disconnected |
| `--ht-danger-light` | `rgba(248, 113, 113, 0.10)` | Error backgrounds |
| `--ht-warning` | `#fbbf24` | Warning states |
| `--ht-warning-light` | `rgba(251, 191, 36, 0.08)` | Warning backgrounds |

**Rationale**: Graphite neutrals (no blue tint, no warm tint — true neutral gray) keep the same temperature in both modes. Emerald as the primary accent because green = "alive, connected, working" in this domain — the LED on a running Pi, the "all systems go" signal. Amber for state values creates semantic separation from the accent without adding a third hue family. Red for errors is universal and unambiguous.

### Typography
- **Headings**: Space Grotesk (600/700) — geometric, technical character. Distinguishes Hassette from generic admin panels. The only place personality shows in the type system.
- **Body**: DM Sans (400/500) — clean geometric sans that pairs well with Space Grotesk without competing. Readable at small sizes for meta text and descriptions.
- **Mono**: JetBrains Mono (400/500/600) — entity IDs, timestamps, handler names, invocation data, log entries. The workhorse font — most data on the page is monospace.
- **Scale**:
  - `--ht-text-xs`: 10px — uppercase labels (INIT STATUS, FIRES, AVG)
  - `--ht-text-sm`: 11px — meta text, badge text, timestamps
  - `--ht-text-base`: 13px — handler summaries, table data, log entries
  - `--ht-text-md`: 14px — body text, descriptions
  - `--ht-text-lg`: 15px — section headings (Event Handlers, Scheduled Jobs)
  - `--ht-text-xl`: 19px — page titles (Garage Proximity)
  - `--ht-text-2xl`: 22px — hero numbers in health cards (0.4%, 18ms, 3m ago)
- **Weights**: 400 (body), 500 (mono emphasis, meta strong values), 600 (headings, stat values), 700 (page title only)

### Spacing
- **Base**: 4px (`--ht-sp-1`)
- **Scale**: `--ht-sp-1` (4px), `--ht-sp-2` (8px), `--ht-sp-3` (12px), `--ht-sp-4` (16px), `--ht-sp-5` (20px), `--ht-sp-6` (24px), `--ht-sp-8` (32px), `--ht-sp-10` (40px)
- **Density note**: This is a diagnostic tool — density is a feature, not a problem. Row padding is compact (10-12px vertical). Meta text gaps are tight (12-16px). The health strip cards have modest padding (12px 14px). Whitespace is for section separation, not for breathing room inside components.

### Depth
- **Strategy**: Subtle shadows + borders. Shadows establish card-level hierarchy. Borders separate rows within lists.
- **Why**: The current borders-only approach was explicitly rejected ("flat and cheap"). Full Bulma-style shadows are too heavy. Single `shadow-sm` on cards adds dimensionality without weight — like a card sitting on a desk, not floating in space.
- **Levels**:
  - `--ht-shadow-sm`: `0 1px 2px rgba(0, 0, 0, 0.04)` — cards, health strip, list containers
  - `--ht-shadow-md`: `0 4px 12px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.03)` — hover lift on app cards, dropdowns
  - Dark mode: `--ht-shadow-sm`: `0 1px 3px rgba(0, 0, 0, 0.3)` — shadows are more visible against dark backgrounds

### Border Radius
- **Scale**: `--ht-radius-sm` (6px), `--ht-radius-md` (9px), `--ht-radius-lg` (10px), `--ht-radius-full` (9999px)
- **Character**: Slightly rounded — not sharp (too clinical), not pill-shaped (too playful). 9-10px on cards and list containers. 6px on buttons and inputs. Full round on badges and status dots. The radius says "tool with considered edges," not "SaaS product" or "terminal."

### Motion
- **Micro**: 120ms `ease-out` — hover state transitions (background, border color)
- **Transition**: 200ms `ease-out` — expand/collapse handler detail, tab switching
- **Signature**: 2.5s `ease-in-out` infinite — the pulse dot breathe animation. This is the only continuous animation in the UI. Slow, biological, like checking if something is alive by watching for breathing.
- **Reduced motion**: All animations and transitions collapse to 0.01ms. The pulse dot becomes a static dot.

## Anti-patterns
- **No warm amber/gold as the primary accent** — that was the old design system. Amber is now reserved for state values only.
- **No dark sidebar on light page** — sidebar uses the same `--ht-bg` and `--ht-surface` as the main content area. Navigation separated by border, not by color.
- **No borders-only depth** — every card and list container gets `--ht-shadow-sm`. Borders alone make the UI feel flat.
- **No pure black or pure gray** — all neutrals are tinted slightly cool (the `#111113`, `#1a1a1e` graphite tint). Per Impeccable guidelines.
- **No Inter, Roboto, or system-ui as primary font** — DM Sans for body, Space Grotesk for headings, JetBrains Mono for data.
- **No indigo/violet accents** — Tailwind default, AI slop signal.
- **No card nesting** — handler rows are list items in a bordered container, not cards inside cards.
- **No bounce/elastic easing** — all transitions use `ease-out`. The UI is a tool, not a toy.

## Component Notes
- **Handler rows**: Grid layout — `8px dot | 1fr content | auto stats`. Plain-language summary as the primary text ("Fires when binary_sensor.garage_door → open"). Invocation count, last-fired, avg duration as mono meta text below. Expandable to show invocation history.
- **Health strip**: 4-column grid of compact cards at the top of App Detail. Init status, error rate (with decay), avg duration, last activity. These are the four questions answered at a glance before drilling into handlers.
- **Pulse dot**: 8px circle in the sidebar. `--ht-accent` color with `breathe` animation when connected. `--ht-danger` and static when disconnected.
- **Status badges**: Pill-shaped (`border-radius: full`), mono font, colored dot + text. Running = emerald, Failed = red, Stopped/Disabled = dim gray. Background uses the `-light` token variant.
- **Log level toggle**: Segmented button group (DEBUG | INFO | WARN). Active state uses `--ht-accent-light` background with `--ht-accent` text.
- **Sidebar**: 56px collapsed icon rail. Same background temperature as the page. Pulse dot anchored to the bottom. Active nav item highlighted with accent background tint.
