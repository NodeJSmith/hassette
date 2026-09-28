---
schema_version: 1
updated_at: 2026-09-28
---

# Hassette Design Context

This document defines the durable visual and interaction direction for Hassette's web UI, and the concrete rules that apply that direction to specific UI patterns (typography, spacing, tables, color, motion, and so on). It is the single design reference for the frontend — there is no separate implementation-rules file. It is not a pixel specification or an exhaustive catalog of every CSS value; where a rule cites a token or class, that's because the token is the stable thing to reference, not because every value is pinned here. The generated screenshots and the running frontend show the current baseline; this document explains what should remain recognizable as the interface improves, and gives concrete rules so agents don't have to invent conventions ad hoc.

Every rule below uses specific tokens, components, or values found in `frontend/src/global.css` and `frontend/src/components/` — check those files, not this document, when a rule and the running code disagree.

## Users & Purpose

Hassette's primary user is a developer or homelab operator checking Home Assistant automations. They may be debugging at a desktop or checking system health from a phone. They usually arrive with a concrete question:

- Is the system connected and are my apps running?
- Which app, handler, or scheduled job failed?
- Did an automation run, skip, time out, or stop firing?
- What error, log line, source location, or configuration explains the result?

The interface is an operational and diagnostic tool. It should make a quick health check easy without hiding the evidence needed for deeper investigation.

## Visual Baseline

The generated `docs/_static/web_ui_*.png` images are the source of truth for the established direction. `docs/screenshots.yml` defines the standard capture set. Representative anchors include:

- `docs/_static/web_ui_apps.png`
- `docs/_static/web_ui_app_detail_overview.png`
- `docs/_static/web_ui_app_detail_handlers.png`
- `docs/_static/web_ui_logs.png`
- `docs/_static/web_ui_config.png`

Preserve their core structure and character while improving details incrementally. Do not redesign the product around a new concept unless that change is explicitly proposed and approved.

The baseline includes:

- Persistent desktop navigation with app health visible in the sidebar.
- A compact status bar and time-window controls.
- Serif page titles as an editorial accent within a technical interface.
- Dense tables, app-detail tabs, and master-detail inspection views.
- Light and dark themes with expressive operational colors.
- Direct access to logs, code, configuration, and execution history.

## Brand Personality

Hassette should feel calm, precise, trustworthy, and crafted. It is technical without pretending to be a terminal, and operational without resembling an enterprise control room.

The desired movement is **dense operational utility with editorial restraint**.

- **Dense**, because diagnosis depends on seeing related evidence together.
- **Operational**, because current state and recent outcomes matter more than decoration.
- **Editorial**, because hierarchy and typography should guide interpretation rather than merely contain data.
- **Restrained**, because exceptions need visual room to stand out.

The interface can use color confidently. Restraint means that color carries meaning, not that the product should become monochrome.

## Domain Language

The visual system should reflect Hassette's actual domain:

- Apps are registered runtime units with lifecycle and instance health.
- Handlers react to events; jobs run on schedules or triggers.
- Executions succeed, fail, skip, cancel, time out, or encounter backpressure.
- Health combines current state with recent behavior.
- Time windows change the evidence being inspected.
- Logs, source, configuration, and tracebacks explain outcomes.
- Disabled autostart and removed apps remain useful configuration or historical evidence.
- Home Assistant is a connected external system, not the visual model for this UI.

Use this vocabulary in labels and explanations. Prefer `app`, `handler`, `job`, `execution`, `listener`, and `instance` over organizational or infrastructure metaphors.

## Signature Pattern

Hassette's signature interaction is the **evidence trail**:

1. A health summary identifies an exception.
2. The exception leads to the relevant app, handler, or job.
3. The detail view shows the latest outcome and execution history.
4. The user can reach the error, log line, source registration, or configuration that explains it.

This trail should be visible in page structure and links, not only available through search. Error summaries should lead somewhere useful. Detail views should keep context while revealing evidence progressively.

## Design Principles

### Lead With Health

Connection state and app health should be understandable at a glance. Desktop navigation keeps app health visible. Mobile layouts may summarize or relocate it, but must not hide critical failures.

### Make Exceptions Louder

Healthy states should be calm. Failures, degraded states, timeouts, and blocked apps should interrupt that calm with clear status color and plain-language context. Do not make every healthy item compete for attention.

### Keep Evidence Connected

Place the explanation near the status it explains or provide an obvious next step. Preserve context when moving from an app to a handler, execution, log entry, source location, or configuration value.

### Be Dense, Not Tiny

Keep useful information together, but do not achieve density through unreadably small type or compressed controls. Create hierarchy with grouping, alignment, type weight, spacing, and selective disclosure.

### Improve In Place

Prefer small, reviewable improvements to the established screens. Reuse existing navigation and interaction models unless changing them solves a demonstrated problem.

## Layout & Information Architecture

- Preserve the desktop sidebar, top status bar, primary pages, app-detail tabs, and master-detail handler view.
- Keep app detail as the center of diagnostic work. Overview, handlers, code, logs, and config are complementary evidence surfaces.
- Use tables for comparable records and scanning. Use cards or grouped sections when relationships and explanation matter more than column comparison.
- Avoid wrapping every section in a card. Borders, spacing, and surface changes should establish hierarchy before additional containers are introduced.
- Keep primary page content left-aligned. Reserve centered layouts for narrow empty or loading states.
- Maintain readable line lengths for prose and errors. Code, tables, and tracebacks may use the available width.

### Information Density

Hassette is a monitoring dashboard checked occasionally, not a trading terminal watched all day. Generous spacing is correct — it reduces cognitive load for infrequent use. But spacing should serve grouping, not fill the page.

**The test:** can you see the most important information on each page without scrolling? On the apps page: the stats strip plus at least the first 5-6 app rows. On the app-detail overview: handler health plus recent activity. If you have to scroll past whitespace to reach content, the spacing is wasteful.

- Page padding: `--sp-7` on desktop. Don't reduce it.
- Section gaps: `--sp-7` between semantic groups on a page — see Spacing under Spacing, Shape & Depth below.
- Card internal padding: `--sp-5`.
- Table row height comes from cell padding (`--sp-2` vertical) plus line height — don't add extra. Rows should be compact enough to show 10+ without scrolling.
- Empty space at the bottom of a page is acceptable. Don't pad the bottom to push content up or center it vertically.

## Responsive Behavior

Responsive design should adapt the task rather than shrink the desktop screen.

- At desktop widths, keep navigation and app health persistently visible.
- Below the sidebar breakpoint, use an accessible drawer with reliable focus management and dismissal.
- On mobile, prioritize connection state, current app health, recent failures, and the next useful action.
- Convert wide tables into priority-column or stacked-row presentations where horizontal scrolling would obscure meaning.
- In master-detail views, show the list and detail as separate steps on narrow screens, with a clear route back to the list.
- Do not remove critical actions or status information on mobile.
- Interactive targets should meet the `--sz-touch` minimum where touch input is expected.

### Breakpoints

Registered once in `frontend/src/global.css`'s `@theme inline` block and mirrored as `BREAKPOINT_*` constants in `frontend/src/hooks/use-media-query.ts` (`check-breakpoint-drift` catches drift between the two):

| Breakpoint | Value | Role |
|---|---|---|
| `tablet` | 1024px | Minor layout adjustments |
| `sidebar` | 900px | Sidebar collapses to a drawer; tables switch to their compact column set |
| `mobile` | 768px | Reduced padding, simplified tables, stacked layouts |
| `small-mobile` | 480px | Minimal padding, essential content only |

### Table Column Hiding

Two independent mechanisms handle tables at narrow widths — don't conflate them:

1. **React-level column hiding.** A page tracks compactness via a media-query hook and conditionally hides the lower-priority `<th>`/`<td>` elements below the `sidebar` breakpoint. Reference implementation: `apps.tsx`.
2. **CSS-level `table-fixed`/`table-auto` swap.** A table stays `table-fixed` with percentage-width columns (so text doesn't crop mid-word) and only switches to `table-auto` at the mobile breakpoint when every column still visible at that width is inherently bounded — short values, or values that wrap via `word-break`. Reference implementation: `execution-table.tsx`.

**Rule:** a column that's still visible at a breakpoint must either be a bounded/short value, wrap safely, or be handled by mechanism 1 (hidden outright). Never let `table-auto` apply to a table where an unbounded mono column (entity IDs, app keys, log messages) is still visible — it will push the table past the viewport and crop content mid-word.

If a table header truncates or wraps, the table has too many columns visible for that viewport — hide a lower-priority column at that breakpoint instead of shrinking further.

### Mobile Detail Pages (<768px)

Detail pages are the hardest to get right on mobile because every layer of context (header, tabs, stats strip, metadata) competes for a viewport that's only ~700px tall.

1. **Collapse metadata aggressively.** Detail metadata (source references, configuration, full stats breakdowns) hides behind a toggle by default. Only identity plus 2-3 key stats stay visible. Primary content (tables, activity feeds) must be reachable without scrolling past metadata.
2. **Stats strips show 3-4 columns max on mobile.** Strips that wrap to multiple rows create visual noise. Pick the most important stats for the mobile view; the rest lives in the collapsed detail section or a tooltip.
3. **Code blocks scroll horizontally.** Code that truncates with no way to see the rest is broken — all code blocks get `overflow-x: auto` on mobile.
4. **Prefer a bottom sheet over inline expansion on mobile.** On a 375px viewport, inline row expansion consumes the entire visible area and pushes all other rows out of view. A bottom sheet (half-viewport height, swipe to dismiss) keeps the table visible above. On desktop, inline expansion is fine when kept tight (see Inline Row Expansion below).
5. **Empty states in secondary contexts are one line on mobile.** "No logs" in `--ink-3`. The full `EmptyState` component (icon + title + body text) is for primary content areas, not expansion panels or sub-sections.

### Mobile Navigation Context

On mobile, the header bar (hamburger, time window, connection status, theme toggle) stays fixed at the top of the viewport via sticky positioning. If it appears mid-page in the document flow, the sticky positioning has broken — that's a layout bug, not a design choice.

## Typography

The established font roles are intentional:

| Role | Family | Use |
|---|---|---|
| Display | Newsreader | Product wordmark and primary page titles |
| Interface | Geist | Navigation, controls, labels, explanations, and body text |
| Data | Geist Mono | Code, paths, IDs, timestamps, durations, and compact numeric data |

Use monospace because the content benefits from fixed-width scanning, not as a generic signal that the product is technical.

### Hierarchy

| Element | Font | Size token |
|---|---|---|
| Primary page title (apps, handlers, logs, config) | Newsreader (`--font-heading`) | `--fs-display` |
| Utility page title (e.g. diagnostics) | Geist | `--fs-h1` |
| Section heading | Geist, `--fw-semibold` | `--fs-h3` |
| Subsection label / table header | Geist Mono, `--fw-medium`, uppercase, `--tr-label` tracking | `--fs-xs` / `--fs-micro` |
| Body text | Geist | `--fs-body` |
| Secondary text | Geist | `--fs-small` |
| Stat value | Geist, `--fw-medium` | `--fs-stat` |

Section headings ("handler health", "recent activity", "logs") use Geist semibold, not Newsreader — this keeps the serif accent reserved for page identity and creates visible hierarchy between the page title (serif, large) and section labels (sans, smaller, weighted).

- Page titles should be clearly larger than section titles.
- App and handler names should remain prominent even when they contain underscores or long identifiers.
- Reserve the smallest size steps (`--fs-micro`/`--fs-xs`) for short, nonessential labels, badges, and metadata. Never put an error explanation, primary action, or required navigation at that size.
- Use uppercase and letter spacing sparingly for short table headers and category labels.
- Prefer weight and spacing over adding many near-identical font sizes.

Adjust the type scale incrementally and validate representative dense screens before changing it globally. Current size values live in `frontend/src/global.css`'s `@theme` block — check there, not here.

## Color

Hassette uses a paper-and-graphite neutral foundation with expressive semantic color.

| Role | Token family | Meaning |
|---|---|---|
| Page and chrome | `--background`, `--sidebar`, `--muted` | Quiet structure and orientation |
| Primary | `--primary` | Navigation, focus, links, and selected state |
| Success | `--status-success` | Running, healthy, and successful |
| Warning | `--status-warning` | Degraded, blocked, or attention needed |
| Destructive | `--destructive` | Failed, crashed, and error evidence |
| Cancelled | `--status-cancel` | Cancelled outcomes |
| Inactive | `--status-muted` | Stopped, disabled, unknown, or idle |
| Job | `--handler-job` | Scheduled-job category coding |
| Listener | `--handler-listener` | Event-listener category coding |

Concrete palette values may evolve, but these semantic roles should remain stable.

### Color Rules

- Use status color consistently across shapes, badges, summaries, rows, and details.
- Pair color with text or shape; color alone must not carry status.
- Use vivid status variants for charts or small marks that need stronger contrast, not large surfaces.
- Use tinted backgrounds for selected, warning, and error regions when they improve grouping.
- Keep the primary brand/action color distinct from status colors.
- Keep brand/action emphasis and subtle highlighted backgrounds as separate visual roles (`--accent`/`--primary` vs. `--highlight-bg` — see `.claude/rules/frontend-css.md`).
- Preserve separate job and listener colors when category distinction helps scanning.
- Avoid decorative gradients, neon glow, and low-contrast gray-on-color combinations.

### Surfaces

- Page background: `--bg-page` (warm off-white in light, near-black in dark).
- Main content: `--bg-surface` (white in light, dark gray in dark).
- Recessed areas: `--bg-sunken` (table headers, code blocks, input backgrounds).
- Active/pressed: `--bg-active`. Hover: `--bg-sunken`.

**The surface stack goes in one direction:** page → surface → sunken. Never nest `--bg-page` inside `--bg-surface`, or `--bg-surface` inside `--bg-sunken`. Depth should always increase inward.

### Accent Color

The accent (`--accent`, oklch hue 255, blue-purple — exposed to shadcn components as `--primary`) is used for links, active tab indicators, focus rings, primary buttons, and selected/active sidebar items.

**Accent is for interactive affordances only.** Don't use accent for decoration, emphasis, or highlighting data. If something isn't clickable or focused, it doesn't get accent color.

### Status Colors in Context

- In tables and lists: status color on the status text only, not the row background.
- In a stats strip: semantic color for non-zero values, `--ink-4`/`--foreground-faint` for zero (see Stats Strip below).
- In handler health tiles: the status dot is the indicator; the tile border stays the default `--border`.
- For the Stop action: destructive but not urgent, so it doesn't dominate the page — see Buttons below for the variant rules.

### Color Use

Color should be semantic — every non-neutral color communicates something (status, interactivity, category). Avoid purely decorative color, but don't default to near-monochrome either. An operational dashboard can carry a richer palette when each color earns its place through meaning.

The current baseline is neutrals (ink scale plus surfaces) for most content, accent color for interactive elements, and status colors where status is being communicated. This baseline is a floor, not a ceiling — richer surface tints, category-coded sections, or a warmer accent palette are all valid directions as long as color remains tied to information, not decoration.

**Test:** remove the color in your head. If the reader loses information (status, what's clickable, which category), the color is meaningful; if nothing is lost, it's decoration.

### Ink Token Contrast

The four `--ink-*` tokens form a contrast tier from most to least legible (`--ink-1` highest, `--ink-4` lowest against `--bg-surface`); check `frontend/src/global.css` for current values in both themes. Usage follows the tier, not the specific ratio:

- **`--ink-1`, `--ink-2`**: any text, any size. Primary and secondary content.
- **`--ink-3`**: safe at `--fs-body` and above. At `--fs-micro` and below, use only for non-essential text (timestamps, metadata) where reduced contrast is acceptable because the information is supplementary. Never for actionable text at small sizes.
- **`--ink-4`**: decorative only — placeholder text, disabled states, ornamental separators, muted zero-value stats. Never for text the user needs to read.

The same tier rules apply in dark mode.

## Spacing, Shape & Depth

### Spacing

Hassette uses a two-tier vertical rhythm: **group gaps** (between semantic groups) and **internal gaps** (between elements within a group).

- Use the `--sp-*` scale in `frontend/src/global.css`; reach for a half-step value only for compact or optical adjustments.
- Keep related label/value pairs tight (`--sp-2` to `--sp-3`) and separate major sections generously (`--sp-7`, between semantic groups on a page — never between siblings within a group).
- Prefer `gap` for component layout instead of ad hoc sibling margins.
- Do not reduce padding solely to fit more information if readability suffers.

**Semantic grouping:** elements that describe or identify the same entity belong in a tight group. Examples of groups (tight internal spacing): breadcrumb + title + subtitle + tab bar (page identity); a section heading + its content (e.g. "handler health" + the handler cards); a stats strip + the list or table it summarizes; a search input + the table it filters; a label + its value.

**The test:** if two adjacent elements are "about" the same thing, they're in the same group and get tight spacing. If they're about different things, they're separate groups and get `--sp-7` between them.

**Implementation:** group siblings into semantic containers and apply `--sp-7` as the gap between containers, not as a flat gap on the page-level flex/grid — a flat gap can't distinguish within-group from between-group spacing.

### Shape

- Small controls and dense rows use compact radii; standard panels, popovers, and cards may use medium radii; large rounded containers should be rare — the product should not feel soft or toy-like.
- Pills are appropriate for statuses and compact categorical badges, not general containers.

**Border radius scale** (`frontend/src/global.css`), desktop and mobile (below `--breakpoint-mobile`, 768px):

| Token | Desktop | Mobile | Use for |
|---|---|---|---|
| `--r-sm` | 6px | 6px | Badges, chips, inline code, small elements |
| `--r-md` | 8px | 8px | Buttons, inputs, default |
| `--r-lg` | 12px | 10px | Cards, main content panel top corners |
| `--r-xl` | 20px | 16px | Large modals, sheets |
| `--r-pill` | 999px | 999px | Pills, toggle tracks |

Tighter radii read as more intentional and less decorative — corners are softened without becoming a visual feature. Every rounded element uses a token, never a hardcoded value; if an element needs a radius between two tokens, use the smaller one.

### Depth

Use surface tint, borders, and restrained shadows in that order. Shadows should separate major layers or interactive surfaces, not make every section float.

**Elevation model** — every element belongs to exactly one layer:

| Layer | Background | Shadow | What lives here |
|---|---|---|---|
| Page | `--bg-page` | none | Page background, sidebar background |
| Surface | `--bg-surface` | `--shadow-2` | Main content area (the panel with rounded top corners) |
| Elevated | `--bg-surface` | `--shadow-2` | Stats strip, handler health tiles, config groups, dialogs |
| Sunken | `--bg-sunken` | none | Table headers, hover states, code blocks, input backgrounds |

**Fewer elevated elements read as a cleaner page.** With tables unwrapped from cards (see Cards and Containers below), a typical page has 1-2 elevated elements (stats strip, maybe handler tiles), not 3-4.

**Shadow levels:**

| Level | Token | Use for |
|---|---|---|
| shadow-1 | `--shadow-1` | Hover lift effects, mobile cards |
| shadow-2 | `--shadow-2` | Cards, the main content panel |
| shadow-3 | `--shadow-3` | Overlays: dropdowns, drawers, dialogs, command palette |

**Never stack shadows.** A card inside the main content panel doesn't get shadow-2 on top of shadow-2 — the card's shadow replaces the surface context; they sit at the same visual level. An element that needs to float above a card (tooltip, dropdown) uses shadow-3.

**Hover effects:** interactive cards (handler health tiles) get a subtle lift on hover — transition to `--shadow-3` at `--t-fast`. Table rows use a background shift (`--bg-sunken`) instead of shadow; rows don't float.

The current depth system: subtle borders (`--line-1`) for rows and internal grouping, stronger borders (`--line-strong`) for table shells and important panels, small shadows for raised cards and controls, and larger shadows only for overlays, drawers, and transient layers.

## Borders and Lines

Components reference borders through the semantic aliases in `frontend/src/global.css`, not the raw `--line-*` tokens:

| Alias | Maps to | Use for |
|---|---|---|
| `--border` (Tailwind `border-border`) | `--line-1` | The default: `Card` and card-like tiles (e.g. handler health cards), the tab bar container, table rows, dividers inside a container |
| `--border-subtle` | `--line-2` | Internal separators that should nearly disappear, e.g. between stats-strip cells when the strip wraps |
| `--border-strong` | `--line-strong` | Data containers that must stand out from the page: `TableCard` and the stats strip |

Match the canonical component rather than picking a tier ad hoc — a new card uses `Card`'s border, a new data table uses `TableCard`.

**Never use a border where spacing alone would work.** If two elements are already visually distinct because of their own structure (a heading followed by a table), a divider between them adds noise. Borders are for separating things that would otherwise bleed together.

## Motion & Interaction

- Use motion to explain state changes, opening, closing, and selection.
- Keep routine transitions between `--t-fast` and `--t-med` with the standard easing curve (`--ease`) — no bouncy easing.
- Animate opacity and transforms where practical; avoid decorative movement.
- Respect `prefers-reduced-motion` — never add animation that bypasses it.
- Every interactive control needs visible hover, focus, active, disabled, and loading behavior where applicable.
- Keyboard navigation and focus order must remain usable in dense tables, tabs, drawers, menus, and master-detail views.
- Prefer progressive disclosure over showing every technical detail in the first row or card.

**Animation confirms an interaction happened — it's feedback, not decoration.** If the user didn't trigger it, it doesn't animate. Data updates are instant; user-initiated state changes get a brief transition.

| Element | Property | Duration | Easing |
|---|---|---|---|
| Hover states (buttons, rows, links) | background-color, color | `--t-fast` | `--ease` |
| Card hover lift | box-shadow | `--t-fast` | `--ease` |
| Tab active state | background, color | `--t-fast` | `--ease` |
| Sidebar drawer open/close | transform | `--t-med` | `--ease` |
| Drawer backdrop | opacity | `--t-med` | `--ease` |
| Focus ring | outline | `--t-fast` | `--ease` |
| Tooltip appear | opacity | `--t-fast` | `--ease` |

What does not animate: page transitions (no route animation), table row additions/removals (appear/disappear instantly), stats strip value changes (instant update), section expand/collapse (instant, unless it's a drawer/panel), color theme switch (instant — animating light/dark creates a flash).

## Component Language

- Standard controls, overlays, badges, tables, and cards should share consistent structure and states.
- Visual differences should represent semantic differences such as status, category, selection, or emphasis.
- Reuse established components before introducing a one-off visual treatment.
- Keep interaction behavior consistent across pages: the same control should look and act like the same control.
- Responsive changes should follow shared layout thresholds rather than isolated component guesses.

### Tables

**Column priority.** Tables must remain readable without horizontal scrolling — when the viewport narrows, hide lower-priority columns rather than shrinking every column (see Table Column Hiding under Responsive Behavior). If a table header truncates or wraps, the table has too many columns for the viewport at that width.

**Text weight in tables** — apply ink tokens to create a scannable hierarchy:

| Column type | Color | Font |
|---|---|---|
| Primary identifier (app name, handler name) | `--ink-1` | Geist Mono |
| Numeric value (run count, duration, error rate) | `--ink-1` | Geist Mono |
| Timestamp | `--ink-3` | Geist Mono |
| Status/category | semantic color | Geist |
| Secondary metadata (class name, trigger type) | `--ink-3` | Geist |

The reader's eye should land on primary identifiers first, then values, then timestamps.

**Table footers.** Footer text (e.g. row counts) uses muted ink (`--ink-3`) — understated by color, not size. See `components/shared/table-footer.tsx`.

**Right-align numeric columns.** Counts, durations, percentages, and rates right-align so digits and decimal points line up. Text (names, identifiers, messages) and status badges stay left-aligned; timestamps can go either way but should be consistent per table. The column header aligns with its content. All numeric values use Geist Mono so digits share a fixed width — a proportional font makes "111" narrower than "999" and breaks the vertical alignment.

### Stats Strip

**Zero-value muting.** When a stat value is zero (and has no explicit status tone), mute it — both the label and the value drop to `--ink-4`/`--foreground-faint`. This makes non-zero values pop without changing the layout. A stat with an explicit tone (e.g. an error count that's meaningfully zero-and-good) keeps its assigned color.

**Label casing.** Stats strip labels are uppercase Geist Mono with wide tracking — keep this.

**Column limits.** A stats strip should have 5-7 columns max on desktop, 3-4 on mobile. Beyond that, values compete for attention and the strip wraps awkwardly. When a strip has too many columns: combine redundant stats (e.g. count + successful count when success rate is also shown), move less-critical breakdowns into a collapsible detail section, or show the most useful single metric in the strip with the full breakdown available on expand or tooltip.

### Search Inputs

Search sits between the section heading and the table, part of the section flow — right-aligned in the same row as the section heading, or on its own line directly above the table. Search filters content below it; it belongs to the section, not to a container around the table.

### Cards and Containers

All data tables use `TableCard` (`frontend/src/components/shared/table-card.tsx`) — a scroll container that provides a structural border (`--border-strong`), radius, scroll height, and an optional footer slot. It has no shadow and no padding beyond what its children bring; it is not the decorative `Card` component.

Do not wrap tables in the decorative `Card` component (`frontend/src/components/ui/card.tsx`). `Card` adds shadow and padding for visual grouping — appropriate for stats strips, handler health tiles, config key-value groups, and empty states, not for tables.

- **`TableCard`** — all data tables. Scroll containment plus footer slot.
- **`Card`** — stats strips, handler health tiles, config key-value groups, empty states. Visual grouping with shadow.
- **Neither** — inline content (section heading + text, diagnostics lists). No container needed.

**Nesting:** avoid card-inside-card. If a section is already inside a card, separate sub-elements with borders (`--line-1`), not nested cards.

### Repetitive Lists

**Mute uniform status.** When a list of items all share the same status (all green, all running, all healthy), the status indicators become noise instead of signal. Mute the uniform state — `--ink-4` for status dots, `--ink-3` for status text — and reserve full-color status indicators for items that differ from the majority. The reader should spot exceptions, not count confirmations.

**Multi-column grids for simple items.** When list items are short (name + status, or name + value), a single-column layout wastes horizontal space. Use a two-column CSS grid above the mobile breakpoint for items that don't need the full page width — if the longest item fills less than half the content width, it should share a row.

**Compact absence.** When a section exists to surface problems and there are none, don't celebrate the absence. One line of muted text ("no issues") is enough — no card wrapper, no centered icon, no explanatory paragraph. The full `EmptyState` treatment (icon + title + body text) is for primary content areas where the user expected to find data, not for status sections reporting "all clear."

### Detail View Hierarchy

**Minimize parent context when drilling down.** When the user navigates deeper (list → detail → sub-detail), each level should reduce the parent's visual footprint — the user navigated here intentionally, and the breadcrumb handles orientation. When viewing a sub-detail, the parent-level stats strip should collapse to a compact single line or hide entirely; the current level's stats are what matters.

**Collapsible metadata.** Detail pages often show reference information (source code, configuration, file paths, registration details) alongside primary content (execution history, log output, activity lists). Identify what the user came to the page to see (usually a table or activity feed) and keep it above the fold. Reference metadata that supports but isn't the reason for the visit collapses by default, with a toggle to expand. What stays visible: identity (name, type badge, key description) and 2-3 key stats. What collapses: source code snippets, file paths, full stats breakdowns, secondary links.

**Inline row expansion** (clicking an invocation row): keep it tight — the expanded area should not be taller than 3-4 table rows; if detail needs more space, use a drawer or panel. Empty states in expanded rows are one line ("No logs for this execution" in `--ink-3`, no icon, no card). The selected-row highlight (tinted background) is the visual anchor showing which row is expanded, and only one row expands at a time.

**Drawer vs. inline expansion.** If the expanded content is just metadata (IDs, timestamps, a result status), inline expansion is fine. If it includes scrollable content (log output, stack traces) or the user might want to compare it across executions, use a side drawer or bottom panel instead — inline expansion shifts the table rows, making comparison across entries difficult.

### Buttons

- Page-level actions (Reload, Stop) sit right-aligned in the title row.
- Button variants carry semantic meaning, not just visual weight: `success` for Start, `outline` for Reload, `danger` for Stop. `danger` is outlined (destructive text/border, transparent background) rather than filled — destructive but not urgent, so it doesn't dominate the page. The `*-ghost` variants (`success-ghost`, `warning-ghost`, `info-ghost`) are for icon-only actions: transparent at rest, tinted hover. Canonical source: `frontend/src/components/ui/button.tsx`.

### Tabs

- No underline indicator — the active tab is distinguished by background tint and text color, not a border. Don't add one back.
- The tab bar sits inside a bordered, rounded container, distinct from the page background.
- Badge counts in tab labels (e.g. "handlers 2") render as plain muted text next to the label, not a separate badge component.

### Code Viewer

Canonical implementation: `frontend/src/components/app-detail/code-tab.tsx` (Shiki-powered). Line numbers are muted and right-aligned; the header bar puts the filename on the left and metadata on the right. Match its existing look rather than re-deriving one.

## Data Formatting

All timestamps, durations, rates, counts, and IDs go through the formatters in `frontend/src/utils/format.ts`; never format one of these inline. That file is the source of truth for exact output strings — the rules below are the decisions the formatters encode, not a restatement of their output.

- Use `formatDurationOrDash` (not `formatOptionalDuration`) when zero means "no data" — an average with no samples. Use `formatOptionalDuration` when zero is a real, meaningful value — a min or max duration.
- Zero counts display as `0`, not `—` or blank — a zero count is information, not absence of data. The average-with-no-data case above is the one exception.
- Execution IDs truncate to their trailing characters via `truncateId`, not the leading ones — IDs are time-prefixed UUID7s, so the shared prefix carries no information and the suffix is what distinguishes rows.
- **Identifiers are never truncated.** App names, handler names, and class names are how the user finds things — they render in full even when long, wrapping rather than clipping. Everything else (log messages, config values) can truncate as long as the full value stays reachable (hover, click-to-expand, or a detail view).

## Loading States

**Initial load** renders the shared `Spinner` (`components/shared/spinner.tsx`) until the page's primary query resolves — see the `isPending` checks in `apps.tsx`, `handlers.tsx`, and `app-detail.tsx`. There is no skeleton-loader pattern.

**Refetches** (changing the time window, filtering) keep the already-loaded data on screen; don't swap content back to a spinner once a page has rendered.

**Failures surface at the level they affect.** A failed or empty query renders `EmptyState` (`components/shared/`) with a specific title and body in the section that needed the data (e.g. "failed to load execution" vs. "execution not found" in `execution-detail.tsx`), and the rest of the page keeps working. Connection state lives in the persistent `SystemHealth` indicator (`components/shared/system-health.tsx`), not in per-page errors. Failed apps are status, not loading errors: they show through their status dot/badge, and the page-level `AlertBanner` (`components/layout/alert-banner.tsx`) lists every failed app with its error.

## Accessibility

- Meet WCAG AA contrast for text, status labels, controls, and focus indicators (see Ink Token Contrast above for the safe usage tiers).
- Never rely on color alone for health or outcome.
- Use semantic headings, tables, tabs, lists, buttons, and links.
- Preserve visible keyboard focus and logical reading order.
- Drawers and dialogs must trap or manage focus correctly, hide inactive content from assistive technology, and restore focus when closed.
- Truncation must preserve access to the full value through layout, title text, or a detail view.
- Loading, empty, disconnected, stale, and error states must explain what happened and what the user can do next.

## Avoid

- Generic SaaS dashboards made from interchangeable metric cards.
- Enterprise control-room language or styling.
- Home Assistant visual mimicry.
- Terminal cosplay, dark neon palettes, and excessive monospace.
- Faint grid backgrounds and decorative data visualization.
- Tiny supporting text used to manufacture density.
- Over-soft rounded containers and indiscriminate shadows.
- Dense handler layouts that expose every implementation detail before selection.
- Hiding app health or critical failures to create a cleaner composition.
- Redesigning multiple navigation or interaction models during a polish task.
- Stacking two elements at the same shadow level (see Depth above).
- Left-border accents (a thick colored border on one side of a card or row) — a recognizable AI-generated tell. Show hierarchy or emphasis with indentation, spacing, surface changes, heading weight, or full borders.
- Wrapping a table in the decorative `Card` component instead of `TableCard`.

## Protect These Patterns

These elements are working well — a change that regresses them needs a stated reason, not just an incidental side effect of something else:

- Font pairing: Newsreader + Geist + Geist Mono is distinctive and legible.
- The 4px spacing grid — the scale itself is sound; apply it consistently rather than reaching for ad hoc values.
- Dark mode token values — the dark palette is well-calibrated.
- Status color semantics — the success/warning/destructive/muted mapping is clear.
- Card styling — the border + radius + shadow combination.
- Sidebar navigation — spacing and active-state treatment.
- The stats strip pattern — grid layout with label-above-value, zero-value muting.
- Accessibility — focus indicators, skip links, ARIA roles, keyboard support. Don't remove any of it.
- Handler health card layout — the mini-dashboard per handler.

## Evolving This Context

This document should change when an incremental improvement becomes an established convention, not for every one-off visual adjustment. Concrete implementation rules (typography, spacing, tables, color, motion, and so on) live here alongside the direction they serve — this is the one design reference for the frontend; there is no separate implementation-rules file. CSS architecture and Tailwind build mechanics (how tokens are wired into `@theme`, how shadcn primitives are aliased, lint guards) live in `.claude/rules/frontend-css.md`.

When changing the design:

1. Compare the result with the visual baseline and state why the deviation improves the user's task.
2. Test desktop and mobile behavior with realistic healthy, empty, degraded, and failing data.
3. Prefer a small implementation slice that can be reviewed independently.
4. Update this document only when the change establishes a reusable rule or replaces a baseline decision.
5. Refresh the affected visual baseline after the implementation is stable.
