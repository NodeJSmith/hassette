---
schema_version: 1
updated_at: 2026-05-02
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

- **The Well-Made Notebook** — warm off-whites, serif headings, careful ink — the sensation of a good technical manual. The Ink design system draws from this: Newsreader for headings brings character; Geist body text keeps it modern and fast to read.
  - **Take**: The warmth of off-white backgrounds, the personality of a real serif for display type
  - **Leave**: Slow-reading text columns, ornamental spacing

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

Ink on cream paper. The precise lines of a technical instrument. Status light on a rack-mounted device. The difference between a running process and a crashed one, communicated in a glance — not through vivid color for its own sake, but through restrained, purposeful use of hue against warm neutral ground.

### Signature Element

The breathing pulse dot — a slow inhale/exhale animation on the WebSocket connection indicator. Accent-colored when connected (breathing). Error-colored and static when disconnected. The only continuously animated element. It exists because the system maintains a persistent WebSocket to Home Assistant — the dot breathes because the connection is alive.

- Appears in the **StatusBar** (top bar), not the sidebar
- 8px circle, `--accent` color with `breathe` keyframe animation (2.5s ease-in-out infinite)
- Additional states: `connecting` (muted, static), `degraded` (`--warn`, static), `disconnected` (`--err`, static)
- Reduced motion: static dot, no animation

### Defaults Rejected

| Default | Why it's wrong | Better alternative |
|---------|---------------|-------------------|
| Indigo/violet accent | Tailwind default, every AI-generated UI uses this — zero personality | Ink-1 (near-black) in light mode; periwinkle-blue in dark — earns accent status through restraint |
| Dark sidebar on light page | Jarring mixed-mode contrast that fights for attention | Sidebar uses same `--bg-page` and `--bg-surface`, separated by border not color |
| Borders-only depth | Makes the UI feel flat and cheap at low information density | Subtle shadows + borders; shadows establish card hierarchy, borders separate rows |
| Inter/Roboto/system-ui | Generic, says nothing about the product | Geist body, Newsreader display headings, Geist Mono data |
| Card nesting | Cards inside cards creates visual noise | Handler rows are list items in bordered containers |
| Bounce/elastic easing | The UI is a tool, not a toy | All transitions use the Ink easing curve |
| Warm amber as primary accent | Overused, dilutes status meaning | Warm status tones (ok/warn/err) are semantic-only; never decorative |

## Concrete Constraints

- **No rounded corners above 8px** (except pills at `--r-pill`) — the product is technical
- **Body text is Geist, never a raw system font** — Geist is on-brand and controlled
- **Display headings (h1–h3) use Newsreader** — gives the UI character without being decorative
- **Maximum 4 semantic hues beyond neutrals** (ok, warn, err, mute) — density demands restraint; accent is a neutral in light mode
- **No drop shadows as primary depth in dark mode** — use surface layering and border hierarchy; shadows supplement but don't carry depth alone against near-black backgrounds
- **Monospace for all data** — entity IDs, timestamps, handler names, invocation counts, log entries. Most content on the page is mono.
- **No icons without text labels** in main content areas — exceptions: sidebar icon rail, and dense data-row action clusters (e.g., Stop/Reload in app list rows) where universal icons (play/stop/refresh) with `aria-label` and `title` suffice
- **Density is a feature** — row padding is compact (10-12px vertical), meta text gaps are tight (12-16px), whitespace is for section separation not breathing room inside components

## Design Principles

1. **Answer the question** — every page exists to answer a specific diagnostic question. If a component doesn't help answer it, remove it.
2. **Hierarchy through type, not decoration** — Newsreader headings vs Geist body vs Geist Mono data create hierarchy. Not borders, backgrounds, or color for its own sake.
3. **Green means ok** — `--ok` is reserved for "connected, running, healthy." Don't dilute it on links, buttons, or decorative elements.
4. **Show state, don't narrate it** — a colored dot says "failed" faster than a paragraph. Status badges, health bars, and color-coded values over prose descriptions.
5. **Respect the developer** — no onboarding tours, no tooltips on obvious things, no confirmation dialogs for reversible actions. The user knows what they're doing.

## Design Tokens

The design system uses unprefixed Ink tokens (no `--ht-*` prefix). Light mode is the `:root` default; dark mode activates via `[data-theme="dark"]`.

### Surfaces

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--bg-page` | `#FAFAF8` | `#111316` | Page canvas — warm off-white / deep neutral |
| `--bg-surface` | `#FFFFFF` | `#191B1F` | Cards, panels, list rows |
| `--bg-sunken` | `#F4F4F1` | `#15171B` | Inset areas, code backgrounds |
| `--bg-active` | `#F0F0EC` | `#1D2026` | Hover states, expanded details |

### Ink (Text)

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--ink-1` | `#16181C` | `#EDEFF3` | Primary text |
| `--ink-2` | `#4A4D54` | `#B5B9C0` | Secondary labels, meta text |
| `--ink-3` | `#787C84` | `#888D97` | Tertiary text, timestamps, placeholders |
| `--ink-4` | `#B0B3B8` | `#5A5E66` | Disabled text |

### Lines (Borders)

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--line-1` | `#E6E6E2` | `#272A30` | Default separation |
| `--line-2` | `#ECECE8` | `#1F2227` | Subtle/secondary separators |
| `--line-strong` | `#D0D0CC` | `#3A3E46` | Interactive element borders |

### Accent

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--accent` | `var(--ink-1)` | `#7A8AFF` | Primary interactive color |
| `--accent-ink` | `var(--bg-page)` | `#0F1115` | Text on accent background |
| `--accent-hover` | `#2A2D33` | `#93A0FF` | Hover state |
| `--accent-soft` | `#E8E8E5` | `#1A1F36` | Soft accent background |

**Rationale**: In light mode, accent is `ink-1` (near-black) — a deliberate choice. The system has personality through type (Newsreader) and surface warmth (`#FAFAF8`), not through a colored accent. In dark mode, periwinkle-blue earns its place without the "every AI-generated UI uses indigo" feel.

### Status

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--ok` / `--ok-bg` | `#1F7A4D` / `#EAF3EE` | `#5FB988` / `#19241E` | Running, healthy, connected |
| `--warn` / `--warn-bg` | `#9A6A12` / `#F5EEDD` | `#D9B36E` / `#272219` | Warning, elevated error rate |
| `--err` / `--err-bg` | `#B53024` / `#F5DEDC` | `#E08278` / `#28191A` | Error, failed, disconnected |
| `--mute` / `--mute-bg` | `#9097A0` / `#EFF0EC` | `#6A707A` / `#1D1F23` | Stopped, disabled, unknown |

### Typography

- **Display/headings (h1–h3)**: Newsreader 400 — a refined newspaper serif. Gives the UI character and warmth without being decorative. Headings feel authored, not generated.
- **Body**: Geist 400/500 — clean, modern sans-serif by Vercel. Fast to read, pairs well with Newsreader without competing.
- **Mono**: Geist Mono 400/500 — entity IDs, timestamps, handler names, invocation data, log entries. The workhorse font — most data on the page is monospace.
- **Scale**:
  - `--fs-display` / `--lh-display`: 38px / 1.05 — hero display text
  - `--fs-h1` / `--lh-h1`: 28px / 1.15 — page titles
  - `--fs-h2` / `--lh-h2`: 20px / 1.25 — section headings
  - `--fs-h3` / `--lh-h3`: 16px / 1.35 — subsection headings
  - `--fs-body` / `--lh-body`: 14px / 1.55 — body text, table data
  - `--fs-small` / `--lh-small`: 12.5px / 1.5 — meta text, captions
  - `--fs-micro` / `--lh-micro`: 11px / 1.4 — labels, uppercase tags
  - `--fs-mono-sm` / `--fs-mono-md`: 12px / 13px — code, data
- **Letter spacing**: Display and headings use negative tracking (`--tr-display: -0.025em` → `--tr-h3: -0.005em`) for optical tightness at large sizes.
- **Self-hosted**: WOFF2 files in `/frontend/public/fonts/` — Newsreader 400, Geist 400/500, Geist Mono 400/500

### Spacing

- **Base**: 4px (`--sp-1`)
- **Scale**: `--sp-1` (4px) through `--sp-10` (72px)
- **Density**: Diagnostic tool — density is a feature. Row padding compact (10-12px vertical). Meta text gaps tight (12-16px). Whitespace for section separation, not breathing room inside components.

### Shadows

- **`--shadow-1`**: `0 1px 2px rgba(20, 22, 26, 0.04)` — subtle card lift (light mode)
- **`--shadow-2`**: `0 2px 8px … + 0 1px 2px …` — card prominence
- **`--shadow-3`**: `0 8px 24px … + 0 2px 6px …` — dropdowns, modals
- **Dark mode**: Same shadow variables use higher opacity (`0.3 / 0.4 / 0.5`) against near-black backgrounds.

### Border Radius

- **`--r-sm`**: 4px — inputs, code spans
- **`--r-md`**: 6px — buttons, cards, list containers
- **`--r-lg`**: 8px — panels, larger cards
- **`--r-xl`**: 12px — modals, large containers
- **`--r-pill`**: 999px — badges, status dots

### Motion

- **`--t-fast`**: 120ms — hover state transitions (background, border color)
- **`--t-med`**: 200ms — expand/collapse, tab switching
- **`--ease`**: `cubic-bezier(0.4, 0, 0.2, 1)` — the Ink easing curve
- **Signature animation**: pulse dot breathe, 2.5s ease-in-out infinite. Only continuous animation.
- **Reduced motion**: `@media (prefers-reduced-motion: reduce)` — all animations collapse to 0.01ms

### Anti-patterns

- **No `--ht-*` prefixed tokens** — the old Graphite+Emerald system is replaced; all tokens are unprefixed Ink tokens
- **No raw hex values in component CSS** — always reference tokens
- **No sidebar on same dark tone as content** — sidebar uses `--bg-page` / `--bg-surface` in both modes
- **No shadows for depth** — borders are the primary depth mechanism; shadows reserved for floating surfaces only (modals, command palette)
- **No blue/indigo/violet accent** — light mode accent is `ink-1` (intentional); dark mode uses restrained periwinkle
- **No card nesting** — handler rows are list items in bordered containers, not cards inside cards
- **No bounce/elastic easing** — all transitions use `--ease`
- **No status colors on non-status elements** — `--ok` / `--warn` / `--err` reserved for state communication only

## Component Notes

- **Handler rows**: Grid layout — `8px dot | 1fr content | auto stats`. Plain-language summary as primary text. Invocation count, last-fired, avg duration as mono meta text below. Expandable.
- **Health strip**: 4-column grid of compact cards at top of App Detail. Init status, error rate, avg duration, last activity.
- **StatusBar**: Top bar with pulse dot (WebSocket indicator), theme toggle, time-preset selector, and degraded/dropped-events indicators. Pulse dot uses `--accent` with breathe animation when connected; `--err` and static when disconnected; `--warn` when degraded.
- **Status badges**: Pill-shaped (`--r-pill`), mono font, shape indicator + text. Running = `--ok`, Failed = `--err`, Stopped/Disabled = `--mute`. Background uses `*-bg` paired token.
- **Log level toggle**: Segmented button group (DEBUG | INFO | WARN). Active state uses `--accent-soft` background with `--accent` text.
- **Sidebar**: 240px panel with icon + label navigation. Same background temperature as page (`--bg-page`). Active nav item uses `--bg-active` background (neutral). Hidden below 768px — replaced by bottom nav on mobile.

## Open Questions

### Remaining polish opportunities

Surface hierarchy and accent reservation are addressed. Remaining gaps from the critique:

- **KPI card hierarchy**: labels and values still lack visual weight differentiation. Consider varying hero number sizes by importance. → `/i-arrange`
- **Health bar treatment**: 4px bars with no label or percentage. Either make them visible (8px, percentage label) or remove from app cards. → `/i-distill`
- **Empty states**: blank space with no guidance. Sessions page, first-run, no-logs states need treatment. → `/i-onboard`
