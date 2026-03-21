# Research Brief: Hassette Web UI Redesign

**Date**: 2026-03-19
**Status**: Ready for Decision
**Proposal**: Full visual and architectural redesign of the Hassette monitoring/admin web UI
**Initiated by**: User dissatisfaction with current UI -- "not intuitive, not clear, doesn't fit the vibe, isn't consistent, don't like the colors, doesn't look well considered"

## Context

### What prompted this

The current UI was built incrementally: first as a Bulma-based proof of concept (#233), then made responsive (#246), then migrated from Bulma to a custom design system (#262). Each wave addressed immediate needs but the result is a UI that feels assembled rather than designed. The user wants to start fresh visually and is open to changing the tech stack entirely.

This is the first impression for anyone who installs Hassette. It ships as part of the framework, not as a separate product.

### Current state

**Tech stack**: Jinja2 templates + HTMX (v2.0.4) + Alpine.js (v3.14.8) + custom CSS (no framework) + Font Awesome icons + vanilla JS (3 files). All served from FastAPI via `StaticFiles`. No build step.

**Template structure**: 56 HTML files total -- 7 pages, 16 partials, 3 components, 1 macro file, 1 base layout. ~970 lines of template HTML. Pages extend `base.html`; partials are HTML fragments returned by HTMX endpoints.

**CSS**: 1,093 lines in `style.css` + 134 lines in `tokens.css`. All custom, using `ht-` prefix. Design token system with CSS custom properties. Borders-only depth strategy (no shadows). Slate/amber color palette.

**JavaScript**: 452 lines across 3 files. `ws-handler.js` (Alpine store for WebSocket), `live-updates.js` (debounced HTMX partial refresh on WS events), `log-table.js` (Alpine component for log viewer with filtering/sorting). JSDoc typed, linted.

**Live updates**: WebSocket pushes `app_status_changed`, `state_changed`, `log`, and `dev_reload` events. `data-live-on-app` and `data-live-on-state` attributes on DOM elements trigger debounced HTMX partial refreshes (500ms). Logs stream in real-time via WS subscription. CSS hot-reload via `dev_reload` message.

**Data sources**: `RuntimeQueryService` (in-memory -- app manifests, recent logs, recent events), `TelemetryQueryService` (SQLite -- listener metrics, execution history), `SchedulerService` (in-memory -- active jobs, next run times). Two identity models: `owner_id` (runtime) vs `app_key + instance_index` (DB/API).

**Pages**:
- Dashboard: app status chips, recent logs (30), activity timeline (20 events)
- Apps: manifest table with status filter tabs, expandable instance rows
- App Detail: metadata, bus listeners, scheduled jobs, logs (per-instance)
- Scheduler: jobs table + execution history table (history currently empty/stubbed)
- Bus: listeners table with expandable detail panels
- Logs: full log viewer with level/app/search filters, sortable columns, WS streaming

**E2E tests**: 8 Playwright test files covering navigation, dashboard, apps, bus, scheduler, logs, hot reload, and WebSocket. Run with `pytest -m e2e`.

### Key constraints

- **No Node.js build step strongly preferred** -- the project uses `uv` for Python packaging and has no JS toolchain
- **Embedded admin panel** -- not a standalone product; bundle size and complexity matter
- **Developer audience** -- technical users comfortable with code, checking dashboards between tasks
- **Python ecosystem fit** -- must integrate naturally with FastAPI, Jinja2 (or replacement), and the existing backend
- **Issue #268 pending features** -- handler invocation drill-down, session list, current-vs-all-time toggle, source code display. These need to be accommodated in the new IA
- **Open bugs** -- #236 (scheduler summary duplication), #338 (missing instance_index filter), #263 (log_table macro too large)

## Prior Art Summary

### Home Assistant Frontend

**Architecture**: Lit-based web components with unidirectional data flow. The `hass` object (all entity state) propagates from root to every component. Material Design components. WebSocket API for state updates.

**What to learn**: The entity more-info dialog pattern -- click any entity to drill into state, history, and settings -- is exactly the interaction model Hassette needs for listeners and jobs (click to see invocation history). HA's card-based dashboard composition lets users customize layout, but Hassette's admin panel should be opinionated (one good layout, not customizable).

**What to avoid**: HA's frontend is a full SPA with a heavy build system (Rollup, Lit, Material Web). Overkill for an embedded admin panel.

### AppDaemon (HADashboard)

**Architecture**: Server-rendered dashboards optimized for wall-mounted tablets. Widget-based layout with pre-compilation. Python backend generates HTML.

**What to learn**: AppDaemon's dashboard is purely for *display*, not administration. Hassette needs both monitoring and control (start/stop/reload). AppDaemon's approach of pre-compiling dashboards is interesting for performance but not directly applicable.

**What to avoid**: The tablet-first, wall-mounted design philosophy. Hassette is a developer tool used at a desk, not a glanceable display.

### Node-RED

**Architecture**: AngularJS SPA (Dashboard 1.0) or Vue.js (Dashboard 2.0). Socket.IO for real-time updates. Sidebar with debug panel, info tab, and config tabs.

**What to learn**: The sidebar debug panel is the killer feature -- a persistent, always-visible log stream alongside the main workspace. Hassette could benefit from a persistent log tail or activity feed that stays visible across page navigation instead of being buried on a dedicated page. The hierarchical page > group > widget information architecture is clean. Navigation sidebar with "Collapsing" mode matches Hassette's current icon-rail pattern.

**What to avoid**: The complexity of two major framework versions. Node-RED's dashboard is for building end-user UIs, not monitoring automation internals.

### Apache Airflow

**Architecture**: React-based SPA (Airflow 3), with Grid View, Graph View, and task instance detail. Dark/light theme support.

**What to learn**: Airflow 3's information hierarchy is the closest model for Hassette:
1. **Home/Dashboard** -- high-level system overview with status widgets
2. **DAGs list** (= Apps list) -- filterable, sortable table with status badges
3. **DAG detail** (= App detail) -- tabs for graph view, grid view, task list
4. **Task instance detail** (= Listener/Job detail) -- execution history, logs, metadata

The Grid View pattern -- a matrix of task instances over time -- is compelling for showing listener invocation patterns over time. The "Runs" concept maps directly to Hassette's "Sessions".

**What to avoid**: Full React SPA complexity. Airflow serves a much broader audience and has dedicated frontend engineers.

### Celery Flower

**Architecture**: Tornado-based server, real-time monitoring via Celery Events. Dashboard with worker status, active/completed tasks, graphs.

**What to learn**: Flower's information density is high but scannable. The three-panel layout (workers | tasks | graphs) lets you see system health at a glance. Task detail shows arguments, result, runtime, and state transitions -- good model for Hassette's invocation drill-down. The "worker status" concept maps to Hassette's app status.

**What to avoid**: Flower's UI is dated (Bootstrap 3 era) and hasn't had a major redesign. Not a visual inspiration.

### Grafana

**Architecture**: React SPA with plugin architecture. Panel-based dashboard composition.

**What to learn**: Grafana's dashboard best practices are directly applicable:
- Logical progression: large to small, general to specific
- Consistent visualization types reduce cognitive load
- The RED method layout (rate/errors/duration) is a natural fit for Hassette's listener and job metrics
- Time range controls and refresh intervals

**What to avoid**: Grafana is a general-purpose visualization tool. Hassette needs opinionated, purpose-built views, not a composable panel system.

### Synthesis: Information Hierarchy Patterns

All successful monitoring UIs follow the same drill-down pattern:
1. **System health at a glance** (dashboard/home) -- status counts, error rates, key metrics
2. **Entity list** (apps/tasks/workers) -- filterable table with status, sortable
3. **Entity detail** (app/task) -- metadata + child entities (listeners, jobs) + execution history
4. **Execution detail** (invocation/run) -- individual execution with timing, result, error details

Hassette's current UI has layers 1-3 but lacks layer 4 (invocation drill-down). Issue #268 addresses this gap.

## Tech Stack Evaluation

### Option A: Evolve Current Stack (Jinja2 + HTMX + Alpine.js + Custom CSS)

**How it works**: Keep the current rendering model but replace the visual layer entirely. New `tokens.css` and `style.css`, new component patterns, potentially new template structure. HTMX continues handling partial updates, Alpine.js handles client-side interactivity, WebSocket integration stays the same.

**Pros**:
- Zero migration cost for backend routes, partials, and WS infrastructure
- No new dependencies or build steps
- The HTMX + Alpine.js pattern is working well -- WS-driven live updates, debounced refreshes, log streaming all function correctly
- E2E tests continue to work with minimal selector updates
- The team (Jessica) already knows this stack

**Cons**:
- Custom CSS means maintaining everything from scratch -- 1,093 lines and growing
- Jinja2 macros get unwieldy at scale (see #263, the 118-line log_table macro)
- No utility classes means lots of one-off CSS for layout adjustments
- The template organization (7 pages, 16 partials, 1 macro file) is already showing strain

**Effort estimate**: Small for visual redesign; Medium if restructuring templates and CSS architecture

**Dependencies**: None new

### Option B: Jinja2 + HTMX + Alpine.js + Tailwind CSS (via standalone CLI)

**How it works**: Replace `style.css` and `tokens.css` with Tailwind utility classes, using the standalone Tailwind CLI (no Node.js). Keep Jinja2 templates, HTMX partials, Alpine.js components. A small set of custom CSS for the pulse-dot animation and any truly unique components. `pytailwindcss` or `tailwind-py` provides the pip-installable standalone binary.

Build step: `tailwindcss -i input.css -o output.css --minify` runs once at build time (or in dev mode with `--watch`). Added to the existing `nox` task runner or as a `uv run` script.

**Pros**:
- Eliminates 1,093 lines of hand-written CSS in favor of utility classes
- Responsive design is dramatically simpler (`md:`, `lg:` prefixes vs media queries)
- Tailwind's design system (spacing, colors, typography) provides a more principled foundation than hand-picked CSS custom properties
- Tailwind v4 has zero-config mode and CSS-native configuration -- minimal setup
- The standalone CLI avoids Node.js entirely; `pytailwindcss` is pip-installable
- JIT mode means only used classes are in the output CSS -- tiny bundle
- Templates become self-documenting (layout is visible in the HTML)

**Cons**:
- Adds a build step (standalone CLI binary, ~15MB) -- even if it is not Node.js, it is a binary dependency
- Long class strings in templates can reduce readability of Jinja2 logic
- Tailwind v4 standalone CLI is newer and less battle-tested than the npm version
- Need to add the Tailwind build to CI, nox, and dev-server hot-reload
- Existing E2E tests that select by CSS class would need updating

**Effort estimate**: Medium -- CSS rewrite + build step integration + template updates

**Dependencies**: `pytailwindcss` or `tailwind-py` (dev dependency), Tailwind standalone CLI binary

### Option C: Pico CSS (Minimal Semantic Framework)

**How it works**: Replace custom CSS with Pico CSS, which styles semantic HTML elements directly (tables, buttons, forms) with minimal class usage. Add a thin custom layer for Hassette-specific components (pulse dot, app chips, detail panels).

**Pros**:
- CDN-loadable, no build step at all
- ~13KB gzipped -- much smaller than Tailwind output
- Semantic HTML approach means templates are cleaner (fewer classes)
- Dark/light theme support built in
- Good typography and spacing defaults

**Cons**:
- Limited component vocabulary -- no utility classes for custom layouts
- Still need custom CSS for anything beyond basic elements (which is most of the UI)
- Less community adoption than Tailwind for admin UIs
- Customization requires SASS or overriding CSS custom properties
- May end up writing almost as much custom CSS as today, just on top of Pico instead of from scratch

**Effort estimate**: Medium -- similar to Option A since most unique components still need custom CSS

**Dependencies**: Pico CSS (CDN or vendored)

### Option D: Lightweight SPA (Preact/Solid)

**How it works**: Replace Jinja2 templates with a Preact or Solid.js SPA served as static assets from FastAPI. Components render client-side. API endpoints remain the same. WebSocket integration moves from HTMX partials to component state.

**Pros**:
- True component model with proper encapsulation
- TypeScript support for type-safe templates
- Better handling of complex interactive views (drill-down, time-range controls, sortable/filterable tables)
- Easier to build issue #268 features (invocation drill-down, session switching)

**Cons**:
- Requires a JS build step (esbuild/Vite) -- directly contradicts the "no Node.js" preference
- Abandons the working HTMX partial infrastructure
- All E2E tests would need rewriting
- Increased bundle size and load time
- Moves complexity from server (Jinja2) to client (component framework)
- Over-engineered for the current scope -- 7 pages, mostly tables and lists

**Effort estimate**: Large -- full rewrite of rendering layer, WS integration, E2E tests

**Dependencies**: Preact or Solid.js, esbuild or Vite, potentially a component library

### Recommendation: Option B (Tailwind CSS via standalone CLI)

Option B provides the best balance: it addresses the root cause of CSS maintenance pain, gives a principled design foundation, avoids Node.js, and preserves the working HTMX/Alpine.js/WebSocket infrastructure. The build step is minimal (one binary, one command) and integrates naturally with nox.

Option A is viable but leaves the CSS maintenance burden in place. Option C doesn't solve enough. Option D solves problems the project doesn't have yet.

## Information Architecture Proposal

Based on the data model, pending features (issue #268), and lessons from prior art, here is a proposed page structure:

### Proposed Navigation

```
Dashboard          -- system health at a glance
Apps               -- app list with status filtering
  App Detail       -- per-app/instance detail with tabs
Sessions           -- NEW: session list (from #268)
Logs               -- full log viewer
```

### Key Changes from Current Structure

**1. Merge Bus and Scheduler into App Detail**

Currently, Bus and Scheduler are top-level pages that show data across all apps. But the primary use case is "what is *this app* doing?" -- not "show me all listeners globally." The data already exists at the app level (`app_instance_detail.html` shows listeners and jobs per app).

Proposed: Remove standalone Bus and Scheduler pages. App Detail becomes the primary drill-down point with tabs:
- **Overview** -- status, metadata, error display (current top section)
- **Listeners** -- bus listeners with invocation counts and drill-down (currently embedded)
- **Jobs** -- scheduled jobs with execution history and drill-down (currently embedded)
- **Logs** -- app-scoped log viewer (currently embedded)

Global cross-app views for listeners and jobs become filter options within the App Detail or accessible from the dashboard via "all listeners" / "all jobs" links.

**2. Add Session page (issue #268)**

A new page showing all sessions with start time, duration, status, error info. Clicking a session scopes the dashboard to that session's data. The "current session vs all-time toggle" from #268 becomes a session selector.

**3. Restructure Dashboard**

Current dashboard: app chips + recent logs + activity timeline. This is too sparse and doesn't leverage the telemetry data now available in SQLite.

Proposed dashboard sections:
- **System Status** -- app status summary (running/failed/stopped counts), WS connection, uptime, current session info
- **Apps** -- compact status grid (current app chips, but with error indicators)
- **Recent Activity** -- merged timeline of listener invocations and job executions (not raw HA events, which are noisy)
- **Error Summary** -- recent errors across all handlers and jobs (from #268 error drill-down query)
- **Quick Stats** -- total invocations, error rate, avg duration (from global summary queries in prereq-04)

**4. Listener/Job Invocation Drill-Down (issue #268)**

Click a listener row to expand and see its last N invocations with status, duration, and error details. Same for jobs. This is the "layer 4" missing from the current UI. The expandable detail panel pattern already exists in `bus_listeners.html` -- extend it with an invocation history sub-table.

### Data Model Alignment

| UI Concept | Data Source | Service |
|---|---|---|
| App status, manifests | In-memory | RuntimeQueryService |
| Listener registration metadata | SQLite `listeners` table | TelemetryQueryService |
| Listener invocation history | SQLite `handler_invocations` table | TelemetryQueryService |
| Job registration metadata | SQLite `scheduled_jobs` table | TelemetryQueryService |
| Job execution history | SQLite `job_executions` table | TelemetryQueryService |
| Job next_run, cancelled | In-memory scheduler heap | SchedulerService |
| Sessions | SQLite `sessions` table | TelemetryQueryService |
| Recent logs | In-memory ring buffer | RuntimeQueryService |
| Recent events | In-memory event buffer | RuntimeQueryService |

## Lessons Learned from History

### Pattern 1: Identity model confusion causes cascading bugs

Issues #335, #336, and audit findings #1 and #2 all stem from the dual identity model (`owner_id` vs `app_key + instance_index`). The web UI has been the primary place where this confusion manifests -- filters that accept `app_key` but need `owner_id` to match scheduler jobs, partials that hardcode `instance_index=0`.

**Implication for redesign**: The new UI should consistently use `app_key + instance_index` as the addressing scheme for all views. Backend query services should accept these parameters and handle the `owner_id` translation internally. Templates should never deal with `owner_id`.

### Pattern 2: Macro sprawl in templates

Issue #263 identifies the 118-line `log_table` macro as a maintenance problem. The macro combines filter controls, table markup, Alpine.js component wiring, and WebSocket subscription logic in a single block. More macros like this would make the system unmaintainable.

**Implication for redesign**: Instead of Jinja2 macros for complex interactive components, use Alpine.js components (like the existing `logTable` pattern in `log-table.js`) paired with simpler template includes. Keep macros for purely presentational helpers (status badges, formatted values).

### Pattern 3: Live update plumbing works well

The `data-live-on-app` / `data-live-on-state` attribute pattern with debounced HTMX refreshes via `live-updates.js` is elegant and reliable. The idiomorph swap strategy prevents unnecessary DOM mutations. This infrastructure should carry forward unchanged.

### Pattern 4: Partials architecture is sound but growing

16 partials, each with a dedicated route, is already a lot of routing boilerplate. Adding invocation drill-down, session views, and dashboard cards will roughly double this. The partial + route pattern is correct but needs better organization (e.g., grouping partial routes by feature area instead of one flat file).

### Pattern 5: UI work generates bugs at the boundary

Most UI bugs (#236, #247, #338) occur at the boundary between backend data and template rendering -- wrong filters, missing parameters, incorrect data shapes. The redesign should add more integration tests that verify partial responses contain the expected data for multi-instance apps.

### Pattern 6: CSS was rewritten once already

The Bulma-to-custom migration (#262) was a significant effort. Doing another CSS rewrite is viable *because* the custom system is well-organized with tokens, but the lesson is: pick a foundation that won't need replacing again. This argues for Tailwind (large ecosystem, stable, widely adopted) over another custom system.

## Visual Direction Options

### Direction 1: "Developer Workbench" -- Warm Neutral + Indigo Accent

**Inspiration**: VS Code, Linear, Raycast

**Palette**: Warm stone/zinc neutrals (not the current cool slate) with an indigo/violet accent color. Light mode default with a dark mode option.

**Typography**: Keep Space Grotesk for headings (it has genuine character). Keep JetBrains Mono for code/data. Consider Inter or system-ui for body text (the current system-ui stack is fine).

**Depth strategy**: Subtle shadows (not borders-only). The borders-only approach makes the UI feel flat and cheap at low information density. A single `shadow-sm` on cards adds dimensionality without being "generic SaaS."

**Signature element**: Keep the pulse-dot concept but make it indigo instead of amber. The breathing animation is genuinely distinctive.

**Character**: Refined, professional, tool-you-trust. Not flashy, not austere. Think "well-made instrument" rather than "control room."

### Direction 2: "Observability Console" -- Dark-First + Emerald Accent

**Inspiration**: Grafana, Datadog, Vercel dashboard

**Palette**: Dark zinc/slate background by default with an emerald/green accent for success states and a warm amber for warnings. Light mode as secondary option.

**Typography**: JetBrains Mono used more prominently (not just for code, but for data labels and small text). Gives a more "operations console" feel. Space Grotesk for page titles only.

**Depth strategy**: Surface elevation via background color shifts (darker = deeper). Subtle borders where surfaces meet. Dark UIs naturally create depth through luminance.

**Signature element**: Pulse-dot in emerald green (the color of "all systems go"). Red static dot for disconnected.

**Character**: Dense, information-rich, monitoring-first. Designed for the user who keeps this open on a second monitor. Emphasizes data over chrome.

### Direction 3: "Clean Admin" -- Light + Teal Accent

**Inspiration**: Tailwind UI, shadcn/ui, Home Assistant

**Palette**: True white cards on a very light gray canvas. Teal/cyan accent for interactive elements and active states. Gray-700 for text.

**Typography**: System font stack for everything except code (JetBrains Mono). Clean, invisible typography that lets the data speak.

**Depth strategy**: Combination of subtle borders and very light shadows. Rounded corners (8px) on cards. More whitespace than the current design.

**Signature element**: Pulse-dot in teal. Consider a small animated status bar or connection indicator instead of a dot.

**Character**: Approachable, modern, well-organized. Less "developer tool" and more "well-designed product." This direction would give Hassette the strongest first impression for new users browsing the docs or trying the framework.

## Design System Carry-Forward

### Keep

- **Space Grotesk** for headings -- it has genuine typographic character that distinguishes Hassette from generic admin panels
- **JetBrains Mono** for code/data -- excellent for tabular data and entity IDs
- **Pulse-dot concept** -- the breathing WebSocket indicator is a genuine signature element that no other HA tool has. Change the color, keep the animation
- **`ht-` class prefix** -- maintains namespace isolation, prevents conflicts
- **CSS custom properties for theming** -- the token architecture is sound regardless of whether Tailwind is adopted (Tailwind v4 uses CSS custom properties natively)
- **4px spacing grid** -- consistent and well-established in the current system
- **Border-radius values** -- the current scale (3/5/8/9999px) is reasonable

### Rethink

- **Color palette** -- the slate/amber combination is the primary complaint. All three visual directions propose a different accent color. The new palette should be chosen during the design phase with actual mockups
- **Borders-only depth strategy** -- this was an intentional rejection of Bulma's shadow-heavy approach, but it went too far. Cards need *some* dimensionality. Consider `shadow-sm` + border, or surface color differentiation
- **Dark sidebar** -- a dark sidebar on a light page creates high contrast that fights for attention. Consider a light sidebar or a full dark mode instead of a mixed approach
- **Font Awesome** -- the icon library is loaded from CDN (115KB+ CSS). Consider Lucide or Heroicons (SVG, tree-shakeable, no CDN dependency). Tailwind-ecosystem projects typically use Heroicons
- **Type scale** -- the current scale (12/13/14/16/20/24px) is slightly too compressed. Consider a wider scale with more differentiation between body and heading sizes
- **Status badge colors** -- the semantic color mapping (green=running, red=failed, yellow=stopped) is correct but the palette values should align with the new accent color
- **`hx-on::after-request` for tab switching** -- the inline JS expressions in the apps page tabs are fragile (see lines 21-55 of `apps.html`). This pattern should be replaced with Alpine.js state management

### Drop

- **Bulma-era naming conventions** -- `.is-active` is the only remnant; should become `ht-active` for consistency
- **`--ht-surface-inset`** -- overloaded token used for both alert items and nested panels. Replace with purpose-specific tokens
- **The "control room" metaphor** -- the user explicitly doesn't want this. The design system document's "Feel" section needs rewriting

## Concerns

### Technical risks

- **Tailwind standalone CLI stability** -- Tailwind v4's standalone CLI is production-ready but newer than the npm version. If issues arise, `pytailwindcss` pins to a specific binary version. Mitigation: vendor the binary or pin the version in CI
- **Build step in CI** -- adding the Tailwind build to the nox/pytest pipeline requires the standalone binary to be available. Can be handled via a nox session that downloads it, similar to how `playwright install` works

### Complexity risks

- **Information architecture change** -- merging Bus and Scheduler into App Detail removes two top-level pages that some users may navigate to directly. If the "all listeners across apps" view is still needed (likely), it needs a home -- perhaps as a filter mode on the Apps page or a dashboard widget
- **Session scoping** -- the "current session vs all-time" toggle adds a global state dimension that affects multiple pages. This needs careful design to avoid confusion

### Maintenance risks

- **Tailwind upgrade path** -- Tailwind v4 is a major version change from v3 with a new configuration model. If the project starts on v4, it should be straightforward, but tracking Tailwind major versions adds a maintenance surface
- **E2E test updates** -- changing CSS classes requires updating Playwright selectors. The current tests use semantic selectors (text content, ARIA labels) where possible, but some use class-based selectors

## Open Questions

- [ ] Which visual direction resonates? (Warm Neutral, Dark Console, or Clean Admin) -- this fundamentally shapes every subsequent design decision
- [ ] Should Bus and Scheduler remain as top-level pages, or merge into App Detail? The data model supports either; the question is navigation preference
- [ ] Is the "no Node.js build step" constraint absolute, or is a standalone binary (Tailwind CLI) acceptable? This determines whether Option B is viable
- [ ] How important is dark mode? Direction 2 is dark-first; Directions 1 and 3 are light-first with dark mode optional. Building both doubles the design surface
- [ ] Should the redesign happen incrementally (page by page) or as a single big-bang rewrite? Incremental preserves E2E test coverage at each step; big-bang avoids a mixed UI
- [ ] Is there a target timeline? The redesign could range from 1-2 weeks (visual refresh only) to 4-6 weeks (IA restructure + visual + new features from #268)

## Recommendation

**Do the redesign in two phases, not one.**

**Phase 1: Visual refresh + CSS migration (2-3 weeks)**

Adopt Tailwind CSS via standalone CLI. Replace `tokens.css` and `style.css` with Tailwind utility classes plus a small custom layer for Hassette-specific components (pulse-dot, app chips). Choose a visual direction and implement it. Keep the current page structure, template architecture, and all HTMX/Alpine.js/WebSocket infrastructure unchanged. This is a CSS-layer rewrite, not a structural change.

Deliverables: New color palette, new component styling, responsive improvements, icon library swap. All existing E2E tests pass (with updated selectors).

This phase gives immediate visual improvement and validates the Tailwind integration before tackling structural changes.

**Phase 2: Information architecture restructure (2-3 weeks, after Phase 1)**

Restructure pages around the drill-down model: Dashboard > Apps > App Detail (with tabs) > Invocation Detail. Add Session page. Implement pending #268 features (invocation drill-down, session list, current/all-time toggle). This phase changes templates, adds new partials and routes, and adds new E2E tests.

This ordering matters because:
1. Phase 1 is lower risk and delivers visible improvement immediately
2. Phase 2 requires design decisions (IA, new page layouts) that benefit from having the visual foundation in place
3. If Phase 2 is delayed or deprioritized, Phase 1 still stands on its own

### Suggested next steps

1. **Run `/mine.design`** to produce a design doc for Phase 1 -- visual direction choice, Tailwind integration plan, component inventory
2. **Create an HTML mockup** of the chosen visual direction for 2-3 key pages (dashboard, app detail, logs) using Tailwind Play CDN -- this validates the visual direction before committing to implementation
3. **Prototype Tailwind standalone CLI integration** in a branch -- verify it works with nox, dev-server hot-reload, and CI before the full migration
4. **File issues** for Phase 1 (CSS migration, icon swap, palette change) and Phase 2 (IA restructure, #268 features) separately

## Sources

- [Home Assistant Frontend Architecture](https://developers.home-assistant.io/docs/frontend/architecture/)
- [Home Assistant Entity System and State Display](https://deepwiki.com/home-assistant/frontend/6-entity-system-and-state-display)
- [AppDaemon Documentation](https://appdaemon.readthedocs.io/en/latest/)
- [Node-RED Dashboard 2.0 Layout and Navigation](https://flowfuse.com/blog/2024/05/node-red-dashboard-2-layout-navigation-styling/)
- [Node-RED Sidebar Documentation](https://nodered.org/docs/user-guide/editor/sidebar/)
- [Airflow 3 UI Overview](https://airflow.apache.org/docs/apache-airflow/stable/ui.html)
- [Airflow UI Introduction - Astronomer](https://www.astronomer.io/docs/learn/airflow-ui)
- [Celery Flower Documentation](http://mher.github.io/flower/)
- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/)
- [Tailwind CSS Standalone CLI](https://tailwindcss.com/docs/installation/tailwind-cli)
- [pytailwindcss - PyPI](https://pypi.org/project/pytailwindcss/)
- [tailwind-py - PyPI](https://pypi.org/project/tailwind-py/)
- [Pico CSS](https://picocss.com)
- [FastAPI + Tailwind CSS Setup](https://github.com/handreassa/fastapi-tailwindcss-admin)
