---
schema_version: 1
updated_at: 2026-04-17
---

## Users & Purpose

A developer at their desk — either verifying a fresh deployment is green, or mid-incident figuring out why the garage door automation didn't fire. Pulls up the UI with a question already in mind, not for passive monitoring.

**Task**: Diagnose. Verify. Confirm or refute a hypothesis fast. "Did my handler fire? What values did it see? Did it error? What was the exception?" — then close the tab.

**Context**: Home Assistant power users who write Python automations. Comfortable with terminals, logs, entity IDs. They don't need hand-holding — they need fast answers.

## Brand Personality

Like opening a well-organized toolbox. Everything has a place, you grab what you need, close it, move on. Not a dashboard you stare at — a diagnostic instrument you reach for.

**Tone**: Quiet confidence. Technical without being hostile. Dense without being cluttered. The UI should feel like it was built by someone who uses it daily.

## Aesthetic Direction

### References

- **Linear** — information density and monospace meta text. Compact rows that expand on click. Dense but scannable. Everything where you expect it.
  - **Take**: Row density, expand-on-click pattern, monospace for IDs/timestamps
  - **Leave**: The cool blue palette, the breadcrumb-heavy navigation

- **Vercel dashboard** — KPI strip, status badges, flat-but-not-flat surface hierarchy. Quiet confidence.
  - **Take**: KPI card pattern, status badge language, surface layering approach
  - **Leave**: The aggressive minimalism that sacrifices information density

- **Terminal aesthetic (grown up)** — near-black with emerald and amber has the vibe of a terminal that evolved into a product. Data-forward, chrome-minimal.
  - **Take**: The color temperature, the monospace-heavy data presentation
  - **Leave**: The raw/unpolished feel — this needs to look like a product, not a prototype

- **Prefect (Miter Design)** — state-driven color where every hue earns its place by representing a workflow state. Colorblind-accessible themes. Speed as a feature.
  - **Take**: Deliberateness of state color assignment, the visual hierarchy in flow run pages
  - **Leave**: Radial/constellation visualizations (Hassette's domain is flat lists, not DAGs)

**Visual movement**: Data-dense utility — the "developer tool that happens to have a UI" school. Not editorial minimalism, not SaaS product, not consumer app.

### Domain Concepts

- **Wiring** — handlers connected to entities
- **Pulse** — system liveness via WebSocket
- **Threshold** — state transitions trigger actions
- **Trace** — following what happened from effect to cause
- **Registry** — what's registered, active, dormant

### Color World

The green LED on a running Raspberry Pi. The cool gray of a breaker panel. The red blink of a low-battery smoke detector. The soft glow of a phone screen in a dark room pulling up the UI at midnight. The matte black of a well-made tool.

### Signature Element

The breathing pulse dot — a slow inhale/exhale animation on the WebSocket connection indicator. Emerald when connected (breathing). Red and static when disconnected. The only continuously animated element. It exists because the system maintains a persistent WebSocket to Home Assistant — the dot breathes because the connection is alive.

- Appears in the **StatusBar** (top bar), not the sidebar
- 8px circle, `--ht-accent` color with `breathe` keyframe animation (2.5s ease-in-out infinite)
- Additional states: `connecting` (amber pulse), `degraded` (amber, for DB degradation or dropped events)
- Reduced motion: static dot, no animation

### Defaults Rejected

| Default | Why it's wrong | Better alternative |
|---------|---------------|-------------------|
| Indigo/violet accent | Tailwind default, every AI-generated UI uses this — zero personality | Emerald: "alive, connected, working" — the LED on a running Pi |
| Dark sidebar on light page | Jarring mixed-mode contrast that fights for attention | Sidebar uses same `--ht-bg` and `--ht-surface`, separated by border not color |
| Borders-only depth | Makes the UI feel flat and cheap at low information density | Subtle shadows + borders; shadows establish card hierarchy, borders separate rows |
| Inter/Roboto/system-ui | Generic, says nothing about the product | DM Sans body, Space Grotesk headings, JetBrains Mono data |
| Card nesting | Cards inside cards creates visual noise | Handler rows are list items in bordered containers |
| Bounce/elastic easing | The UI is a tool, not a toy | All transitions use ease-out |
| Warm amber as primary accent | Was the old palette — rejected by user | Amber reserved for state values only |

## Concrete Constraints

- **No rounded corners above 10px** (except pills/badges at `radius-full`) — the product is technical
- **Body text is DM Sans, never a serif** — the diagnostic-tool feel requires geometric sans
- **Maximum 3 color families beyond neutrals** (emerald accent, amber values, red errors) — density demands restraint
- **No drop shadows as primary depth in dark mode** — use border highlights and surface tint differentiation instead; shadows supplement but don't carry depth alone against near-black backgrounds
- **Monospace for all data** — entity IDs, timestamps, handler names, invocation counts, log entries. Most content on the page is mono.
- **No icons without text labels** in main content areas — exceptions: sidebar icon rail, and dense data-row action clusters (e.g., Stop/Reload in app list rows) where universal icons (play/stop/refresh) with `aria-label` and `title` suffice
- **Density is a feature** — row padding is compact (10-12px vertical), meta text gaps are tight (12-16px), whitespace is for section separation not breathing room inside components

## Design Principles

1. **Answer the question** — every page exists to answer a specific diagnostic question. If a component doesn't help answer it, remove it.
2. **Hierarchy through type, not decoration** — font family (heading vs body vs mono), weight, and size create hierarchy. Not borders, backgrounds, or color.
3. **Emerald means alive** — green is reserved for "connected, running, healthy." Don't dilute it on links, buttons, or decorative elements.
4. **Show state, don't narrate it** — a red dot says "failed" faster than a paragraph. Status badges, health bars, and color-coded values over prose descriptions.
5. **Respect the developer** — no onboarding tours, no tooltips on obvious things, no confirmation dialogs for reversible actions. The user knows what they're doing.

## Design Tokens

### Color — Dark Mode (Graphite + Emerald) — Default

| Token | Value | Role |
|-------|-------|------|
| `--ht-bg` | `#111113` | Page canvas — near-black graphite |
| `--ht-surface` | `#222226` | Cards, panels, list rows — perceptible separation from bg |
| `--ht-surface-recessed` | `#2a2a2f` | Hover states, inset areas, expanded details |
| `--ht-surface-sticky` | `#222226` | Sticky headers (same as surface) |
| `--ht-border` | `rgba(255, 255, 255, 0.06)` | Default separation — visible when you look, invisible when you don't |
| `--ht-border-strong` | `rgba(255, 255, 255, 0.10)` | Interactive element borders (inputs, buttons, toggles) |
| `--ht-border-highlight` | `rgba(255, 255, 255, 0.08)` | Card top-edge highlight — simulates light source for depth |
| `--ht-text` | `#ececef` | Primary text |
| `--ht-text-secondary` | `#9898a0` | Secondary labels, meta text |
| `--ht-text-dim` | `#5c5c66` | Tertiary text, timestamps, placeholders |
| `--ht-link` | `#6bab94` | Interactive text — muted emerald, distinct from vivid accent and neutral text |
| `--ht-link-hover` | `#8cc4ad` | Interactive hover state |
| `--ht-accent` | `#34d399` | Status accent — emerald. Reserved for alive/connected/running states, pulse dot |
| `--ht-accent-light` | `rgba(52, 211, 153, 0.10)` | Status accent backgrounds (badges, highlights) |
| `--ht-value` | `#fbbf24` | State values in handler summaries — amber, distinct from accent |
| `--ht-success` | `#34d399` | Healthy/running — same as accent (emerald = "all systems go") |
| `--ht-success-light` | `rgba(52, 211, 153, 0.10)` | Success badge backgrounds |
| `--ht-danger` | `#f87171` | Error, failed, disconnected |
| `--ht-danger-light` | `rgba(248, 113, 113, 0.10)` | Error badge/trace backgrounds |
| `--ht-warning` | `#fbbf24` | Warning states, elevated error rates |
| `--ht-warning-light` | `rgba(251, 191, 36, 0.08)` | Warning badge backgrounds |
| `--ht-shadow-sm` | `0 1px 3px rgba(0, 0, 0, 0.3)` | Cards, containers |
| `--ht-shadow-md` | `0 4px 12px rgba(0, 0, 0, 0.4), 0 1px 3px rgba(0, 0, 0, 0.2)` | Hover lift, dropdowns |

**Rationale**: Graphite neutrals (no blue tint, no warm tint — true neutral gray) keep the same temperature in both modes. Emerald as the primary accent because green = "alive, connected, working" in this domain — the LED on a running Pi, the "all systems go" signal. Amber for state values creates semantic separation from the accent without adding a third hue family. Red for errors is universal and unambiguous.

### Color — Light Mode (Chalk + Emerald)

| Token | Value | Role |
|-------|-------|------|
| `--ht-bg` | `#ededf0` | Page canvas — cool chalk with visible separation from cards |
| `--ht-surface` | `#f9f9fa` | Cards, panels, list rows |
| `--ht-surface-recessed` | `#e6e6ea` | Hover states, inset areas, expanded details |
| `--ht-surface-sticky` | `#f9f9fa` | Sticky headers |
| `--ht-border` | `rgba(0, 0, 0, 0.08)` | Default separation |
| `--ht-border-strong` | `rgba(0, 0, 0, 0.13)` | Interactive element borders |
| `--ht-border-highlight` | `rgba(0, 0, 0, 0.04)` | Card top-edge highlight |
| `--ht-text` | `#111113` | Primary text — near-black graphite |
| `--ht-text-secondary` | `#55555e` | Secondary labels, meta text |
| `--ht-text-dim` | `#9898a0` | Tertiary text, timestamps |
| `--ht-link` | `#1a7a5a` | Interactive text — muted emerald for light backgrounds |
| `--ht-link-hover` | `#0f5c42` | Interactive hover state |
| `--ht-accent` | `#047857` | Status accent — deeper emerald, WCAG AA compliant (5.0:1 on white) |
| `--ht-accent-light` | `rgba(4, 120, 87, 0.07)` | Status accent backgrounds |
| `--ht-value` | `#b45309` | State values — darker amber for light backgrounds |
| `--ht-success` | `#047857` | Healthy/running |
| `--ht-success-light` | `rgba(4, 120, 87, 0.07)` | Success badge backgrounds |
| `--ht-danger` | `#dc2626` | Error, failed, disconnected |
| `--ht-danger-light` | `rgba(220, 38, 38, 0.07)` | Error badge/trace backgrounds |
| `--ht-warning` | `#a16207` | Warning states |
| `--ht-warning-light` | `rgba(161, 98, 7, 0.06)` | Warning badge backgrounds |
| `--ht-shadow-sm` | `0 1px 2px rgba(0, 0, 0, 0.04)` | Cards, containers |
| `--ht-shadow-md` | `0 4px 12px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.03)` | Hover lift, dropdowns |

### Typography

- **Headings**: Space Grotesk (600/700) — geometric, technical character. Distinguishes Hassette from generic admin panels. The only place personality shows in the type system.
- **Body**: DM Sans (400/500) — clean geometric sans that pairs with Space Grotesk without competing. Readable at small sizes for meta text and descriptions.
- **Mono**: JetBrains Mono (400/500/600) — entity IDs, timestamps, handler names, invocation data, log entries. The workhorse font — most data on the page is monospace.
- **Scale**:
  - `--ht-text-xs`: 13px — uppercase labels (INIT STATUS, FIRES, AVG)
  - `--ht-text-sm`: 14px — meta text, badge text, timestamps
  - `--ht-text-base`: 16px — handler summaries, table data, log entries
  - `--ht-text-md`: 17px — body text, descriptions
  - `--ht-text-lg`: 19px — section headings (Event Handlers, Scheduled Jobs)
  - `--ht-text-xl`: 23px — page titles (Garage Proximity)
  - `--ht-text-2xl`: 27px — hero numbers in health cards (0.4%, 18ms, 3m ago)
- **Weights**: 400 (body), 500 (mono emphasis, meta strong values), 600 (headings, stat values), 700 (page title only)
- **Self-hosted**: WOFF2 files in `/frontend/public/fonts/` — DM Sans 400/500/700, Space Grotesk 400/500/600/700, JetBrains Mono 400/500

### Spacing

- **Base**: 4px (`--ht-sp-1`)
- **Scale**: `--ht-sp-1` (4px), `--ht-sp-2` (8px), `--ht-sp-3` (12px), `--ht-sp-4` (16px), `--ht-sp-5` (20px), `--ht-sp-6` (24px), `--ht-sp-8` (32px), `--ht-sp-10` (40px)
- **Density**: Diagnostic tool — density is a feature. Row padding compact (10-12px vertical). Meta text gaps tight (12-16px). Health strip cards modest padding (12px 14px). Whitespace for section separation, not breathing room inside components.

### Depth

- **Strategy**: Subtle shadows + borders. Shadows establish card-level hierarchy. Borders separate rows within lists.
- **Why**: Borders-only was explicitly rejected ("flat and cheap"). Full Bulma-style shadows are too heavy. Single shadow-sm on cards adds dimensionality without weight.
- **Levels**: `--ht-shadow-sm` on cards and containers, `--ht-shadow-md` on hover lift and dropdowns.
- **Dark mode**: Surface bump (#111113 → #222226) provides perceptible luminance separation. Border highlights (`--ht-border-highlight` at 0.08 alpha) on card top edges simulate a light source. Together with shadows, cards are unambiguously visible.

### Border Radius

- **Scale**: `--ht-radius-sm` (6px), `--ht-radius-md` (9px), `--ht-radius-lg` (10px), `--ht-radius-full` (9999px)
- **Character**: Slightly rounded — not sharp (too clinical), not pill-shaped (too playful). 9-10px on cards and list containers. 6px on buttons and inputs. Full round on badges and status dots. The radius says "tool with considered edges."

### Motion

- **Micro**: 120ms `ease-out` — hover state transitions (background, border color)
- **Transition**: 200ms `ease-out` — expand/collapse handler detail, tab switching
- **Signature**: 2.5s `ease-in-out` infinite — the pulse dot breathe animation. Only continuous animation.
- **Reduced motion**: All animations and transitions collapse to `0.01ms`. Pulse dot becomes static.

### Anti-patterns

- **No warm amber/gold as primary accent** — amber is reserved for state values only
- **No dark sidebar on light page** — sidebar uses same `--ht-bg` and `--ht-surface` as main content
- **No borders-only depth** — every card and list container gets `--ht-shadow-sm`, supplemented by border highlights in dark mode
- **No pure black or pure gray** — all neutrals have the graphite tint (`#111113`, `#1a1a1e`)
- **No Inter, Roboto, or system-ui as primary font**
- **No indigo/violet accents** — Tailwind default, AI slop signal
- **No card nesting** — handler rows are list items in bordered containers, not cards inside cards
- **No bounce/elastic easing** — all transitions use `ease-out`
- **No emerald on non-status elements** — accent is reserved for status (alive/connected/running). Links use `--ht-link` (muted emerald). Nav, tabs, toggles, and buttons use neutral treatments. Three semantic layers: vivid emerald = status, muted emerald = interactive, neutral = static text.

## Component Notes

- **Handler rows**: Grid layout — `8px dot | 1fr content | auto stats`. Plain-language summary as primary text. Invocation count, last-fired, avg duration as mono meta text below. Expandable.
- **Health strip**: 4-column grid of compact cards at top of App Detail. Init status, error rate, avg duration, last activity.
- **StatusBar**: Top bar with pulse dot (WebSocket indicator), theme toggle, session scope toggle, and degraded/dropped-events indicators. Pulse dot uses `--ht-accent` with breathe animation when connected; `--ht-danger` and static when disconnected; amber when connecting or degraded.
- **Status badges**: Pill-shaped (radius-full), mono font, colored dot + text. Running = emerald, Failed = red, Stopped/Disabled = dim gray. Background uses `-light` token variant.
- **Log level toggle**: Segmented button group (DEBUG | INFO | WARN). Active state uses `--ht-accent-light` background with `--ht-accent` text.
- **Sidebar**: 56px icon rail (no expanded state). Same background temperature as page (`--ht-bg`). Active nav item uses `--ht-surface-recessed` background (neutral, not accent). Hidden below 768px — replaced by bottom nav on mobile.

## Open Questions

### Remaining polish opportunities

Surface hierarchy and accent reservation are addressed. Remaining gaps from the critique:

- **KPI card hierarchy**: labels and values still lack visual weight differentiation. Consider varying hero number sizes by importance. → `/i-arrange`
- **Health bar treatment**: 4px bars with no label or percentage. Either make them visible (8px, percentage label) or remove from app cards. → `/i-distill`
- **Empty states**: blank space with no guidance. Sessions page, first-run, no-logs states need treatment. → `/i-onboard`
