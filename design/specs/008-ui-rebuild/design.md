# Design: UI Rebuild

**Date:** 2026-03-19
**Status:** approved
**Spec:** design/specs/008-ui-rebuild/spec.md
**Research:** design/research/2026-03-19-ui-redesign/
**Direction:** design/direction.md
**Critique:** design/critiques/2026-03-19-ui-redesign/critique.md

## Problem

The Hassette web UI was built incrementally through three waves (Bulma POC, responsive pass, custom design system migration). The result is an interface that mirrors backend services instead of user tasks, has no invocation history despite the data existing in SQLite, uses a visual direction the user rejected ("not intuitive, not clear, doesn't fit the vibe"), and generates cascading bugs at the data/template boundary (identity model confusion, hardcoded instance indices).

The user arrives with a diagnostic question — "why didn't my garage door handler fire?" — and the current UI cannot answer it. The mockups validated during this session demonstrate what can: information-dense handler rows with invocation history, expandable drill-down, plain-language summaries, and a Graphite + Emerald visual identity.

This is a big-bang rewrite. All templates, CSS, JS, routes, and E2E tests are replaced. The API layer (`routes/`) and dependency injection (`dependencies.py`) are preserved.

### Deployment strategy

Work on a feature branch. The old UI continues serving on `main` until the rebuild is merged. The rebuild PR is one atomic merge when all pages and E2E tests pass. The user's homelab instance stays on `main` during development — no broken production UI.

Minimum viable milestone (merge-ready): Dashboard + App Detail + Apps list + Logs + navigation + E2E tests for all four pages. Deferred-feature placeholders (501 endpoints) are included but not blocking.

## Non-Goals

- **Event payload storage** — the `handler_invocations` table does not store trigger data. Adding a `trigger_data` column requires a schema migration. **Template extension point:** The `handler_invocations.html` partial includes a `<div class="invocation__payload" data-testid="invocation-payload">` element that is hidden (`x-show="false"`) with an `hx-get` pointing to a future `/ui/partials/invocation-payload/{invocation_id}` endpoint. When the backend adds `trigger_data`, the partial returns content and the `x-show` condition checks for it.
- **App initialization timestamps** — `AppManifestInfo` has no `initialized_at` field. **Template extension point:** The health strip's "Init Status" card renders `status` (running/failed/stopped) instead of "Ready / 142ms". When `initialized_at` is added to the manifest, the card switches to showing the duration. The template checks: `{% if manifest.initialized_at %}{{ manifest.initialized_at | duration }}{% else %}{{ manifest.status }}{% endif %}`.
- **Runtime log level control** — needs an API endpoint. **Template extension point:** The log level toggle buttons exist in the controls area with `hx-post="/api/apps/{{ app_key }}/log-level"` and `hx-vals='{"level": "DEBUG"}'`. The endpoint returns 501 until implemented. Buttons are visually present but show a tooltip "Coming soon" on hover.
- **App enable/disable toggle** — needs config persistence. **Template extension point:** A toggle switch in the app header area with `hx-post="/api/apps/{{ app_key }}/enabled"`. Returns 501 until implemented. Disabled state: toggle is grayed with "Coming soon" tooltip.
- **Manual job trigger** — needs a permission model. **Template extension point:** Each job row includes a "Run now" button (`hx-post="/api/scheduler/jobs/{{ job_id }}/trigger"`). Returns 501 until implemented. Button is present but visually subdued with "Coming soon" tooltip.
- **Error rate sparklines** — needs a time-series rendering approach. Show numeric error rate for now.
- **Cross-app global views** — the user confirmed these are "almost never" needed. No standalone Bus or Scheduler page. If a cross-app view is needed later, it can be a dashboard panel.
- **Tailwind CSS** — hand-written CSS with the direction.md token system. No build step.

## Architecture

### Pages (4, down from 7)

| Page | Route | Purpose | Data sources |
|------|-------|---------|-------------|
| **Dashboard** | `/` | System health at a glance. HA connection state, app health grid with error rate gradient, recent errors feed, session info. | `RuntimeQueryService.get_all_manifests_snapshot()`, `RuntimeQueryService.get_system_status()`, `TelemetryQueryService.get_recent_errors()`, `TelemetryQueryService.get_global_summary()`, `TelemetryQueryService.get_current_session_summary()` |
| **Apps** | `/apps` | App list with status filter tabs. | `RuntimeQueryService.get_all_manifests_snapshot()` |
| **App Detail** | `/apps/{app_key}` `/apps/{app_key}/{index}` | Center of gravity. Health strip, handler rows with invocation drill-down, job rows with execution history, app-scoped logs. | `RuntimeQueryService`, `TelemetryQueryService.get_listener_summary()`, `TelemetryQueryService.get_handler_invocations()`, `TelemetryQueryService.get_job_summary()`, `TelemetryQueryService.get_job_executions()`, `SchedulerService.get_all_jobs()` |
| **Logs** | `/logs` | Global log viewer with level/app/search filters. | `RuntimeQueryService.get_recent_logs()` |

**Removed:** Bus page, Scheduler page. Their data is surfaced per-app in App Detail and as aggregates on Dashboard.

### App Detail page structure (the center of gravity)

```
┌─────────────────────────────────────────────┐
│ breadcrumb: Apps / garage_proximity         │
│ Title: Garage Proximity  [Running]          │
│ Instance 0 · PID 12847 · Uptime 3d 14h     │
│                    [DEBUG|INFO|WARN] [⟳] [⏸]│
├─────────────────────────────────────────────┤
│ ┌──────────┐┌──────────┐┌──────────┐┌──────┐│
│ │Init: Ready││Err: 0.4% ││Avg: 18ms ││3m ago││
│ │142ms      ││2/483     ││p95: 45ms ││garage││
│ └──────────┘└──────────┘└──────────┘└──────┘│
├─────────────────────────────────────────────┤
│ Event Handlers (3 registered)               │
│ ┌───────────────────────────────────────────┐│
│ │● Fires when garage_door → open    47 12ms││
│ │  47 invocations · last 3m · on_garage_... ││
│ │  ┌─ Recent Invocations ──────────────┐   ││
│ │  │ ● Today 14:32  8ms  Success  ...  │   ││
│ │  │ ● Today 11:05  14ms Success  ...  │   ││
│ │  │ ● Yest  22:17  3ms  Error    ...  │   ││
│ │  │   ConnectionError: Cannot connect..│   ││
│ │  │ Registered at garage_proximity:31  │   ││
│ │  └───────────────────────────────────┘   ││
│ │● Fires when person.jessica → home 12 24ms││
│ │● Fires when garage_temp > 40°C     0   — ││
│ └───────────────────────────────────────────┘│
├─────────────────────────────────────────────┤
│ Scheduled Jobs (2 active)                   │
│ ┌───────────────────────────────────────────┐│
│ │● check_occupancy · every 5m      864 35ms││
│ │● sync_device_states · every 1h    82    3││
│ └───────────────────────────────────────────┘│
├─────────────────────────────────────────────┤
│ Logs (garage_proximity)                     │
│ [All Levels ▾] [Search...]                  │
│ 14:32:18  INFO  Garage door opened — ...    │
│ 13:00:03  ERROR sync_device_states: Time... │
│ ...                                         │
└─────────────────────────────────────────────┘
```

**Flat layout, no tabs.** Everything visible, scrollable. Information density over navigation depth.

### Data layer wiring

Six existing `TelemetryQueryService` methods need UI endpoints:

| Method | New partial route | Used by |
|--------|------------------|---------|
| `get_handler_invocations(listener_id, limit)` | `/partials/handler-invocations/{app_key}/{listener_id}` | Handler row drill-down |
| `get_job_executions(job_id, limit)` | `/partials/job-executions/{app_key}/{job_id}` | Job row drill-down |
| `get_job_summary(app_key, instance_index)` | Inline in App Detail route | Job row stats (total runs, errors, avg duration) |
| `get_recent_errors(session_id, limit)` | `/partials/recent-errors` | Dashboard error feed (session-scoped by default — shows errors from the current session, not all time) |
| `get_global_summary()` | Inline in Dashboard route | Dashboard KPI strip |
| `get_current_session_summary()` | Inline in Dashboard route | Dashboard session bar |

**No new backend work required for wiring these.** The query methods exist, the SQLite tables have the data, the methods just need route endpoints.

**Backend prerequisites (small, do early):**
1. **Predicate `summarize()` method** — add `summarize() -> str` to each predicate class in `predicates.py`. Add `human_description` column to `listeners` table (Alembic migration). Populate at registration time. See "Plain-language handler summaries" below.
2. **Typed query result models** — add Pydantic models (`ListenerSummary`, `JobSummary`, `HandlerInvocation`, `JobExecution`) in `core/` to replace the raw `dict` returns from `TelemetryQueryService._row_to_dict()`. This prevents the "column rename → silent template failure" class of bugs that the current UI suffers from. Call `model_validate()` on each row. Makes future fields (like `trigger_data: dict | None = None`) explicit in the type system.

### Plain-language handler summaries

**Problem:** `predicate_description` is currently stored as `repr(listener.predicate)` (`bus_service.py:100`). Only 3 predicate classes define custom `__repr__`. Complex predicates (`AllOf`, `AnyOf`, `Guard` wrapping a lambda) produce unstable output including memory addresses. Parsing repr at render time is brittle.

**Solution:** Add a `summarize() -> str` method to each predicate class in `predicates.py`. This returns a stable, human-readable description:
- `EntityMatches("light.kitchen")` → `"entity light.kitchen"`
- `StateTo("on")` → `"→ on"`
- `AllOf([EntityMatches("light.kitchen"), StateTo("on")])` → `"entity light.kitchen → on"`
- `Guard(lambda ...)` → `"custom condition"` (fallback for unparseable lambdas)

Populate a `human_description` field on `ListenerRegistration` at registration time by calling `predicate.summarize()`. Store it in the `listeners` table alongside `predicate_description` (which remains as a debug artifact).

The route handler combines `topic` (for entity ID extraction) and `human_description` (for the condition) into the final summary string. This lives in `ui/context.py` as `format_handler_summary()`:

```python
def format_handler_summary(listener: ListenerSummary) -> str:
    """Generate 'Fires when binary_sensor.garage_door → open' from registration metadata."""
    entity_id = extract_entity_from_topic(listener.topic)
    condition = listener.human_description or listener.predicate_description or ""
    return f"Fires when {entity_id} {condition}" if entity_id else f"Fires on {listener.topic}"
```

**Backend prerequisite:** Add `summarize()` to predicate classes and `human_description` column to `listeners` table (Alembic migration). This is a small backend change that should be done before or early in the rebuild.

### CSS architecture

Hand-written CSS with the `design/direction.md` token system. Two files:

- **`tokens.css`** — All `--ht-*` custom properties. Light mode in `[data-theme="light"]`, dark mode in `[data-theme="dark"]`. Default to dark (user preference). ~150 lines.
- **`style.css`** — All component styles referencing only token variables. No raw hex values. ~1,500-1,800 lines estimated (handler row states, responsive breakpoints, and component variants add up; dark mode tokens are separate but component styles are shared via token references).

The `ht-` prefix is retained for component class names (`ht-card`, `ht-badge`) but all token values come from direction.md. No parallel token namespace.

### Template architecture

```
templates/
├── base.html                    # Root layout: fonts, HTMX, Alpine, tokens, nav, pulse dot
├── components/
│   ├── nav.html                 # Sidebar icon rail (same-temperature)
│   ├── connection_bar.html      # HA connection status banner
│   └── status_bar.html          # Top status bar (simplified)
├── macros/
│   └── ui.html                  # handler_row, job_row, health_card, status_badge,
│                                # action_buttons, log_table
├── pages/
│   ├── dashboard.html           # KPIs + app grid + error feed
│   ├── apps.html                # Manifest list with status tabs
│   ├── app_detail.html          # Center of gravity (flat, no tabs)
│   └── logs.html                # Global log viewer
└── partials/
    ├── dashboard_app_grid.html  # App health cards
    ├── dashboard_errors.html    # Recent errors feed
    ├── app_list.html            # Manifest rows
    ├── app_health_strip.html    # 4 health KPI cards
    ├── app_handlers.html        # Handler row list
    ├── app_jobs.html            # Job row list
    ├── app_logs.html            # App-scoped log entries
    ├── handler_invocations.html # Expanded invocation history (loaded on click)
    ├── job_executions.html      # Expanded execution history (loaded on click)
    └── alert_banner.html        # Failed app alerts
```

~24 template files (down from 30, but richer content per file).

### JavaScript architecture

Three files, evolved from current:

- **`ws-handler.js`** — Alpine.js store for WebSocket connection. Preserved as-is with minor updates (event type routing).
- **`live-updates.js`** — Debounced HTMX partial refresh. **One change:** add IntersectionObserver-based visibility tracking. Elements register with an observer on mount; the observer maintains a `Set<Element>` of currently-visible elements. The refresh scheduler checks `visibleElements.has(el)` before queuing a request. This is more reliable than `el.offsetParent !== null` (which fails for `position: fixed` and `visibility: hidden` elements).
- **`log-table.js`** — Alpine.js `logTable` component. Preserved with styling updates.

### Live-update wiring for App Detail

| Panel | Trigger event | Partial URL |
|-------|--------------|-------------|
| Health strip | `app_status_changed` | `/partials/app-health-strip/{app_key}` |
| Handler list | `app_status_changed` | `/partials/app-handlers/{app_key}` |
| Job list | `app_status_changed` | `/partials/app-jobs/{app_key}` |
| Log entries | `log` (via WS subscription) | Streamed via `logTable` component |
| Dashboard app grid | `app_status_changed` | `/partials/dashboard-app-grid` |
| Dashboard errors | `app_status_changed` | `/partials/dashboard-errors` |

**Polling for invocation freshness:** `app_status_changed` only fires on lifecycle transitions (start/stop/fail), not on individual handler invocations. A running, healthy app never broadcasts this event. To keep invocation counts fresh during diagnostic use, a **separate stats-only partial** (`/partials/app-handler-stats/{app_key}`) returns just the invocation counts and last-fired timestamps for each handler. This partial polls with `hx-trigger="every 5s" hx-sync="this:replace"`. The full handler row list (with expandable drill-down) only refreshes on WS `app_status_changed` events. This separation prevents a poll from morphing away an expanded drill-down panel while its lazy-loaded content is in flight.

**No new WS event types needed** for the initial rebuild. If the 5s polling proves insufficient, a lightweight `telemetry_updated` WS broadcast can be added later.

### Alpine.js state preservation

All elements with `x-data` must have stable `id` attributes so idiomorph can match them across morphs:

```html
<!-- WRONG: idiomorph can't match this reliably -->
<div x-data="{ open: false }">

<!-- RIGHT: stable id ensures state preservation -->
<div id="handler-{{ listener.id }}" x-data="{ open: false }">
```

### Handler/job row expand pattern

Drill-down invocation history is loaded on demand via HTMX, triggered by the Alpine.js click handler — not by IntersectionObserver (which does not fire on `display: none` elements set by `x-show`):

```html
<div id="handler-{{ listener.id }}" class="item-row"
     x-data="{ open: false, loaded: false }">
  <div class="item-row__main"
       @click="open = !open; if (open && !loaded) { htmx.ajax('GET', '/ui/partials/handler-invocations/{{ app_key }}/{{ listener.id }}', { target: '#handler-{{ listener.id }}-detail', swap: 'innerHTML' }); loaded = true; }">
    <!-- summary row content -->
  </div>
  <div id="handler-{{ listener.id }}-detail"
       x-show="open" x-cloak>
    <div class="detail-loading">Loading invocations...</div>
  </div>
</div>
```

This lazy-loads invocation history on first expand only. The `loaded` flag prevents re-fetching on subsequent toggles. The `id` attribute ensures idiomorph preserves Alpine.js state across morphs.

### E2E test strategy

- **Conftest reuse:** The `create_hassette_stub()` fixture chain is preserved. Seed data is updated to include telemetry records (invocations, executions) for the new UI assertions.
- **Selector strategy:** `data-testid` attributes on all interactive and assertable elements. Text content assertions as secondary validation.
- **Test files:**

| File | Coverage |
|------|----------|
| `test_navigation.py` | Sidebar nav, active states, collapse/expand, responsive |
| `test_dashboard.py` | Connection bar, KPI strip, app grid, error feed |
| `test_app_detail.py` | Health strip, handler rows, invocation drill-down, job rows, execution history, logs, controls |
| `test_apps_list.py` | App list, status filter tabs |
| `test_logs.py` | Log viewer, level filter, search, sort |
| `test_websocket.py` | WS connection, live updates, morphing stability |
| `test_theme.py` | Light/dark toggle, token application |

- **Write tests alongside each page**, not after. Each page implementation includes its E2E tests.

### Identity model bug fix

`router.py:105` and `:147` filter jobs by `owner_id` (which is `None` for stopped/failed apps). The correct filter is `app_key + instance_index`. This is fixed as part of the route rewrite — both lines are replaced in the new `router.py`.

### Sidebar design

56px collapsed icon rail. **Same background temperature as the page** — uses `--ht-bg`, separated by `--ht-border`. No dark sidebar on light page.

Active nav item: `--ht-accent-light` background, `--ht-accent` icon color.

Pulse dot at the bottom: `--ht-accent` with `breathe` animation when connected. `--ht-danger` and static when disconnected.

### Dark mode

Both modes ship together. CSS uses `[data-theme="light"]` and `[data-theme="dark"]` selectors. A `data-theme` attribute on `<html>` controls the mode. Toggle button in the top-right corner. Default to dark (the user's preferred mode). Persist preference in `localStorage`.

## Alternatives Considered

### Tailwind CSS via standalone CLI

**Rejected.** The critique identified ARM64/Alpine Linux failures in Tailwind v4's standalone CLI (GitHub issues #14569, #16555). The project targets Raspberry Pi and Docker deployments. Pre-compiling at publish time mitigates this but adds build complexity. At ~1,200 lines of CSS with a well-defined token system, hand-written CSS is manageable and has zero toolchain risk.

### Incremental page-by-page migration

**Rejected.** The critique (finding #2, CRITICAL) demonstrated that phased migration creates throw-away work — Bus and Scheduler pages would be styled then deleted. A big-bang rewrite avoids mixed-state UI and rework. The user confirmed big-bang is acceptable.

### Tabbed App Detail (Airflow-style 4-layer hierarchy)

**Rejected.** The critique (finding #6, HIGH) and task analysis demonstrated that at Hassette's scale (3-10 apps, ~15 handlers), tabs hide information that fits on one page. The flat layout keeps everything visible and scrollable, matching the "well-organized toolbox" feel.

### SPA (Preact/Solid)

**Rejected per research brief.** Requires a JS build step (contradicts no-Node.js preference), abandons working HTMX/Alpine.js infrastructure, over-engineered for 4 pages of mostly tables and lists.

## Open Questions

- [ ] **Icon library**: Font Awesome dropped. Replacement TBD (Lucide, Heroicons, custom inline SVGs). Decision needed before template implementation.
- [ ] **Font loading**: Google Fonts CDN or self-hosted? CDN is simpler; self-hosted works offline in homelab scenarios.

## Resolved (from design critique)

- [x] **Expand pattern**: `hx-trigger="intersect once"` replaced with Alpine.js `@click` triggered `htmx.ajax()` — IntersectionObserver doesn't fire on `display: none` elements.
- [x] **Handler summaries**: `predicate_description` repr parsing replaced with `summarize()` method on predicate classes, populated at registration time.
- [x] **Deferred feature placeholders**: Each deferred feature now has a specified template element, disabled state, and future endpoint URL.
- [x] **Invocation freshness**: Added `hx-trigger="every 5s"` polling on handler list partial to keep counts fresh during diagnostic use.
- [x] **Deployment strategy**: Feature branch workflow with atomic merge at minimum viable milestone.
- [x] **Visibility gate**: `el.offsetParent` replaced with IntersectionObserver-based visibility tracking.
- [x] **CSS estimate**: Updated to 1,500-1,800 lines.
- [x] **Typed query results**: Added Pydantic models for query results as a backend prerequisite.

## Impact

### Files replaced (big-bang)

- `src/hassette/web/templates/` — all 30 HTML files → ~24 new files
- `src/hassette/web/static/css/` — 2 files (tokens.css, style.css) → 2 new files
- `src/hassette/web/static/js/` — 3 files → 3 files (evolved)
- `src/hassette/web/ui/router.py` — rewritten (7 routes → 5 routes)
- `src/hassette/web/ui/partials.py` — rewritten (14 partials → ~10 partials)
- `src/hassette/web/ui/context.py` — rewritten (add `format_handler_summary()`)
- `tests/e2e/` — all 9 test files → 7-8 new test files

### Files preserved

- `src/hassette/web/app.py` — minor updates (drop Font Awesome CDN)
- `src/hassette/web/dependencies.py` — unchanged
- `src/hassette/web/models.py` — unchanged
- `src/hassette/web/utils.py` — unchanged
- `src/hassette/web/routes/` — all 9 API route files unchanged
- `src/hassette/web/ui/__init__.py` — unchanged (may add custom filter for handler summaries)
- `tests/e2e/conftest.py` — evolved (seed data updates for telemetry)

### Blast radius

The change is primarily contained to the web UI layer. Changes to other layers:

**Small backend prerequisites (do early):**
- `src/hassette/event_handling/predicates.py` — add `summarize()` method to predicate classes
- `src/hassette/core/` — add Pydantic models for `ListenerSummary`, `JobSummary`, `HandlerInvocation`, `JobExecution`
- Database: one Alembic migration to add `human_description` column to `listeners` table

**No changes to:**
- App system (`src/hassette/app/`)
- Bus, Scheduler, API services (beyond predicate `summarize()`)
- Configuration system
- Documentation site (`docs/`)

### Dependencies affected

- Font Awesome CDN reference removed from `base.html`
- DM Sans added to Google Fonts import
- No new Python dependencies
- No new JS dependencies
