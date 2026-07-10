---
schema_version: 1
updated_at: 2026-07-08
---

# Hassette Frontend Design Context

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

## Design Tokens

These document the current implemented token direction. Do not treat this section as a mandate that tokens are final; it records the baseline before visual QA.

### Color

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg-page` | `oklch(0.95 0.006 var(--accent-hue))` | `#0c0e11` | Outer page background |
| `--bg-surface` | `oklch(0.995 0.002 var(--accent-hue))` | `#1a1c21` | Main panels and cards |
| `--bg-sunken` | `oklch(0.955 0.006 var(--accent-hue))` | `#141619` | Table headers, recessed inputs, code regions |
| `--bg-active` | `oklch(0.92 0.01 var(--accent-hue))` | `#22242a` | Active/hover surfaces |
| `--bg-chrome` | `oklch(0.96 0.005 var(--accent-hue))` | `#131517` | Status bar and app chrome |
| `--ink-1` | `#16181c` | `#edeff3` | Primary text |
| `--ink-2` | `#4a4d54` | `#b5b9c0` | Secondary text |
| `--ink-3` | `#787c84` | `#888d97` | Muted metadata |
| `--ink-4` | `#b0b3b8` | `#5a5e66` | Disabled/subtle metadata |
| `--accent` | `oklch(0.5 0.09 255)` | `oklch(0.72 0.09 255)` | Navigation, active state, primary emphasis |
| `--ok` | `#1f7a4d` | `#5fb988` | Healthy/running/success |
| `--warn` | `#9a6a12` | `#d9b36e` | Warning/degraded/blocked |
| `--err` | `#b53024` | `#e08278` | Failure/error |
| `--mute` | `#9097a0` | `#6a707a` | Inactive/unknown/disabled |

**Rationale**: The palette supports a restrained operational console. Surfaces stay close together, status colors carry meaning, and accent color is used primarily for orientation rather than decoration.

### Typography

- **Display**: `Newsreader`, `Source Serif Pro`, Georgia, serif. Used for page titles and product wordmark. Adds a human/editorial note to an otherwise technical interface.
- **Body**: `Geist`, system UI fallback. Used for navigation, labels, explanatory text, and controls.
- **Mono**: `Geist Mono`, UI monospace fallback. Used for code, IDs, timestamps, paths, timings, and dense table data.
- **Current scale**: display 38px, h1 28px, h2 20px, h3 16px, body 14px, small 12.5px, micro 12px, xs 11px.
- **Line heights**: `--lh-display` 1.05, `--lh-h1` 1.15, `--lh-h2` 1.25, `--lh-h3` 1.35, `--lh-body` 1.55, `--lh-relaxed` 1.6, `--lh-small` 1.5, `--lh-micro` 1.4, `--lh-xs` 1.3.
- **Tracking**: `--tr-label-tight` 0.03em, `--tr-label-mid` 0.04em, `--tr-label` 0.05em, `--tr-label-wide` 0.07em.
- **Current weights**: normal 400, medium 500, semibold 600, bold 700.

**Guidance**: The serif display face should remain a deliberate accent. If a page title feels disconnected from the rest of the UI, integrate surrounding hierarchy rather than removing the character by default.

### Spacing

- **Base**: 4px grid with half-steps where useful.
- **Scale**: `--sp-px` 1px, `--sp-0` 2px, `--sp-1` 4px, `--sp-2` 8px, `--sp-3` 12px, `--sp-4` 16px, `--sp-5` 20px, `--sp-6` 24px, `--sp-7` 32px, `--sp-8` 40px, `--sp-9` 56px, `--sp-10` 72px.
- **Current page rhythm**: `.ht-page` uses larger desktop padding and gaps, then tightens below mobile breakpoints.

**Guidance**: Use spacing to clarify hierarchy, not to make the product airy. This UI should remain compact.

### Depth

- **Strategy**: subtle shadows plus visible borders.
- **Current levels**: `--shadow-1`, `--shadow-2`, `--shadow-3`.
- **Current card baseline**: `var(--bg-surface)`, `1px solid var(--line-strong)`, `var(--r-md)`, `var(--shadow-2)`.

**Guidance**: Depth should separate working surfaces from the page, especially tables and diagnostic cards. Avoid dramatic elevation.

### Border Radius

- **Scale**: `--r-sm` 6px, `--r-md` 8px, `--r-lg` 12px, `--r-xl` 20px, `--r-pill` 999px.
- **Character**: moderately technical, not sharp-industrial and not bubbly.

**Guidance**: Large rounded panels should be used carefully. Keep dense diagnostic elements tighter than marketing-style cards.

### Component Sizing

- `--sz-sidebar` 240px — sidebar width, used in layout grid and mobile drawer.
- `--sz-search-min` 160px — minimum width for search inputs.
- `--sz-touch` 44px, `--sz-icon-sm` 14px.

### Component Padding & Gap

Component-local custom properties for em-based padding and gap values. These scale with font-size and are prefixed per component to avoid collisions (CSS Modules scopes class selectors, not custom property names).

- **Button** (`button.module.css`): `--btn-pad-y` 0.4em (sm 0.25em, xs 0.15em), `--btn-pad-x` 0.85em (sm 0.6em, xs 0.45em), `--btn-gap` 0.35em.
- **Badge** (`badge.module.css`): `--badge-pad-y` 0.15em (xs 0.05em, sm 0.1em, md 0.2em), `--badge-pad-x` 0.55em (xs 0.4em, sm 0.45em, md 0.65em), `--badge-gap` 0.25em.
- **Inline Code** (`typography.css`): `--code-pad-y` 0.1em, `--code-pad-x` 0.35em.

**Guidance**: These are em-based so they scale with the component's font-size across size variants. They are not global tokens — they live on the component's base selector and size variants override them via cascade.

### Effects

- `--blur-overlay` 2px — backdrop blur for overlays (command palette, confirm dialog).
- `--border-thick` 3px — heavy borders (spinner track, error accent borders).

### Motion

- **Micro**: `--t-fast` 120ms.
- **Transition**: `--t-med` 200ms.
- **Spin**: `--t-spin` 0.8s — spinner animation duration.
- **Easing**: `cubic-bezier(0.4, 0, 0.2, 1)`.

**Guidance**: Motion should confirm interactions and orient users during overlays/drawers. Avoid decorative animation except for meaningful live-status indicators like the connection pulse.

## Anti-Patterns

- Showing every value with equal emphasis.
- Adding charts when a table, count, or linked evidence trail answers the question better.
- Making successful states visually louder than failures.
- Using red/green only as decoration without text or context.
- Creating page-specific table/filter behavior when a shared pattern already exists.
- Hiding important diagnostic details behind tabs or collapsed panels without a strong reason.
- Treating configuration and logs as raw dumps with no hierarchy or affordances.

## Current Open Questions

- Should the serif display treatment stay as-is, become more integrated, or be reduced?
- Should the accent remain blue-violet in tokens while operational status remains green, or should the product identity move closer to Graphite/Emerald?
- How much explanatory prose should be added to pages before it starts slowing down expert users?
- Which page is the true landing page: Apps, Diagnostics, or an eventual dashboard/overview?
- Should mobile use the same information architecture as desktop, or a more opinionated quick-check view?
