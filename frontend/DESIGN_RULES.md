# Design Rules

Concrete visual rules for hassette's web UI. Claude reads this when making frontend changes.

These rules codify what's already working and fix what's inconsistent. They reference the existing token system in `src/styles/tokens.css`. Every rule uses specific tokens or values — no subjective judgment required.

## Typography Hierarchy

The UI uses two font families: Newsreader (serif, display) and Geist (sans, body). The rule is: **Newsreader is for page identity only. Geist does everything else.**

| Element | Font | Size | Weight | Color | Tracking |
|---------|------|------|--------|-------|----------|
| Page title (h1) | Newsreader | `--fs-h1` (28px) | 400 | `--ink-1` | `--tr-h1` |
| Section heading (h3) | Geist | `--fs-h3` (16px) | `--fw-semibold` | `--ink-1` | none |
| Subsection label | Geist Mono | `--fs-xs` (11px) | `--fw-medium` | `--ink-3` | `--tr-label` uppercase |
| Table header | Geist Mono | `--fs-micro` (12px) | `--fw-medium` | `--ink-3` | `--tr-label` uppercase |
| Body text | Geist | `--fs-body` (14px) | 400 | `--ink-1` | none |
| Secondary text | Geist | `--fs-small` (12.5px) | 400 | `--ink-3` | none |
| Stat value | Geist | `--fs-stat` (26px) | `--fw-medium` | `--ink-1` | none |

**Why the change for section headings:** Currently section headings ("handler health", "recent activity", "logs") all use Newsreader at 16px normal weight. They look too similar to each other and blend with surrounding text. Switching to Geist semibold creates visible hierarchy between the page title (serif, large) and section labels (sans, smaller, weighted). The serif display font stays special because it's used sparingly.

## Spacing Rhythm

The page uses a two-tier vertical rhythm: **group gaps** (between semantic groups) and **internal gaps** (between elements within a group).

### Semantic Grouping

Elements that describe or identify the same entity belong in a tight group. The large section gap applies between groups, never between siblings within a group.

| Internal gap | Token | Value | Use for |
|-------------|-------|-------|---------|
| Tight | `--sp-2` to `--sp-3` | 8-12px | Between elements within a group |
| Card padding | `--sp-5` | 20px | Inside a card container |
| Compact card | `--sp-3` | 12px | Compact card variant |

| Group gap | Token | Value | Use for |
|-----------|-------|-------|---------|
| Section to section | `--sp-7` | 32px | Between semantic groups on a page |

**Examples of groups** (tight internal spacing):
- Breadcrumb + title + subtitle + tab bar (page identity)
- Section heading + its content (e.g., "handler health" + the handler cards)
- Stats strip + the list or table it summarizes
- Search input + the table it filters
- A label + its value

**The test:** if two adjacent elements are "about" the same thing, they're in the same group and get tight spacing. If they're about different things, they're separate groups and get `--sp-7` between them.

**Implementation:** Group siblings into semantic containers. Apply `--sp-7` as the gap between containers, not as the gap on the page-level flex/grid. A flat gap on `.ht-page` will always be wrong because it can't distinguish within-group from between-group.

## Tables

### Column Priority

Tables must remain readable without horizontal scrolling. When the viewport is narrow, hide columns in this order (least important first):

**Handlers table priority:** type, app, name, trigger, runs, error rate, avg duration. Hide from the right. "FAILED", "TIMED OUT" can merge into a single "ERRORS" column, or hide below 900px.

**General rule:** If a table header truncates or wraps, the table has too many columns for the viewport. Either hide lower-priority columns at that breakpoint or abbreviate the headers.

### Text Weight in Tables

Not all columns are equal. Apply ink tokens to create a scannable hierarchy:

| Column type | Color | Font | Example |
|-------------|-------|------|---------|
| Primary identifier | `--ink-1` | Geist Mono | App name, handler name |
| Numeric value | `--ink-1` | Geist Mono | Run count, duration, error rate |
| Timestamp | `--ink-3` | Geist Mono | "3h ago", "05/27 12:19:10" |
| Status/category | semantic color | Geist | "running", "failed", "event" |
| Secondary metadata | `--ink-3` | Geist | Class name, trigger type |

The reader's eye should land on primary identifiers first, then values, then timestamps.

### Table Footers

Footer text ("13 apps", "21 handlers") uses `--ink-3` at `--fs-small`. This is correct — keep it understated.

## Stats Strip

### Zero Value Muting

When a stat value is zero, mute it. This makes non-zero values pop without changing the layout.

- Non-zero values: use the semantic color assigned to that stat (ok for running, err for failed, etc.), or `--ink-1` for neutral stats
- Zero values: use `--ink-4` for both the value and the label
- The stat that matters most in the current context keeps `--ink-1` regardless

### Label Casing

Stats strip labels are uppercase Geist Mono with wide tracking. This is correct and consistent — keep it.

## Search Inputs

Search sits between the section heading and the table, part of the section flow. Place it right-aligned in the same row as the section heading, or on its own line directly above the table.

**Placement rule:** Search filters content below it. It belongs to the section, not to a container around the table.

## Cards and Containers

### Tables Are Not Cards

Tables provide their own visual structure — the header row (uppercase mono, `--bg-sunken`) creates a clear top edge, row borders create internal structure, and the footer text provides closure. Wrapping a table in a card adds border + shadow + padding for no information gain. It also creates whitespace problems (search input positioning, padding around already-padded table cells).

**Rule: tables sit directly on the page surface.** No card wrapper, no border, no shadow. The table header row is the visual anchor.

### When to Use a Card

- **Stats strips** — distinct summary data blocks. Card styling built in.
- **Handler health tiles** — mini-dashboards per handler. Cards.
- **Config key-value groups** — grouped entities that benefit from visual containment.
- **Empty states** — when a section has no content to show.
- **Tables** — no. The table IS the structure.
- **Inline content** (section heading + text, diagnostics lists) — no card.

### Nesting

Avoid card-inside-card. If a section is already inside a card, sub-elements are separated by borders (`--line-1`), not nested cards.

## Repetitive Lists

### Mute Uniform Status

When a list of items all share the same status (all green, all running, all healthy), the status indicators become noise instead of signal. Mute the uniform state: use `--ink-4` for status dots and `--ink-3` for status text. Reserve full-color status indicators for items that differ from the majority. The reader should spot exceptions, not count confirmations.

### Use Multi-Column Grids for Simple Items

When list items are short (name + status, or name + value), a single-column layout wastes horizontal space and forces unnecessary scrolling. Use a two-column CSS grid above 768px for items that don't need the full page width. The test: if the longest item fills less than half the content width, it should share a row.

### Compact Absence

When a section exists to surface problems and there are no problems, don't celebrate the absence. One line of muted text ("no issues") is enough. No card wrapper, no centered icon, no explanatory paragraph. Empty states with full visual treatment (icon + title + body text) are for primary content areas where the user expected to find data, not for status sections reporting "all clear."

## Shadows and Elevation

### The Elevation Model

The UI has three visual layers. Every element belongs to exactly one.

| Layer | Background | Shadow | What lives here |
|-------|-----------|--------|-----------------|
| Page | `--bg-page` | none | Page background, sidebar background |
| Surface | `--bg-surface` | `--shadow-2` | Main content area (the white panel with rounded top corners) |
| Elevated | `--bg-surface` | `--shadow-2` | Stats strip, handler health tiles, config groups, dialogs |
| Sunken | `--bg-sunken` | none | Table headers, hover states, code blocks, input backgrounds |

**Principle: fewer elevated elements = cleaner page.** With tables unwrapped from cards, a typical page has 1-2 elevated elements (stats strip, maybe handler tiles) instead of 3-4. This is intentional.

### Shadow Levels

| Level | Token | Use for |
|-------|-------|---------|
| shadow-1 | `0 1px 2px rgba(20,22,26,0.04)` | Hover lift effects, mobile cards |
| shadow-2 | `0 2px 8px ... + 0 1px 2px ...` | Cards, the main content panel |
| shadow-3 | `0 8px 24px ... + 0 2px 6px ...` | Overlays: dropdowns, drawers, dialogs, command palette |

**Rule: never stack shadows.** A card inside the main content panel doesn't get shadow-2 + shadow-2. The card's shadow replaces the surface context — they sit at the same visual level. If an element needs to float above a card (tooltip, dropdown), it uses shadow-3.

### Hover Effects

Interactive cards (handler health tiles) get a subtle lift on hover: transition to `--shadow-3` at `--t-fast`. Tables rows use background shift (`--bg-sunken`) instead of shadow — rows don't float.

## Border Radius

### Recommended Scale

| Token | Current | Recommended | Mobile (<768px) | Use for |
|-------|---------|-------------|-----------------|---------|
| `--r-sm` | 10px | 6px | 6px | Badges, chips, inline code, small elements |
| `--r-md` | 15px | 8px | 8px | Buttons, inputs, default |
| `--r-lg` | 20px | 12px | 10px | Cards, main content panel top corners |
| `--r-xl` | 30px | 20px | 16px | Large modals, sheets |
| `--r-pill` | 999px | 999px | 999px | Pills, toggle tracks (unchanged) |

Tighter radii read as more intentional and less decorative. At 8px default, corners are softened without becoming a visual feature. The current 15px rounds corners enough to draw attention to the rounding itself. Professional reference: GitHub uses 6px, Linear uses 8px, Grafana uses 4px.

### Consistency Rule

Every rounded element uses a token — never a hardcoded value. If an element needs a radius between two tokens, use the smaller one.

## Contrast and Ink Safety

### Ink Token Contrast Ratios (against `--bg-surface` white)

| Token | Hex | Contrast vs white | WCAG AA (normal text) | WCAG AA (large text) |
|-------|-----|-------------------|----------------------|---------------------|
| `--ink-1` | #16181c | ~16:1 | Pass | Pass |
| `--ink-2` | #4a4d54 | ~7.5:1 | Pass | Pass |
| `--ink-3` | #787c84 | ~4.5:1 | Borderline | Pass |
| `--ink-4` | #b0b3b8 | ~2.7:1 | Fail | Fail |

### Safe Usage Rules

- **`--ink-1`**: any text, any size. Primary content.
- **`--ink-2`**: any text, any size. Secondary content, descriptions.
- **`--ink-3`**: safe at `--fs-body` (14px) and above. At `--fs-micro` (12px) and below, use only for non-essential text (timestamps, metadata) where failing AA is acceptable because the information is supplementary. Never use for actionable text at small sizes.
- **`--ink-4`**: decorative only. Placeholder text, disabled states, ornamental separators. Never for text the user needs to read. WCAG AA fails at all sizes.

### Dark Mode Contrast

The dark theme inverts appropriately. `--ink-1` in dark mode (#edeff3) against `--bg-surface` dark (#1a1c21) has strong contrast. The same tier rules apply — `--ink-4` in dark mode is still decorative-only.

## Color Usage

### Surfaces

- Page background: `--bg-page` (warm off-white in light, near-black in dark)
- Main content: `--bg-surface` (white in light, dark gray in dark)
- Recessed areas: `--bg-sunken` (table headers, code blocks, input backgrounds)
- Active/pressed: `--bg-active`
- Hover: `--bg-sunken`

**Rule: the surface stack goes in one direction.** Page → surface → sunken. Never put `--bg-page` inside `--bg-surface`, or `--bg-surface` inside `--bg-sunken`. The depth should always increase inward.

### Accent Color

The accent (oklch hue 255, blue-purple) is used for:
- Links
- Active tab indicators
- Focus rings
- Primary buttons
- Selected/active sidebar items

**Rule: accent is for interactive affordances only.** Don't use accent for decoration, emphasis, or highlighting data. If something isn't clickable or focused, it doesn't get accent color.

### Status Colors in Context

- **In tables and lists:** status color on the status text only, not the row background
- **In stats strip:** semantic color for non-zero values, `--ink-4` for zero
- **In handler health tiles:** the status dot is the indicator; the tile border stays `--line-strong`
- **For the Stop button:** outlined with `--err` text and border, not filled `--err-bg`. Destructive but not urgent — it shouldn't dominate the page.

### Color Restraint

A professional dashboard uses color sparingly. On any given page, the visible colors should be:
- Neutrals (ink scale + surfaces) for 90% of the content
- One accent color for interactive elements
- Status colors only where status is being communicated

If a page screenshot looks colorful, something is wrong. The default state of a healthy system is mostly neutral with small pops of green and blue.

## Borders and Lines

Three border tokens exist. Each has a specific role — don't mix them.

| Token | Value (light) | Use for |
|-------|--------------|---------|
| `--line-1` | #e6e6e2 | Subtle separators within a container: table row borders, dividers between sections inside a card, tab bar bottom border |
| `--line-2` | #ecece8 | Group separators: between sidebar nav groups, between card sections that aren't strongly distinct |
| `--line-strong` | #d0d0cc | Container edges: card borders, input borders, stats strip border, any element that needs a visible boundary against the page |

### Rules

- **Table rows:** `--line-1` bottom border on cells (subtle, doesn't compete with content)
- **Table header:** `--line-1` bottom border (the `--bg-sunken` background already separates it visually)
- **Section dividers:** `--line-1` horizontal rule between major page sections (handler health / recent activity / logs on the overview tab)
- **Card borders:** `--line-strong` (the card needs to stand out from the surface)
- **Input borders:** `--line-strong` at rest, `--accent` on focus
- **Nested dividers inside cards:** `--line-1` (lighter than the card's own border)

**Never use a border where spacing alone would work.** If two elements are visually distinct because of their own structure (a heading followed by a table), a divider between them adds noise. Borders are for separating things that would otherwise bleed together.

## Motion

### What Animates

| Element | Property | Duration | Easing |
|---------|----------|----------|--------|
| Hover states (buttons, rows, links) | background-color, color | `--t-fast` (120ms) | `--ease` |
| Card hover lift | box-shadow | `--t-fast` | `--ease` |
| Tab underline | border-color, color | `--t-fast` | `--ease` |
| Sidebar drawer open/close | transform | `--t-med` (200ms) | `--ease` |
| Drawer backdrop | opacity | `--t-med` | `--ease` |
| Focus ring | outline | `--t-fast` | `--ease` |
| Tooltip appear | opacity | `--t-fast` | `--ease` |

### What Does Not Animate

- Page transitions (no route animation)
- Table row additions/removals (they appear/disappear instantly)
- Stats strip value changes (instant update)
- Section expand/collapse (instant, unless it's a drawer/panel)
- Color theme switch (instant — animating light↔dark creates a flash)

### Principle

Animation confirms an interaction happened. It's feedback, not decoration. If the user didn't trigger it, it doesn't animate. Data updates are instant. User-initiated state changes get a brief transition.

`prefers-reduced-motion` is already handled (durations drop to 0.01ms). Don't add animation that bypasses this.

## Data Formatting

### Timestamps

| Context | Format | Example |
|---------|--------|---------|
| Within the last hour | Relative | "12m ago" |
| Within the last 24 hours | Relative | "3h ago" |
| Older than 24 hours | Absolute, compact | "05/25 10:21" |
| Tooltip/detail view | Full | "2026-05-25 10:21:22" |
| Range | Relative pair | "36m ago–3h ago" |

**Rule:** relative timestamps update live via the time window, not on a timer. They reflect the selected window (Since restart, 1h, 24h, 7d), not wall clock.

### Durations

| Range | Format | Example |
|-------|--------|---------|
| Under 1 second | Milliseconds, 1 decimal | "1.3ms", "332.1ms" |
| 1–60 seconds | Seconds, 1 decimal | "4.2s" |
| Over 60 seconds | Minutes and seconds | "2m 15s" |

No microseconds. No durations beyond hours (if something takes that long, the display should show the start time instead).

### Counts

- Integers with no decimals: "4 calls", "13 apps"
- Rates with 1 decimal: "39.5 runs/hr"
- Percentages with no decimal unless under 1%: "100%", "0.0%", "95%"
- Zero values: display "0", not "–" or blank. The zero is information.

### Truncation

| Element | Max display | Overflow |
|---------|------------|----------|
| App name in table | Full | Never truncate — names are identifiers |
| Class name in table | Full | Never truncate |
| Log message in table cell | Single line | Ellipsis (`text-overflow: ellipsis`), full text in detail drawer |
| Config value | ~60 characters | Ellipsis, full text on hover (title attribute) or click-to-expand |
| Execution ID | 7 characters | Truncate with ellipsis, full ID in tooltip |
| File path | ~40 characters | Truncate from the left (show filename, not root): "…/src/apps/air_purifier.py" |

**Rule:** identifiers (app names, handler names, class names) are never truncated. They're how the user finds things. Everything else can truncate if it provides a way to see the full value.

## Information Density

### Stance: Spacious but Not Wasteful

Hassette is a monitoring dashboard checked occasionally, not a trading terminal watched all day. Generous spacing is correct — it reduces cognitive load for infrequent use. But spacing should serve grouping, not fill the page.

**The test:** can you see the most important information on each page without scrolling? On the apps page: the stats strip + at least the first 5-6 app rows. On the app detail overview: handler health + recent activity. If you have to scroll past whitespace to reach content, the spacing is wasteful.

### Density Rules

- **Page padding:** `--sp-7` (32px) on desktop is correct. Don't reduce it.
- **Section gaps:** `--sp-7` (32px) between sections. Not more. The current flat `--sp-4` is too tight; anything over `--sp-8` wastes vertical space.
- **Card internal padding:** `--sp-5` (20px). Don't increase it.
- **Table row height:** determined by cell padding (`--sp-2` vertical) + line height. Don't add extra. Rows should be compact enough to show 10+ without scrolling.
- **Empty space at bottom of page:** acceptable. Don't pad the bottom to push content up or center it vertically.

## Loading States

### Page Load

When a page is loading data, show the page structure immediately (heading, stats strip skeleton, empty table with headers) and fill in data as it arrives. Never show a full-page spinner or blank page.

### Skeleton Pattern

- Stats strip: show the label text immediately, replace values with a pulsing `--bg-sunken` bar (same width as a typical number)
- Tables: show column headers immediately, show 3-5 skeleton rows with pulsing bars for cell content
- Handler health tiles: show the tile outline, pulse the inner content area
- Skeleton pulse: `--bg-sunken` → `--bg-active` → `--bg-sunken`, 1.5s cycle, `ease-in-out`

### Inline Loading

When refreshing data within an already-loaded page (changing time window, filtering), don't replace content with skeletons. Keep the stale data visible and add a subtle loading indicator — a thin progress bar at the top of the content area or a brief opacity reduction (`--op-muted`) on the updating section.

### Error States

| Severity | Appearance | When |
|----------|-----------|------|
| Connection lost | Alert banner at top, `--warn` color, persistent until reconnected | WebSocket disconnect |
| App failed | Status dot `--err`, row text stays `--ink-1` | App crash/exception |
| Load failure | EmptyState component with error icon, retry button, `--err` accent | API request failed |
| Partial failure | Inline text "failed to load" in `--ink-3` where data would be, rest of page works | One section of a page failed |

**Rule:** errors surface at the level they affect. A single failed API call doesn't show a full-page error — it shows an inline failure in the section that needed that data. Only total connection loss gets a page-level banner.

## Number Alignment

### Right-Align Numeric Columns

In tables, numeric values (counts, durations, percentages, rates) right-align so digits and decimal points line up vertically. This makes it possible to scan a column and compare values at a glance.

| Column type | Alignment |
|-------------|-----------|
| Text (names, identifiers, messages) | Left |
| Status badges | Left |
| Counts | Right |
| Durations | Right |
| Percentages | Right |
| Rates | Right |
| Timestamps | Right (they're fixed-width, so left works too — pick one per table and be consistent) |

The column header aligns with its content — a right-aligned column gets a right-aligned header.

### Monospace for Numbers

All numeric values in tables use Geist Mono. This ensures digits are the same width, which is what makes right-alignment work. Proportional fonts make "111" narrower than "999", breaking the vertical line.

## Detail View Hierarchy

### Minimize Parent Context When Drilling Down

When the user navigates deeper (list → detail → sub-detail), each level should reduce the parent's visual footprint. The user navigated here intentionally — the breadcrumb handles orientation, so parent-level summaries shouldn't consume primary real estate.

**Rule: context strips reflect the current detail level.** When viewing a sub-detail, the parent-level stats strip should either collapse to a compact single line or hide entirely. The current level's stats are what matters.

### Collapsible Metadata on Detail Pages

Detail pages often show reference information (source code, configuration, file paths, registration details) alongside primary content (execution history, log output, activity lists). When both are fully expanded, the reference metadata pushes primary content below the fold.

**Rule: primary content must be visible without scrolling past metadata.** Identify what the user came to this page to see (usually a table or activity feed), and ensure it's above the fold. Reference metadata that supports but isn't the reason for the visit should collapse by default, with a toggle to expand.

**What stays visible:** identity (name, type badge, key description) and 2-3 key stats.
**What collapses:** source code snippets, file paths, full stats breakdowns, secondary links.

### Stats Strip Column Limits

A stats strip should have **5-7 columns max.** Beyond that, values compete for attention and the strip wraps awkwardly on narrow viewports. When a strip has too many columns:

- Combine redundant stats (e.g., count + successful count when success rate is also shown)
- Move less-critical breakdowns into a collapsible detail section
- Show the most useful single metric in the strip, with the full breakdown available on expand or tooltip

### Inline Row Expansion

When a table row expands to show detail (clicking an invocation row):

- **Keep it tight.** The expanded area should not be taller than 3-4 table rows. If detail needs more space, use a drawer or panel instead.
- **Empty states in expanded rows are one line.** "No logs for this execution" in `--ink-3`, no icon, no card, no explanation paragraph. The expansion is secondary context — it shouldn't draw more visual weight than a row with actual content.
- **The selected row highlight** (tinted background) is correct. Keep it as the visual anchor showing which row is expanded.
- **Only one row expanded at a time.** Clicking another row collapses the current expansion and opens the new one.

### When to Use a Drawer Instead of Inline Expansion

If the detail content is rich (logs, tracebacks, state diffs) and the user might want to compare it across executions, a side drawer or bottom panel works better than inline expansion. Inline expansion shifts the table rows, making comparison across entries difficult.

**Guideline:** if the expanded content is just metadata (IDs, timestamps, a result status), inline expansion is fine. If it includes scrollable content (log output, stack traces), use a drawer.

## Responsive Behavior

### Breakpoints

The existing breakpoints are correct:
- 900px: sidebar collapses to drawer
- 768px: reduce padding, simplify tables, stack layouts
- 480px: minimal padding, essential content only

### Table Behavior at 768px

Fixed-layout tables (`.ht-table--fixed`) keep `table-layout: fixed` at every breakpoint and hide non-essential columns rather than allowing horizontal scroll or header truncation. Switching to `table-layout: auto` on mobile lets unbreakable mono content (entity IDs, app keys, log messages) push the table past the viewport and crop columns mid-word — the colgroup must instead reallocate widths to the columns that remain visible at that breakpoint (see `apps.module.css` for the pattern). Any table whose headers truncate or wrap at a breakpoint needs column hiding at that breakpoint.

The exception is `.ht-table--compact`, which switches to `auto` at 768px. **A table may only use this class when every column visible on mobile is bounded** — short values, hidden at the breakpoint, or wrappable via `word-break` — because auto layout has nothing to keep an unbounded column from pushing past the viewport. The execution history table qualifies because status/time/duration are short and its one wide column (trace) hides at that breakpoint; the config key/value tables qualify because their value cells use `word-break: break-all`.

### Mobile Detail Pages (<768px)

Detail pages are the hardest to get right on mobile because every layer of context (header, tabs, stats strip, metadata) competes for a viewport that's only ~700px tall.

**Rules for mobile detail views:**

1. **Collapse metadata aggressively.** On mobile, detail metadata (source references, configuration, full stats breakdowns) hides behind a toggle by default. Only identity + 2-3 key stats stay visible. The primary content (tables, activity feeds) must be reachable without scrolling past metadata.

2. **Stats strips show 3-4 columns max on mobile.** Strips that wrap to multiple rows create visual noise. Pick the most important stats for the mobile view; the rest lives in the collapsed detail section or a tooltip.

3. **Code blocks scroll horizontally.** Code that truncates with no way to see the rest is broken. All code blocks get `overflow-x: auto` on mobile.

4. **Use bottom sheets instead of inline expansion on mobile.** On a 375px viewport, inline row expansion consumes the entire visible area and pushes all other rows out of view. A bottom sheet (half-viewport height, swipe to dismiss) keeps the table visible above. On desktop, inline expansion is fine when kept tight (see Inline Row Expansion rules).

5. **Empty states in secondary contexts are one line on mobile.** "No logs" in `--ink-3`. The full EmptyState component (icon + title + body text) is for primary content areas, not expansion panels or sub-sections.

### Mobile Navigation Context

On mobile, the header bar (hamburger, time window, connection status, theme toggle) must stay fixed at the top of the viewport. If it appears mid-page in the document flow, it's a layout bug — the sticky positioning has broken.

### What Already Works on Mobile

These adaptations are already correct — maintain them:
- Time window buttons → dropdown select
- Stats strip → responsive grid reflow
- Execution ID column hidden from invocations table
- Sidebar → drawer with backdrop
- Chevron (›) affordance on table rows indicating tap targets

## Buttons

### Action Button Placement

Page-level actions (Reload, Stop) sit right-aligned in the title row. This is correct.

### Button Visual Weight

- **Primary actions** (Reload): outlined style, normal weight. Correct.
- **Destructive actions** (Stop): filled `--err-bg`. Consider reducing to outlined with `--err` text + border to lower visual weight — Stop is available but shouldn't dominate the page.
- **Ghost buttons** (filter icons, sort toggles): transparent, `--ink-4` default, `--ink-2` on hover. Correct.

## Tabs

The tab bar is clean. Rules to maintain:

- Active tab: `--fw-medium`, underline `--accent`, `--ink-1` text
- Inactive tab: normal weight, no underline, `--ink-3` text
- Tab bar sits inside a card-like container with bottom border. Keep this.
- Badge counts in tab labels (e.g., "handlers 2") use the neutral badge style.

## Code Viewer

The Shiki-powered code viewer looks professional. Rules to maintain:

- Line numbers: `--ink-4`, right-aligned, `--sp-4` right padding
- Code font: Geist Mono, `--fs-mono-md` (13px)
- Background: `--bg-sunken`
- Header bar: filename left, metadata right, `--fs-small`, `--ink-3`

## What Not to Change

These elements are working well — don't regress them:

- **Font pairing.** Newsreader + Geist + Geist Mono is distinctive and legible.
- **The 4px spacing grid.** The token scale is well-designed. The issue is consistency of application, not the scale itself.
- **Dark mode token values.** The dark palette is well-calibrated.
- **Status color semantics.** Green/amber/red/gray mapping is clear.
- **Card styling.** Border + radius + shadow combination is clean.
- **Sidebar navigation.** Clean, well-spaced, good active state treatment.
- **The stats strip pattern.** The grid layout with label-above-value works. Just needs zero-value muting.
- **Accessibility.** Focus indicators, skip links, ARIA roles, keyboard support. Don't remove any of it.
- **Handler health card layout.** The mini-dashboard per handler is a good pattern.
