---
schema_version: 1
updated_at: 2026-07-10
---

# Hassette Design System

## Users & Purpose

Hassette's frontend is for a developer/operator running Home Assistant automations and checking whether the system is healthy. They are usually diagnosing a concrete question, not browsing casually:

- Is everything running?
- Which app failed?
- Did this handler or job fire?
- Why did it fail, skip, timeout, cancel, or stop firing?
- What code, config, or log line explains the behavior?

The user may be at a desktop doing focused debugging, or on a phone doing a quick homelab health check. The interface should support both, but the desktop experience can be denser because the primary job is diagnostic inspection.

## Brand Personality

Hassette should feel like a quiet operational console: calm, precise, trustworthy, and compact. It should have enough warmth and craft to avoid feeling like a generic admin panel, but it should not become decorative.

The current UI is closest to a data-dense troubleshooting console with a light editorial touch: graphite surfaces, restrained green status accents, serif page titles, mono data, and compact tables.

The desired refinement is not a redesign into a consumer smart-home dashboard. It is a cleanup pass that makes the existing direction easier to scan, read, and understand.

## Aesthetic Direction

### Current Movement

Dense operational utility with editorial restraint.

### Keep

- Compact tables and code/config visibility.
- Calm graphite/green status language.
- Serif display titles as a distinctive product note.
- Monospace for code, IDs, paths, timings, and table data where precision matters.
- Subtle surfaces and borders rather than loud panels.
- App Detail as the diagnostic center of gravity.

### Improve

- Stronger page hierarchy so users know what to look at first.
- Clearer grouping inside dense pages, especially app detail and config.
- More readable tables: row scanning, link emphasis, column priority, and error prominence.
- More explanatory status language: show what happened and what the user can do next.
- More consistent spacing rhythm between page headers, stats strips, tables, and cards.

### Avoid

- Generic SaaS dashboard gloss.
- Home Assistant visual mimicry.
- Terminal cosplay: dark neon, excessive monospace, fake shell aesthetics.
- Consumer smart-home friendliness that hides diagnostic detail.
- Decorative charts or cards that do not answer an operational question.
- Over-soft rounded UI that weakens the technical character.

## Domain Concepts

- Automations as registered runtime units.
- Handlers and jobs as things that fire, skip, fail, cancel, or time out.
- Event history as the path to understanding behavior.
- App instances as operational processes, not marketing objects.
- Logs, code, config, and telemetry as connected evidence.
- Health as a current system state plus recent activity, not a single badge.
- Time windows as an inspection lens.

## Signature Element

The signature Hassette pattern should be an evidence trail: a status or failure should lead directly to the related handler/job, recent run, log line, code registration, and config source.

This should appear in visual structure, not only navigation:

- Rows should expose enough context to explain why they exist.
- Error blocks should link or point to the relevant handler, traceback, or log drawer.
- App detail should connect summary health to handler cards, recent activity, logs, code, and config.
- Search/filter affordances should help narrow evidence quickly.

## Concrete Constraints

- Keep the UI information-dense, but do not let density flatten hierarchy.
- Prefer readable diagnostic grouping over adding new navigation depth.
- Use color semantically and sparingly: green for healthy, red for failure, amber for warning/degraded, muted gray for inactive/unknown.
- Do not introduce visual variants by passing ad hoc CSS classes into shared components. Add semantic component variants when a visual distinction is needed.
- Tables should share the same interaction model wherever practical: search above, filters in column headers or mobile footer, count in footer, contained table card.
- Mobile should prioritize quick checks: health, error rate/failures, and whether critical apps are running.
- Code/config/log views should feel like evidence surfaces, not separate developer toys.
- All component-specific styles belong in CSS Modules. Global styles are reserved for tokens, reset, typography, layout, tables, and utilities.

## Design Principles

### 1. Lead With The Diagnostic Answer

Every page should make the most likely diagnostic question obvious. The first visual destination should usually be health, failure, recent activity, or the active filter/search context.

### 2. Dense, Not Crowded

Hassette can show a lot of data at once, but related information must be grouped clearly. Use spacing, borders, section titles, and subdued metadata to create scan paths.

### 3. Evidence Should Be Connected

When the UI shows a failure or surprising status, it should make the supporting evidence nearby or one click away: handler detail, run history, log drawer, code, traceback, or config.

### 4. Quiet By Default, Loud On Exceptions

Healthy/running states should be calm. Failures, warnings, blocked states, and degraded telemetry should break the calm enough to draw attention without overwhelming the page.

### 5. Components Carry The System

Buttons, badges, chips, cards, table shells, sort headers, empty states, and popovers should encode visual decisions. Page code should assemble domain-specific content, not invent one-off UI language.

---

## Design Tokens

All tokens are defined in `frontend/src/tokens.css`. Light theme is the `:root` default; dark theme overrides live under `[data-theme="dark"]`. These values document the current implemented state — some remain open for revision (see Open Questions at the end of this file).

For prescriptive design rules on how to apply these tokens — typography hierarchy, spacing rhythm, contrast safety, data formatting, information density — see `frontend/DESIGN_RULES.md`.

### Color Palette

#### Surfaces

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg-page` | `oklch(0.95 0.006 var(--accent-hue))` | `#0c0e11` | Outer page background |
| `--bg-surface` | `oklch(0.995 0.002 var(--accent-hue))` | `#1a1c21` | Main panels, cards, sidebar |
| `--bg-sunken` | `oklch(0.955 0.006 var(--accent-hue))` | `#141619` | Table headers, recessed inputs, code regions |
| `--bg-active` | `oklch(0.92 0.01 var(--accent-hue))` | `#22242a` | Hover and active surfaces |
| `--bg-chrome` | `oklch(0.96 0.005 var(--accent-hue))` | `#131517` | Status bar and app chrome |

Light-mode surfaces use oklch with accent-hue tinting for subtle warmth. Dark-mode surfaces use raw hex with no hue tinting.

#### Ink (Text)

| Token | Light | Dark | Role |
|---|---|---|---|
| `--ink-1` | `#16181c` | `#edeff3` | Primary text |
| `--ink-2` | `#4a4d54` | `#b5b9c0` | Secondary text, descriptions |
| `--ink-3` | `#787c84` | `#888d97` | Muted metadata, labels |
| `--ink-4` | `#b0b3b8` | `#5a5e66` | Disabled/subtle metadata, placeholders |

#### Lines (Borders)

| Token | Light | Dark | Role |
|---|---|---|---|
| `--line-1` | `#e6e6e2` | `#272a30` | Subtle dividers, section borders |
| `--line-2` | `#ecece8` | `#1f2227` | Softest dividers, internal borders |
| `--line-strong` | `#d0d0cc` | `#3a3e46` | Card borders, table containers, prominent dividers |

#### Accent

| Token | Light | Dark | Role |
|---|---|---|---|
| `--accent` | `oklch(0.5 0.09 255)` | `oklch(0.72 0.09 255)` | Navigation, active state, primary emphasis |
| `--accent-hover` | `oklch(0.42 0.09 255)` | `oklch(0.8 0.09 255)` | Accent hover state |
| `--accent-ink` | `oklch(0.98 0.005 255)` | `oklch(0.15 0.01 255)` | Text on accent background |
| `--accent-soft` | `oklch(0.95 0.0225 255)` | `oklch(0.22 0.036 255)` | Active tab backgrounds, focus rings |
| `--accent-border` | `oklch(0.65 0.054 255)` | `oklch(0.55 0.054 255)` | Instance switcher active border |
| `--accent-bg` | `oklch(0.97 0.0135 255)` | `oklch(0.18 0.018 255)` | Instance switcher active background |

Accent hue is `255` (blue-violet). Chroma is `0.09`. Both are CSS custom properties (`--accent-hue`, `--accent-chroma`) so the entire accent family shifts if the hue changes.

#### Status

| Token | Light | Dark | Role |
|---|---|---|---|
| `--ok` | `#1f7a4d` | `#5fb988` | Healthy, running, success |
| `--ok-bg` | `#eaf3ee` | `#19241e` | Success background tint |
| `--warn` | `#9a6a12` | `#d9b36e` | Warning, degraded, blocked |
| `--warn-bg` | `#f5eedd` | `#272219` | Warning background tint |
| `--err` | `#b53024` | `#e08278` | Failure, error, crashed |
| `--err-bg` | `#f5dedc` | `#28191a` | Error background tint |
| `--cancel` | `#1f6f9a` | `#6fb8d9` | Cancelled (no `--cancel-bg` token) |
| `--mute` | `#9097a0` | `#6a707a` | Inactive, unknown, disabled |
| `--mute-bg` | `#eff0ec` | `#1d1f23` | Muted background tint |

#### Utility

| Token | Light | Dark | Role |
|---|---|---|---|
| `--input-bg` | `#ffffff` | `#1f2227` | Input field backgrounds |
| `--overlay-bg` | `rgba(0,0,0,0.45)` | `rgba(0,0,0,0.5)` | Modal/drawer backdrops |
| `--err-dark` | `#9a2020` | `#7a1a1a` | Error emphasis variant |
| `--code-bg` | `var(--bg-sunken)` | `var(--bg-sunken)` | Code block backgrounds |
| `--code-comment` | `var(--ink-3)` | `var(--ink-3)` | Code comment text |

**Rationale**: The palette supports a restrained operational console. Surfaces stay close together, status colors carry meaning, and accent color is used primarily for orientation rather than decoration.

### Typography

#### Font Stacks

| Token | Stack | Usage |
|---|---|---|
| `--font-display` | Newsreader, Source Serif Pro, Georgia, serif | Page titles, product wordmark |
| `--font-body` | Geist, system-ui, -apple-system, sans-serif | Navigation, labels, explanatory text, controls |
| `--font-mono` | Geist Mono, ui-monospace, SF Mono, Menlo, monospace | Code, IDs, timestamps, paths, timings, table data |

The serif display face is a deliberate accent — an editorial note in an otherwise technical interface.

#### Type Scale

| Token | Size | Line Height | Tracking | Usage |
|---|---|---|---|---|
| `--fs-display` | 38px | `--lh-display` 1.05 | `--tr-display` -0.025em | Page titles (with `--font-display`) |
| `--fs-h1` | 28px | `--lh-h1` 1.15 | `--tr-h1` -0.02em | Major section headings |
| `--fs-h2` | 20px | `--lh-h2` 1.25 | `--tr-h2` -0.015em | Subsection headings |
| `--fs-h3` | 16px | `--lh-h3` 1.35 | `--tr-h3` -0.005em | Card headings, sidebar wordmark |
| `--fs-body` | 14px | `--lh-body` 1.55 | — | Body text, nav items |
| `--fs-small` | 12.5px | `--lh-small` 1.5 | — | Table cells, app links |
| `--fs-micro` | 12px | `--lh-micro` 1.4 | — | Badges, chips, inputs, metadata |
| `--fs-xs` | 11px | `--lh-xs` 1.3 | — | Smallest labels |
| `--fs-stat` | 26px | — | — | StatsStrip values |
| `--fs-badge` | 11.5px | — | — | Badge text (specific) |
| `--fs-mono-sm` | 12px | — | — | Small monospace (inputs, code) |
| `--fs-mono-md` | 13px | — | — | Medium monospace (tabs) |

`--lh-relaxed` (1.6) is used for code blocks, tracebacks, and compact button rows where lines need more breathing room than `--lh-small` (1.5).

#### Letter Spacing

| Token | Value | Usage |
|---|---|---|
| `--tr-label-tight` | 0.03em | Mobile filter labels |
| `--tr-label-mid` | 0.04em | Diagnostics, config tab labels |
| `--tr-label` | 0.05em | Uppercase table headers, sidebar labels |
| `--tr-label-wide` | 0.07em | StatsStrip labels, section headers |

#### Weights

| Token | Value | Usage |
|---|---|---|
| `--fw-normal` | 400 | Body text, display titles |
| `--fw-medium` | 500 | Buttons, badges, chips, stat values, active nav |
| `--fw-semibold` | 600 | Active sort columns, dialog titles, tab badges |
| `--fw-bold` | 700 | Rare emphasis |

### Spacing

4px base grid with half-steps where useful.

| Token | Value | Usage examples |
|---|---|---|
| `--sp-px` | 1px | Hairline border width, sub-grid vertical padding (chips, compact badges) |
| `--sp-0` | 2px | Focus outline offset, micro margins |
| `--sp-1` | 4px | Icon button padding, tight gaps |
| `--sp-1h` | 6px | Input vertical padding (half-step) |
| `--sp-2` | 8px | Shell gap, table cell padding, inner gaps |
| `--sp-3` | 12px | Card compact padding, section gaps, nav item padding |
| `--sp-3h` | 14px | StatsStrip cell padding (half-step) |
| `--sp-4` | 16px | Page header gaps, command palette padding |
| `--sp-5` | 20px | Card default padding |
| `--sp-6` | 24px | Card error padding, dialog padding, empty state padding |
| `--sp-7` | 32px | Page padding and gap, status bar horizontal padding |
| `--sp-8` | 40px | Dialog width margin |
| `--sp-9` | 56px | (Reserved) |
| `--sp-10` | 72px | (Reserved) |

### Border Radius

| Token | Value | Mobile | Character |
|---|---|---|---|
| `--r-sm` | 6px | — | Chips, filter buttons, focus outlines |
| `--r-md` | 8px | — | Cards, buttons, inputs, table containers, popovers |
| `--r-lg` | 12px | 10px | Main content area top corners |
| `--r-xl` | 20px | 16px | Dialogs, command palette |
| `--r-pill` | 999px | — | Badges, pulse dots, spinner |

Moderately technical — not sharp-industrial and not bubbly.

### Elevation & Shadows

| Token | Light | Dark | Usage |
|---|---|---|---|
| `--shadow-1` | `0 1px 2px rgba(20,22,26,0.04)` | `0 1px 2px rgba(0,0,0,0.3)` | Subtle, mobile cards |
| `--shadow-2` | `0 2px 8px rgba(20,22,26,0.06), 0 1px 2px rgba(20,22,26,0.04)` | `0 2px 8px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)` | Cards, table containers, stats strips |
| `--shadow-3` | `0 8px 24px rgba(20,22,26,0.08), 0 2px 6px rgba(20,22,26,0.04)` | `0 8px 24px rgba(0,0,0,0.5), 0 2px 6px rgba(0,0,0,0.3)` | Dialogs, command palette, elevated popovers |

Dark mode shadows use stronger opacity for definition against dark backgrounds. Strategy is subtle shadows plus visible borders — depth separates working surfaces from the page without dramatic elevation.

### Component Padding & Gap

Component-local custom properties for em-based padding and gap values. These scale with font-size and are prefixed per component to avoid collisions (CSS Modules scopes class selectors, not custom property names).

| Component | Pad Y | Pad X | Gap | Defined in |
|---|---|---|---|---|
| **Button** (default) | `--btn-pad-y` 0.4em | `--btn-pad-x` 0.85em | `--btn-gap` 0.35em | `button.module.css` |
| Button sm | 0.25em | 0.6em | — | |
| Button xs | 0.15em | 0.45em | — | |
| **Badge** (default) | `--badge-pad-y` 0.15em | `--badge-pad-x` 0.55em | `--badge-gap` 0.25em | `badge.module.css` |
| Badge xs | 0.05em | 0.4em | — | |
| Badge sm | 0.1em | 0.45em | — | |
| Badge md | 0.2em | 0.65em | — | |
| **Inline Code** | `--code-pad-y` 0.1em | `--code-pad-x` 0.35em | — | `typography.css` |

These are em-based so they scale with the component's font-size across size variants. They are not global tokens — they live on the component's base selector and size variants override them via cascade.

### Effects

| Token | Value | Usage |
|---|---|---|
| `--blur-overlay` | 2px | Backdrop blur for overlays (command palette, confirm dialog) |
| `--border-med` | 2px | Focus-visible outlines, failing-state accent borders |
| `--border-thick` | 3px | Heavy borders (spinner track, error accent borders) |

### Motion

| Token | Value | Usage |
|---|---|---|
| `--t-fast` | 120ms | Hover, color, background transitions |
| `--t-med` | 200ms | Drawer slide, layout shifts |
| `--t-spin` | 0.8s | Spinner animation duration |
| `--ease` | `cubic-bezier(0.4, 0, 0.2, 1)` | All transitions |

The breathing animation (connection pulse) cycles opacity `--op-ghost` to 1.0 over 2.5s, ease-in-out, infinite. No spring or bounce curves anywhere.

Motion confirms interactions and orients users during overlays/drawers. No decorative animation except the connection pulse.

### Z-Index

| Token | Value | Layer |
|---|---|---|
| `--z-table-head` | 1 | Sticky table headers |
| `--z-tooltip` | 15 | Tooltips, info popovers |
| `--z-sidebar` | 30 | Desktop sidebar |
| `--z-drawer-bg` | 55 | Mobile drawer backdrop |
| `--z-drawer` | 60 | Mobile drawer, column filter popovers |
| `--z-status-bar` | 65 | Fixed mobile status bar |
| `--z-dialog` | 100 | Modal dialogs (backdrop + 1 for content) |
| `--z-palette-bg` | 200 | Command palette backdrop |
| `--z-palette` | 201 | Command palette panel |
| `--z-skip` | 1000 | Accessibility skip link |

### Opacity

| Token | Value | Usage |
|---|---|---|
| `--op-ghost` | 0.35 | Breathing animation low point |
| `--op-disabled` | 0.5 | Disabled elements |
| `--op-muted` | 0.7 | Muted overlays |
| `--op-subtle` | 0.9 | Hover dimming (brand link, primary button) |

### Component Sizing

| Token | Value | Usage |
|---|---|---|
| `--sz-sidebar` | 240px | Sidebar width, layout grid and mobile drawer |
| `--sz-search-min` | 160px | Minimum width for search inputs |
| `--sz-touch` | 44px | WCAG touch target minimum (applied at ≤900px) |
| `--sz-icon-sm` | 14px | Standard inline icon size |
| `--sz-popover-min` | 200px | Minimum width for popovers (column filter, mobile filter panel) |
| `--sz-popover-max` | 280px | Maximum width for popovers (column filter, info popover) |
| `--sz-content-narrow` | 320px | Maximum width for narrow centered content (empty state body) |
| `--sz-dialog-min` | 320px | Minimum width for dialogs (confirm dialog) |
| `--sz-dialog-max` | 480px | Maximum width for dialogs (confirm dialog) |
| `--sz-drawer` | 400px | Log detail drawer width |
| `--sz-palette` | 620px | Command palette width (clamped to 90% on small screens) |

---

## Layout

### Shell Structure

The app shell is a CSS grid: 240px sidebar + 1fr main content area. The main area has rounded top corners (`--r-lg`), `--shadow-2`, and scrolls independently.

```
.ht-layout (grid: 240px 1fr, gap --sp-2, padded right/top/bottom)
  Sidebar (sticky, full height)
  .ht-main (scrollable, --bg-surface, rounded top)
    StatusBar (inline on desktop, fixed on mobile)
    .ht-page (content, --sp-7 padding and gap)
```

### Sidebar

Width: `--sz-sidebar`, `position: sticky; top: 0`, `--bg-page` background.

**Sections top to bottom:**
1. **Brand** — Newsreader wordmark (`--fs-h3`), version in mono (`--fs-micro`, `--ink-3`), bordered bottom
2. **Cmd-K trigger** — button styled as a sunken pill (`--bg-sunken`, `--line-1` border, `--r-md`)
3. **Main navigation** — links with icons, `--fs-body`, `--r-md` radius. Active: `--accent-soft` background, `--accent` text, `--fw-medium`
4. **App navigation** — scrollable section with search input, collapsible status groups, app links

**Status groups** in sidebar: collapsible headers with StatusShape indicator, uppercase mono label, count badge. Groups with errors/warnings use `--err`/`--warn` on the label.

**App links:** `--font-mono`, `--fs-small`. Hover: `--accent` color.

### Status Bar

Horizontal bar at top of main area. `--bg-chrome` background, `--line-1` bottom border.

**Contents:** time preset selector (left), WebSocket status pulse + optional indicators + theme toggle (right).

**Pulse dot:** 8px circle, `--r-pill`. Colors: connected = `--ok` with breathing animation, connecting = `--mute`, disconnected = `--err`, degraded = `--warn`.

**Time preset selector (desktop):** segmented button row with `--line-1` border, `--r-md` radius. Active preset: `--accent-soft` background, `--accent` text. Mobile: native `<select>` dropdown.

### Responsive Breakpoints

| Breakpoint | Constant | Changes |
|---|---|---|
| **≤900px** | `BREAKPOINT_SIDEBAR` | Sidebar hidden, hamburger menu shown, grid collapses to single column, main area loses border-radius and shadow, touch targets enlarged to `--sz-touch` |
| **≤768px** | `BREAKPOINT_MOBILE` | Status bar becomes fixed, page padding reduces to `--sp-3`, search inputs go full-width, stats strip drops to 3 columns, handler table replaced by card layout, tab strip scrolls horizontally, column filters consolidate into footer |
| **≤480px** | `BREAKPOINT_SMALL_MOBILE` | Page padding reduces to `--sp-2`, uptime display hidden |

These constants are synced between CSS media queries and `use-media-query.ts`.

### Page Patterns

#### Standard Table Page (Apps, Handlers)

```
.ht-page
  .ht-page-header > h1.ht-display
  .ht-table-section
    StatsStrip? (optional summary stats)
    input.ht-search (align-self: flex-end)
    TableCard
      table.ht-table.ht-table--fixed
        colgroup (explicit column widths)
        thead > SortHeader per column
        tbody > rows
      TableFooter (count + mobile filters)
```

Page gap: `--sp-7`. Table section gap: `--sp-3`. Display heading: `--font-display`, `--fs-h1`.

Column widths are set per-page via `<colgroup>`. Mobile (≤900px) hides lower-priority columns and reallocates widths.

#### Detail Page (App Detail)

```
.ht-page
  Identity section (instance switcher + header + tab strip)
  Tab panel (active tab content)
```

**Tab strip:** inline row of links, `--line-1` border, `--r-sm` radius. Active tab: gradient fade to `--accent-soft`. Tabs: overview, handlers, code, logs, config.

**Multi-instance:** grid `repeat(auto-fill, minmax(280px, 1fr))` of instance cards. Active instance: `--accent-bg` background, `--accent-border` border.

---

## Components

All shared components live in `frontend/src/components/shared/`. Use these instead of raw CSS class strings.

### Button

**Variants:** `default`, `primary`, `success`, `warning`, `info`, `danger`
**Sizes:** default, `sm`, `xs`
**Modifiers:** `ghost` (transparent bg/border), `icon` (square padding for icon-only)

| Variant | Background | Border | Text | Hover |
|---|---|---|---|---|
| default | `--bg-surface` | `--line-strong` | `--ink-1` | bg: `--bg-sunken` |
| primary | `--accent` | `--accent` | `--accent-ink` | opacity: `--op-subtle` |
| success | `--bg-surface` | `--ok` | `--ok` | bg: `--ok-bg` |
| warning | `--bg-surface` | `--warn` | `--warn` | bg: `--warn-bg` |
| info | `--bg-surface` | `--line-strong` | `--accent` | bg: `--bg-sunken`, text: `--accent-hover` |
| danger | transparent | `--err` | `--err` | bg: `--err-bg` |

**Ghost modifier:** border and background become transparent. Hover shows `--bg-sunken` (or status-bg for semantic variants).

**Base:** `--font-body`, `--fs-small`, `--fw-medium`, `--r-md` radius, `--t-fast` transitions. Padding: `--btn-pad-y` / `--btn-pad-x` (em-based, scales with font size). Icon mode: `--sp-1` padding, SVG sized `--sp-4`.

**Sizes:** `sm` and `xs` use `--fs-micro` and override `--btn-pad-y` / `--btn-pad-x` to tighter values.

**Responsive (≤900px):** `sm`, `xs`, and `icon` variants get min-height `--sz-touch` for WCAG touch targets.

### Badge

**Variants:** `success`, `danger`, `warning`, `neutral`, `info`
**Sizes:** `xs`, `sm`, default, `md`

| Variant | Text | Background |
|---|---|---|
| success | `--ok` | `--ok-bg` |
| danger | `--err` | `--err-bg` |
| warning | `--warn` | `--warn-bg` |
| neutral | `--ink-3` | `--bg-sunken` |
| info | `--accent` | `--accent-soft` |

**Base:** `--r-pill` (full pill shape), `--fs-micro`, `--fw-medium`, `--badge-pad-y` / `--badge-pad-x` padding. No interactive states (static display element).

`BadgeVariant` extends `StatusVariant` with `"info"` — the info variant is used directly by components, not derived from status mapping functions.

### Card

**Variants:** default, `compact`, `config`, `error`

| Variant | Padding | Notes |
|---|---|---|
| default | `--sp-5` | Standard card |
| compact | `--sp-3` | Tighter padding, same border/shadow |
| config | 0 | Flush inner content, overflow hidden |
| error | `--sp-6` | Standalone error display, centered text |

**Base:** `--bg-surface`, `1px solid --line-strong`, `--r-md`, `--shadow-2`.

**Responsive (≤768px):** shadow reduces to `--shadow-1`, border softens to `--line-1`. At ≤480px: padding reduces to `--sp-3`.

### Chip

**Variants:** `modifier`, `schedule`, `kind`, `origin`, `muted`
**Sizes:** default, `sm`

| Variant | Font | Border | Background | Text |
|---|---|---|---|---|
| modifier | `--font-mono` | `color-mix(--accent 30%)` | `color-mix(--accent 12%)` | `--ink-1` |
| schedule | `--font-mono` | `color-mix(--ok 25%)` | `color-mix(--ok 10%)` | `--ink-3` |
| kind | `--font-body` | per-kind color | transparent | per-kind color |
| origin | `--font-mono` | `--line-2` | transparent | `--ink-3` |
| muted | `--font-mono` | `--line-1` | `--bg-sunken` | `--ink-3` |

**Kind sub-variants** (when `variant="kind"`):

| Kind | Border/Text Color |
|---|---|
| ok | `--ok` |
| warn | `--warn` |
| err | `--err` |
| cancel | `--cancel` |
| mute | `--ink-4` |

**Base:** `--r-sm`, `--fs-micro`, `--fw-medium`. No interactive states.

Origin variant uses uppercase + `--tr-label` letter spacing.

### StatusShape

SVG geometric indicators for inline status display. Each kind maps to a distinct shape:

| Kind | Shape | Fill | Notes |
|---|---|---|---|
| ok | Circle | `--ok` | Filled |
| warn | Triangle | `--warn` | Filled |
| err | Rounded square | `--err` | Filled |
| cancel | Diamond | `--cancel` | Filled |
| mute | Ring | `--mute` | Stroke-only (hollow) |

Used in sidebar app groups, table rows, and command palette results. Sized by the parent context. No interactive states.

### StatsStrip

Grid of labeled stat cells. Columns set via `cols` prop (default 7).

**Structure:** `--bg-surface`, `--line-strong` border, `--r-md` radius, `--shadow-2`.

**Cell:** label in `--font-mono`, uppercase, `--fs-micro`, `--tr-label-wide`, `--ink-3`. Value in `--font-body`, `--fs-stat`, `--fw-medium`.

**Tone colors:** cells accept a tone (ok, warn, err, cancel, mute) that colors the value. Zero-value cells dim both label and value to `--ink-4`.

**Responsive (≤768px):** grid drops to 3 columns; overflow cells get a top border.

### Tooltip

CSS-only via `::after` pseudo-element on a wrapper. No JavaScript positioning.

**Appearance:** `--ink-1` background (inverted), `--bg-page` text, `--r-sm` radius, `--shadow-2`. Positioned above trigger with `--sp-1` gap.

**Activation:** hover or focus-visible → opacity 1 with `--t-fast` transition.

### InfoPopover

JavaScript-positioned floating panel for contextual help. Uses floating-ui.

**Trigger:** 18×18px button, `--ink-4` text → `--accent` on hover/expanded.

**Panel:** `--bg-surface`, `--line-strong` border, `--r-md` radius, `--shadow-3`. Max `--sz-popover-max` wide, 60vh tall. `--font-body`, `--fs-micro`, `--ink-2` text.

**Dismiss:** Escape, click outside.

### ConfirmDialog

Modal dialog with backdrop blur.

**Backdrop:** `--overlay-bg`, `backdrop-filter: blur(--blur-overlay)`, `--z-dialog`.

**Dialog:** `--bg-surface`, `--line-1` border, `--r-xl` radius, `--shadow-3`. Min `--sz-dialog-min`, max `--sz-dialog-max` wide, `--sp-6` padding. Title: `--fs-h3`, `--fw-semibold`. Body: `--fs-body`, `--ink-2`.

**Actions:** flex-end, `--sp-3` gap. Cancel button is default variant; confirm is `primary` or `danger` based on tone prop.

**Behavior:** focus trap, Escape dismisses, focus returns to trigger on unmount.

### Spinner

Rotating border circle. `--sp-6` width/height, `--border-thick` border in `--line-strong` with `--accent` top edge. `--t-spin` linear infinite rotation.

ARIA: `role="status"`, `aria-label="Loading"`.

### EmptyState

Centered placeholder for empty data views.

**Structure:** icon (`--fs-h1`, `--ink-4`), title (`--fs-small`, `--fw-medium`, `--ink-2`), optional body (`--fs-micro`, `--ink-3`, max `--sz-content-narrow`), optional children slot for action buttons.

### AppLink

Monospace link to app detail pages. `--font-mono`, `--fs-small`, `--ink-1`. Hover: `--accent` with underline.

### Icons

Inline SVGs at `--sz-icon-sm` (14px). All use `currentColor` and `aria-hidden="true"`.

**Stroke icons** (navigation, actions): 24×24 viewBox, stroke-width 2, round caps/joins.

**Fill icons** (sidebar): 24×24 viewBox, path-based.

**Chevron:** separate sizing via `size` prop, rotates based on `open` prop.

---

## Status System

### Two Visual Channels

The UI uses two parallel status systems that intentionally diverge for some states. They serve different questions:

- **StatusVariant** (Badge) → "What should the user do about this?" Warning = needs attention. Neutral = no action needed.
- **StatusKind** (Shape/Chip) → "What is the current health state?" Ok = healthy. Warn = transitional. Mute = inactive.

| Status | Badge (StatusVariant) | Shape (StatusKind) | Why they differ |
|---|---|---|---|
| running | success | ok | — |
| starting | neutral | ok | No action needed, but healthy progress |
| stopped | warning | mute | Needs attention (badge) but not broken (shape) |
| blocked | warning | warn | — |
| stopping / shutting_down | neutral | warn | No action needed, but transitional |
| failed / crashed | danger | err | — |
| exhausted_dead | danger | err | — |
| exhausted_cooling | warning | warn | — |
| disabled / not_started | neutral | mute | — |

Use the mapping functions in `frontend/src/utils/status.ts` — do not map status strings to colors directly. New status values must be added to both maps.

### StatusVariant

`"success" | "danger" | "warning" | "neutral"`

Used by Badge (via `statusToVariant()`), log levels (via `levelToVariant()`), and readiness display (via `readinessVariant()`).

### StatusKind

`"ok" | "warn" | "err" | "cancel" | "mute"`

Used by StatusShape SVG indicators (via `statusToKind()`), Chip kind variant, execution status (via `executionStatusKind()`), and log levels (via `levelToKind()`).

`cancel` exists as a Kind but not a Variant — it maps to the diamond shape for cancelled executions.

### Execution Status Mapping

| Execution status | StatusKind |
|---|---|
| success | ok |
| timed_out | warn |
| cancelled | cancel |
| error | err |
| skipped | mute |

### Log Level Mapping

| Level | Badge (StatusVariant) | Shape (StatusKind) |
|---|---|---|
| DEBUG | neutral | mute |
| INFO | success | mute |
| WARNING | warning | warn |
| ERROR / CRITICAL | danger | err |

---

## Patterns

### Focus

**Global baseline** (`:where(:focus-visible)`): `outline: 2px solid var(--accent)`, `outline-offset: var(--sp-0)`. The `:where()` wrapper gives zero specificity so component-level rules win cleanly.

**Inputs** suppress the outline and use border + box-shadow ring instead: `border-color: var(--accent)`, `box-shadow: 0 0 0 2px var(--accent-soft)`.

**Popover inputs** use a simpler focus: `border-color: var(--accent)` only (no box-shadow).

### Inputs

No shared `<Input>` component exists. Inputs are styled via two patterns:

**`.ht-search`** (global class, primary pattern): `--font-body`, `--fs-mono-sm`, `--sp-1h`/`--sp-2` padding, `1px solid --line-strong`, `--r-md`, `--input-bg`. Placeholder: `--ink-4`. Mobile: stretches full width.

**Popover inputs** (scoped CSS): similar but smaller padding (`--sp-1`/`--sp-2`), `--line-1` border (softer), `--r-sm` radius.

### Tables

All data tables follow the same structural pattern:

```
TableCard (scroll container + footer slot)
  table.ht-table[.ht-table--fixed|.ht-table--compact]
    colgroup (explicit column widths, set per page)
    thead > SortHeader per column
    tbody > rows
  TableFooter (count + mobile filter consolidation)
```

**Table headers:** `--font-mono`, `--fw-medium`, `--fs-micro`, uppercase, `--tr-label` tracking, `--ink-3`.

**Table cells:** `--fs-small`, `--sp-2`/`--sp-3` padding, `--line-1` bottom border. Row hover: `--bg-sunken`.

**Scroll container:** `--line-strong` border, `--r-md` radius, max-height defaults to `calc(100vh - 310px)`, overridable via `scrollHeight` prop.

**Sort headers:** click cycles asc/desc. Active: `--ink-1`, `--fw-semibold`. Arrow indicators: Unicode ↑/↓.

**Column filters:** desktop: popover per column header. Mobile: consolidated into footer panel.

**Compact variant:** tighter padding (`--sp-1`/`--sp-2`), `table-layout: fixed`, text-overflow ellipsis. Has predefined column-width classes for status/time/duration columns.

### Command Palette

Cmd-K / Ctrl-K global search. `--r-xl` radius, `--shadow-3`, positioned at 15vh from top.

**Structure:** search input → grouped results (sections with uppercase mono headers) → keyboard hint footer.

**Result rows:** `--fs-body`, hover: `--bg-active`. Active: `--fw-semibold`. Kind chips per result.

**Responsive (≤768px):** footer hidden.

### Dark Mode

Token-driven — almost no component-level overrides. The only structural dark-mode override is the Shiki code syntax highlighter, which needs `!important` to override inline styles.

Key dark-mode differences in token values:
- Accent lightness inverts (0.5 → 0.72) for contrast on dark backgrounds
- Shadow opacity increases significantly for definition
- Light-mode surfaces use oklch with accent-hue tinting; dark-mode uses raw hex

---

## Do's and Don'ts

These are implementation-level rules for agents working on the frontend. For higher-level design constraints, see Concrete Constraints above.

### Do

- Use shared components (Button, Badge, Card, Chip) instead of raw CSS classes
- Use CSS Modules for all component-specific styles
- Reference tokens for all visual values — no raw hex, pixel, or rem values in component CSS
- Follow the table pattern: TableCard + SortHeader + TableFooter
- Use StatusShape for inline status indicators, Badge for labeled status
- Use the status mapping functions from `status.ts` — never map status strings to colors directly
- Follow the standard table page or detail page pattern when creating new pages
- Let tokens handle dark mode — avoid component-level `[data-theme="dark"]` overrides
- Enlarge touch targets to `--sz-touch` at the sidebar breakpoint (≤900px)
- Use `--font-mono` for data that benefits from fixed-width alignment (IDs, timestamps, paths)

### Don't

- Show every value with equal visual emphasis — use ink hierarchy (`--ink-1` through `--ink-4`)
- Add charts when a table, count, or linked evidence trail answers the question better
- Make successful states visually louder than failures
- Use status colors as decoration without text or context
- Create page-specific table or filter behavior when the shared pattern exists
- Hide diagnostic details behind tabs or collapsed panels without strong reason
- Treat config and logs as raw dumps with no hierarchy or affordances
- Add new `.ht-*` global classes without updating the CSS allowlist
- Create new status colors or invent a third status mapping system
- Use inline styles for colors, spacing, or typography
- Style inputs inconsistently — follow `.ht-search` or the popover input pattern
- Add new page layouts that deviate from the standard table page or detail page pattern

---

## Open Questions

- Should the serif display treatment stay as-is, become more integrated, or be reduced?
- Should the accent remain blue-violet in tokens while operational status remains green, or should the product identity move closer to Graphite/Emerald?
- How much explanatory prose should be added to pages before it starts slowing down expert users?
- Which page is the true landing page: Apps, Diagnostics, or an eventual dashboard/overview?
- Should mobile use the same information architecture as desktop, or a more opinionated quick-check view?
