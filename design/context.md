---
schema_version: 1
updated_at: 2026-05-05
---

## Users & Purpose

A technical hobbyist — not a developer by trade, but savvy enough to run Home Assistant, configure YAML, and drop Python files into an apps directory. They're comfortable with entity IDs and config keys but don't live in a terminal. They pull up the UI with a question already in mind, not for passive monitoring.

**Task**: Diagnose. Verify. Confirm or refute a hypothesis fast. "Did my handler fire? What values did it see? Did it error? What was the exception?" — then close the tab. Occasionally: check that everything is healthy after a restart, or browse the logs after something unexpected happened.

**Context**: The UI is one tab among many. The user doesn't spend hours in it. They arrive, find what they need, and leave. Speed of comprehension matters more than aesthetic delight.

## Brand Personality

The contrast IS the personality. A warm editorial shell — Newsreader serif headings, cream-toned backgrounds, considered spacing — wrapping raw technical data: monospace handler names, entity IDs, Python tracebacks, invocation counts. Don't resolve this tension; lean into it.

Like a well-typeset technical manual. The cover is beautiful, the content is precise. The UI should feel like it was built by someone who cares about typography AND reads stack traces daily.

**Tone**: Neutral and slightly understated. Hassette tells the user what's happening; it doesn't editorialize. No exclamation points except in genuine error states. No "Oops!" or "Looks like..." No emoji.

## Content Fundamentals

**Voice**: Second person sparingly. Most copy is descriptive ("3 apps failing" not "You have 3 failing apps"). System messages prefer the imperative ("Restart the app to apply changes" not "You'll need to restart...").

**Casing**: Sentence case throughout — "Stop motion_lights?", not "Stop Motion_Lights?". Code identifiers (app names, entity IDs, file paths) keep their literal casing.

**Numbers**: Integers for counts, no thousands separator under 10k. Durations use `2.4s`, `380ms`, never "2.4 seconds". Times are 12-hour with seconds where precision matters (`7:25:37 PM`), or relative for recency ("4m ago", "yesterday").

**Errors**: Lead with what happened, then what to do. "Could not connect to broker — check `mqtt.host` in config." Not "Error: connection failed."

**Empty states**: Short, factual, friendly. "No events match this filter." Not "Nothing to see here!"

## Aesthetic Direction

### References

- **Linear** — information density and monospace meta text. Compact rows that expand on click. Dense but scannable. Everything where you expect it.
  - **Take**: Row density, expand-on-click pattern, monospace for IDs/timestamps
  - **Leave**: The cool blue palette, the breadcrumb-heavy navigation

- **Vercel dashboard** — KPI strip, status badges, flat-but-not-flat surface hierarchy. Quiet confidence.
  - **Take**: KPI card pattern, status badge language, surface layering approach
  - **Leave**: The aggressive minimalism that sacrifices information density

- **The Well-Made Notebook** — warm off-whites, serif headings, careful ink — the sensation of a good technical manual. Newsreader for headings brings character; Geist body text keeps it modern and fast to read.
  - **Take**: The warmth of off-white backgrounds, the personality of a real serif for display type
  - **Leave**: Slow-reading text columns, ornamental spacing

- **Prefect (Miter Design)** — state-driven color where every hue earns its place by representing a workflow state. Colorblind-accessible status shapes. Speed as a feature.
  - **Take**: Deliberateness of state color assignment, the visual hierarchy in flow run pages
  - **Leave**: Radial/constellation visualizations (Hassette's domain is flat lists, not DAGs)

**Visual movement**: Editorial tension — a warm, typographically considered shell wrapping raw diagnostic data. Not pure editorial minimalism, not developer terminal, not consumer SaaS. The tension between the two registers is deliberate.

### Domain Concepts

- **Wiring** — handlers connected to entity events, jobs on intervals, delayed tasks. The app detail page surfaces this with type badges (event, interval, after).
- **Pulse** — system liveness. The breathing dot, the "up 7m" label, the "connected" status. Multiple heartbeats layered: WebSocket, telemetry health, service readiness.
- **Greeting** — the UI knows what time it is and what state the system is in. "Good evening. all apps are healthy." Diagnostic triage disguised as hospitality.
- **Activity** — runs per hour, sparklines, invocation counts. The system has a metabolic rate.
- **Registry** — what's loaded, running, disabled. The sidebar IS the registry — status-grouped, filterable, showing invocation counts in real time.
- **Trace** — following what happened from effect to cause. Logs, recent errors, handler invocation detail. Monospace content inside editorial containers.

### Color World

Ink on warm cream paper. Status lights on a quiet instrument panel — green, amber, red, grey — each appearing only to communicate state, never for decoration. The warm off-white background prevents the clinical feel of pure white. In dark mode, deep charcoal with a periwinkle-blue accent that feels restrained, not the ubiquitous indigo.

The color world is deliberately narrow: most of the page is neutral (ink on cream). The only hue that "lives" on the page is green — because most of the time, things are running. Red and amber are visitors, not residents.

### Signature Elements

Two signature elements work in tandem:

**The breathing pulse dot** — 8px circle in the status bar, accent-colored with a 2.5s ease-in-out inhale/exhale animation when connected. Static and red when disconnected, amber when degraded. The only continuously animated element. It breathes because the WebSocket connection is alive.

- Appears in the **StatusBar** (top-right) and **sidebar version area** (below wordmark)
- States: `connected` (accent, breathing), `connecting` (muted, static), `degraded` (warn, static), `disconnected` (err, static)
- Reduced motion: static dot, no animation

**The greeting** — "Good evening." in Newsreader serif, followed by a plain-language system summary. Not a dashboard title — a sentence that tells you what's happening. Changes with system state: "garage_alerts needs your attention" vs "nothing needs your attention right now." This is the editorial tension in action.

### Defaults Rejected

| Default | Why it's wrong | Better alternative |
|---------|---------------|-------------------|
| Indigo/violet accent | Tailwind default, every AI-generated UI uses this — zero personality | Ink-1 (near-black) in light mode; periwinkle-blue in dark — accent earns its place through restraint |
| Dark sidebar on light page | Jarring mixed-mode contrast that fights for attention | Sidebar uses same `--bg-page`, separated by border not color contrast |
| Sidebar with icons | Icon+label is generic SaaS nav | Text-only nav labels; the app registry below the nav IS the primary interaction surface |
| Dashboard as KPI grid | Rows of identical metric cards is a monitoring dashboard, not a diagnostic tool | Greeting + system state subtitle, stats strip, and summary cards — the page adapts its emphasis based on what's happening |
| Skeleton loaders | Shimmer placeholders are consumer-app polish | Single spinner for initial load; stale data with `opacity: 0.6` during refetch |
| Card nesting | Cards inside cards creates visual noise | Handler rows are list items in bordered containers |
| Bounce/elastic easing | The UI is a tool, not a toy | All transitions use the Ink easing curve |
| Warm amber as primary accent | Overused, dilutes status meaning | Status tones (ok/warn/err) are semantic-only; never decorative |

## Concrete Constraints

- **No rounded corners above 8px** (except pills at `--r-pill`) — the product is technical
- **Body text is Geist, never a raw system font** — controlled and on-brand
- **Display headings (h1-h3) use Newsreader** — this is where the editorial tension lives
- **Maximum 4 semantic hues beyond neutrals** (ok, warn, err, mute) — density demands restraint
- **Monospace for all data** — entity IDs, timestamps, handler names, invocation counts, log entries, config keys. Most content on the page is mono. This is the "raw technical data" half of the tension.
- **No icons without text labels** in main nav or content — sidebar nav is text-only; exceptions: dense action clusters (reload/stop) and the status bar (pulse dot, theme toggle)
- **Density is a feature** — row padding is compact (10-12px vertical), meta text gaps tight, whitespace for section separation not breathing room
- **No status colors on non-status elements** — `--ok`/`--warn`/`--err` reserved for state communication only
- **Borders for depth, shadows for floating** — cards use `--line-1` borders; shadows only on genuinely floating surfaces (modal, command palette, dropdown)
- **Greeting, not dashboard title** — the overview page opens with a time-of-day greeting and system state sentence, not "Dashboard" or "Overview"
- **No left-border accents** — AI slop pattern; use indentation, spacing, or weight instead
- **No emoji** — not in tone, not in code samples, not in microcopy

## Design Principles

1. **Answer the question** — every page exists to answer a specific diagnostic question. If a component doesn't help answer it, remove it.
2. **Hierarchy through type, not decoration** — Newsreader headings vs Geist body vs Geist Mono data create hierarchy. Not borders, backgrounds, or color for its own sake.
3. **Green means ok** — `--ok` is reserved for "connected, running, healthy." Don't dilute it on links, buttons, or decorative elements.
4. **Show state, don't narrate it** — a colored dot says "failed" faster than a paragraph. Status badges, sparklines, and color-coded values over prose descriptions.
5. **Respect the user** — no onboarding tours, no tooltips on obvious things, no confirmation dialogs for reversible actions. The user is technically capable.

## Iconography

Minimal. Most "icons" are typographic: bullets, arrows (`→` `↑` `↓`), keyboard hints (`⌘K`). When real icons are needed, use inline SVGs at 14-16px. Never decorative — every icon should communicate something the text doesn't.

Status indicators combine **shape + color**: filled circle for ok, triangle for warn, square for err, outline ring for muted. Status is readable in greyscale — color is reinforcement, not the only signal.

## Design Tokens

The design system uses unprefixed Ink tokens (no `--ht-*` prefix). Light mode is the `:root` default; dark mode activates via `[data-theme="dark"]`.

### Surfaces

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--bg-page` | `#FAFAF8` | `#111316` | Page canvas — warm off-white / deep neutral |
| `--bg-surface` | `#FFFFFF` | `#191B1F` | Cards, panels, list rows |
| `--bg-sunken` | `#F4F4F1` | `#15171B` | Inset areas, code backgrounds |
| `--bg-active` | `#F0F0EC` | `#1D2026` | Hover states, expanded details, active sidebar item |

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
| `--line-strong` | `#D0D0CC` | `#3A3E46` | Interactive element borders, focused inputs |

### Accent

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--accent` | `var(--ink-1)` | `#7A8AFF` | Primary interactive color |
| `--accent-ink` | `var(--bg-page)` | `#0F1115` | Text on accent background |
| `--accent-hover` | `#2A2D33` | `#93A0FF` | Hover state |
| `--accent-soft` | `#E8E8E5` | `#1A1F36` | Soft accent background (active tabs, selections) |

**Rationale**: In light mode, accent is `ink-1` (near-black). The system has personality through type (Newsreader) and surface warmth (`#FAFAF8`), not through a colored accent. In dark mode, periwinkle-blue earns its place without the "every AI-generated UI uses indigo" feel.

### Status

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--ok` / `--ok-bg` | `#1F7A4D` / `#EAF3EE` | `#5FB988` / `#19241E` | Running, healthy, connected |
| `--warn` / `--warn-bg` | `#9A6A12` / `#F5EEDD` | `#D9B36E` / `#272219` | Warning, elevated error rate, degraded |
| `--err` / `--err-bg` | `#B53024` / `#F5DEDC` | `#E08278` / `#28191A` | Error, failed, disconnected, crashed |
| `--mute` / `--mute-bg` | `#9097A0` / `#EFF0EC` | `#6A707A` / `#1D1F23` | Stopped, disabled, unknown |

### Typography

- **Display/headings (h1-h3)**: Newsreader 400 — a refined newspaper serif. Gives the UI character and warmth. Headings feel authored, not generated. This is the editorial half of the tension.
- **Body**: Geist 400/500 — clean, modern sans-serif by Vercel. Fast to read, pairs with Newsreader without competing.
- **Mono**: Geist Mono 400/500 — entity IDs, timestamps, handler names, invocation data, log entries, config keys. The workhorse font — most data on the page is monospace. This is the technical half of the tension.
- **Scale**:
  - `--fs-display` / `--lh-display`: 38px / 1.05 — hero display text (greeting)
  - `--fs-h1` / `--lh-h1`: 28px / 1.15 — page titles
  - `--fs-h2` / `--lh-h2`: 20px / 1.25 — section headings
  - `--fs-h3` / `--lh-h3`: 16px / 1.35 — subsection headings
  - `--fs-body` / `--lh-body`: 14px / 1.55 — body text, table data
  - `--fs-small` / `--lh-small`: 12.5px / 1.5 — meta text, captions
  - `--fs-micro` / `--lh-micro`: 11px / 1.4 — labels, uppercase tags
  - `--fs-mono-sm` / `--fs-mono-md`: 12px / 13px — code, data
- **Letter spacing**: Display and headings use negative tracking (`--tr-display: -0.025em` through `--tr-h3: -0.005em`) for optical tightness at large sizes.
- **Self-hosted**: WOFF2 files in `/frontend/public/fonts/` — Newsreader 400, Geist 400/500, Geist Mono 400/500

### Spacing

- **Base**: 4px (`--sp-1`)
- **Scale**: `--sp-1` (4px) through `--sp-10` (72px)
- **Density**: Diagnostic tool — density is a feature. Row padding compact (10-12px vertical). Meta text gaps tight (12-16px). Whitespace for section separation, not breathing room inside components. Information-dense surfaces (logs, tables) shrink to `--sp-2`/`--sp-3`; calmer surfaces (overview cards, modals) breathe with `--sp-5`/`--sp-6`.

### Shadows

- **`--shadow-1`**: `0 1px 2px rgba(20, 22, 26, 0.04)` — subtle card lift (light mode)
- **`--shadow-2`**: `0 2px 8px ... + 0 1px 2px ...` — card prominence
- **`--shadow-3`**: `0 8px 24px ... + 0 2px 6px ...` — dropdowns, modals, command palette
- **Dark mode**: Same shadow variables use higher opacity (0.3 / 0.4 / 0.5) against near-black backgrounds.
- **Usage rule**: Borders are the primary depth mechanism. Shadows reserved for genuinely floating surfaces only.

### Border Radius

- **`--r-sm`**: 4px — inputs, code spans, kbd badges
- **`--r-md`**: 6px — buttons, cards, list containers
- **`--r-lg`**: 8px — panels, larger cards
- **`--r-xl`**: 12px — modals, large containers
- **`--r-pill`**: 999px — status badges, status dots

### Motion

- **`--t-fast`**: 120ms — hover state transitions (background, border color)
- **`--t-med`**: 200ms — expand/collapse, tab switching, drawer slide
- **`--ease`**: `cubic-bezier(0.4, 0, 0.2, 1)` — the Ink easing curve. Used everywhere.
- **Signature animation**: pulse dot breathe, 2.5s ease-in-out infinite. Only continuous animation.
- **Reduced motion**: `@media (prefers-reduced-motion: reduce)` — all animations collapse to 0.01ms

## Component Inventory

### Layout

**Sidebar** — 240px fixed panel, left side. Text-only nav (overview, apps, logs, config) — no icons. Below the nav: APPS section header with count, search input, then status-grouped app entries (FAILING, BLOCKED, SLOW, RUNNING, STOPPED, DISABLED). Each group is collapsible. App entries show StatusShape + display name + optional auto badge + invocation count. Multi-instance apps have an expand chevron showing individual instances with tree connectors (`└`). Wordmark ("hassette") at top with version and connection status below it. Command palette trigger ("jump to... Ctrl+K") between wordmark and nav.

**Mobile layout** (below 900px) — sidebar hides; hamburger button (top-left, 44px) opens an off-canvas drawer that slides in from the left with the full sidebar content. Backdrop overlay for dismissal. Main content gets top padding to clear the hamburger. The 900px threshold was chosen to eliminate the 769-900px dead zone where the sidebar consumed too much of the viewport. General mobile layout changes (grid stacking, compact tables, touch targets) still trigger at 768px.

**StatusBar** — horizontal bar at top of main content area. Left side: TimePresetSelector (Since restart / 1h / 24h / 7d with uptime label). Right side: WebSocket indicator (pulse dot + label when not connected), telemetry degraded indicator, dropped events indicator, error handler failures indicator, theme toggle (sun/moon icon).

**Command Palette** — modal overlay triggered by Cmd+K / Ctrl+K. Search input with fuzzy matching. Items categorized: pages (overview, logs, config), apps (navigate to app), instances (for multi-instance apps), handlers (navigate to app's handler), actions (reload/stop apps). Each item shows StatusShape, label, sub-label, and optional status. Keyboard navigation with highlighted selection.

### Overview (Dashboard)

**Greeting header** — time-of-day greeting ("Good morning." / "Good afternoon." / "Good evening.") in Newsreader display size. Metadata line showing app count and runs/hr. Subtitle with system state description in plain language.

**System state detection** — five states influence the greeting subtitle and page emphasis:
- `first_install` — no apps loaded
- `healthy` — all apps running
- `quiet` — apps running but zero activity; activity card shows "0 runs / hour" with explanation
- `single_failure` — one app failing
- `multiple_failures` — 2+ apps failing

**Stats strip** — 3-cell horizontal strip showing handlers count, invocations count, success rate. Hidden when system is quiet. Mono font for values, micro uppercase for labels.

**Framework error banner** — appears when hassette started with boot issues (errors/warnings). Shows count, top issue label + detail, link to config page.

**Summary cards** — 3-column grid:
- *Your apps* — list of all apps sorted by activity, each with StatusShape + name + run count. Links to app detail.
- *Activity* — big number (total runs), time label, sparkline (SVG polyline), ok/err breakdown with StatusShapes.
- *System* — list of internal services (event stream, database, bus, scheduler, etc.) each with StatusShape + humanized name + status.

**Recent errors table** — card with `--err-bg` top border. Header with tier filter toggle (All / Apps / Framework). Table columns: TIME, APP, LOCATION, EXCEPTION, AGE. Supports stale-data display during refetch (opacity fade). Hidden when no errors.

**Recent activity feed** — receded card showing latest handler invocations. Each row: StatusShape + timestamp + app.handler label + duration or error type. "Quiet hour" empty state when no activity. Link to full log.

### Apps Page

**Page header** — "apps" in Newsreader h1.

**Stats strip** — 7-cell grid: Total, Running, Failed, Stopped, Disabled, Handlers, Runs/hr. Status-colored values (running count in green, failed in red).

**Status filter** — pill toggle row: all (with count), running (with count), disabled (with count). Active pill uses accent styling.

**Search** — text input, right-aligned, filters by app name or key.

**App table** — sortable columns: APP (StatusShape + display name + class name), STATUS (badge), LAST ERROR, RUNS (count + sparkline), LAST FIRED, ACTIONS (reload/stop icons). Multi-instance apps show expand chevron with instance count. Mobile hides columns 3+ and class names.

### App Detail

**Breadcrumb** — "Apps / app_key" with link back.

**Header** — StatusShape + app_key in h1. Meta line: file path, class name. Reload and Stop action buttons (top-right). Error display card when app has recent error (shows error type, message, link to traceback).

**Tab bar** — handlers (with count), code, logs, config. Underline-style active indicator.

**Health strip** — 4-5 cell KPI row: Handlers, Invocations (with time scope), Success Rate, Failed, Timed Out. Mono values, micro uppercase labels.

**Handlers tab** — two-panel layout. Left: handler/job list. Each row shows StatusShape + type badge (event/interval/after/cron) + handler name + meta (entity pattern, schedule, run count). Right: detail panel for selected handler showing invocation/execution history table.

**Code tab** — syntax-highlighted Python source with line numbers. Horizontal scroll for long lines.

**Logs tab** — filtered log table scoped to this app. Same columns as the main logs page.

**Config tab** — key-value table showing the app's resolved configuration.

### Logs Page

**Page header** — "logs" in Newsreader h1.

**Toolbar** — entry count (left). Right side: tier filter (All / Apps / Framework), live toggle (green dot + "live"), level filter (INFO+), app filter dropdown, search input.

**Log table** — columns: Level (StatusShape + label), Timestamp, App, SOURCE (handler name + file:line), Message. Sortable. Alternating row backgrounds for warnings. Expandable message cells for truncated content. Mobile hides non-essential columns.

### Config Page

**Page header** — "config" in Newsreader h1.

**Grouped key-value tables** — sections: General, Connection, Buffers, Timeouts, Scheduler, Paths, Database, Features. Each section has an h2 heading. Two-column table: key (mono) and value (mono). No editing — read-only config viewer.

### Handlers Page (`/handlers`)

**Page header** — "handlers" in Newsreader display size.

**Toolbar** — tier filter (All / Apps / Framework), app filter dropdown (all apps or a specific app key), search input. Defaults to app-tier only; toggling includes framework-tier items.

**Unified table** — handlers and jobs in a single sortable table. Sortable columns: TYPE (event/job badge), APP, NAME, TRIGGER, RUNS, FAILED, TIMED OUT, ERROR RATE, AVG, NEXT RUN. Rows link to app detail with handler focused. The TYPE column distinguishes handlers from jobs; columns that don't apply to a row show "—" (e.g., handlers have no NEXT RUN, jobs with zero runs show "—" for AVG). Header shows combined counts ("19 handlers · 14 jobs"). Empty state: "no handlers found."

Cancelled jobs are filtered at the backend (SQL `WHERE sj.cancelled_at IS NULL`). The STATUS column was removed — all returned jobs are active by definition.

Data sources: `GET /api/bus/listeners` and `GET /api/scheduler/jobs`.

### Diagnostics Page (`/diagnostics`)

**Page header** — "diagnostics" in Newsreader display size.

**Services panel** — two-phase initialization: seeded from `GET /api/health` on mount (returns `ServiceInfoResponse` with `name`, `status`, `role`, `ready_phase`, `retry_at`), then live WS `service_status` broadcasts overlay keyed by `resource_name`. Displays each service as a row: StatusShape + resource_name (mono, bold) + role (mono, muted) + status (mono) + optional ready_phase (italic). Services in `exhausted_cooling` state show a relative retry timestamp ("retry in 3m") that refreshes as the WS signal updates. Services with exceptions show a "show exception" toggle revealing a `<pre>` block. When WS is disconnected, a "stale" badge appears in the panel header. Empty state: "No services registered."

**Boot issues panel** — reads from the same `GET /api/health` response (shared fetch). Issues sorted by severity (errors first). Each row: StatusShape (err/warn) + label (bold) + detail text below. Empty state: "Clean startup — no issues."

**Telemetry health panel** — reads from `useAppState()` signals populated by the global 30s `useTelemetryHealth` poller (no additional fetch). Shows a degraded banner when `telemetryDegraded` is true. Displays per-category drop counters: Buffer overflow, Write failed, No session, During shutdown, Error handler failures — each as a label/count row. When all counters are zero: "No telemetry drops."

Data sources: `GET /api/health` (services + boot issues), `useAppState()` signals (drop counters).

### Shared Components

**StatusBadge** — two variants:
- Full: pill with dot + label (`ht-status-badge--{variant}`)
- Small: compact pill (`ht-badge--sm ht-badge--{variant}`)

**StatusShape** — inline SVG combining shape + color for colorblind accessibility:
- ok: filled circle (green)
- warn: filled triangle (amber)
- err: filled square (red)
- mute: outline circle (grey)

**Spinner** — loading indicator for initial page loads.

**ConfirmDialog** — modal for destructive actions (stop app). Dark overlay, card with title + message + cancel/confirm buttons. Danger variant uses `--err` confirm button.

**AlertBanner** — dismissible banner at top of main content showing failed app names with error messages. Uses `--err-bg` background.

**LogTable** — reusable log viewer with level filtering, sorting, and expandable message cells. Used on the main logs page and per-app logs tab.

**ShowMoreButton** — "show more" trigger for expanding truncated lists.

**ActionButtons** — reload/stop icon buttons with loading states and confirmation flow.

### Anti-patterns

- **No `--ht-*` prefixed tokens** — the old Graphite+Emerald system is replaced; all tokens are unprefixed Ink tokens
- **No raw hex values in component CSS** — always reference tokens
- **No sidebar icons** — text-only nav is intentional, not a gap
- **No shadows for card depth** — borders are the primary mechanism; shadows for floating surfaces only
- **No blue/indigo/violet accent** — light mode accent is `ink-1`; dark mode uses restrained periwinkle
- **No card nesting** — handler rows are list items in bordered containers, not cards inside cards
- **No bounce/elastic easing** — all transitions use `--ease`
- **No status colors on non-status elements** — `--ok` / `--warn` / `--err` reserved for state communication only
- **No left-border accents** — use indentation, spacing, or weight instead
- **No emoji** — not in UI copy, not in error messages, not anywhere
- **No skeleton loaders** — use spinner or stale-data-with-opacity
- **No bottom navigation on mobile** — hamburger + off-canvas drawer pattern

## Open Questions

- **Logo / wordmark** — currently text-only ("hassette" in Newsreader). Real mark deferred.
- **Empty states** — empty states for no logs matching filter, no handlers, sessions page need treatment.
