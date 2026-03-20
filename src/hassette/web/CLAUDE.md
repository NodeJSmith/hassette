# Hassette Web UI — Developer Guide

## Template Directory Layout

```
templates/
├── base.html              # Root layout: Google Fonts, HTMX, Alpine.js, idiomorph, nav, theme toggle
├── macros/
│   └── ui.html            # Shared Jinja2 macros (status_badge, job_status_badge, health_card,
│                          #   handler_row, job_row, action_buttons, log_table)
├── components/
│   ├── nav.html            # 56px icon-rail sidebar with pulse dot
│   ├── connection_bar.html # HA WebSocket connection status banner
│   ├── status_bar.html     # Top status bar (simplified)
│   └── alert_banner.html   # Global alert strip (failed apps)
├── pages/                  # Full-page templates (extend base.html)
│   ├── dashboard.html      # KPI strip + app health grid + error feed + session bar
│   ├── apps.html           # Manifest list with server-side status filter tabs
│   ├── app_detail.html     # Center of gravity: health strip, handler/job rows, logs
│   ├── logs.html           # Global log viewer with level/app/search filters
│   └── error.html          # Error page (404, 500)
└── partials/               # HTML fragments for HTMX swaps (no <html>, no <head>)
    ├── alert_failed_apps.html
    ├── manifest_list.html       # App manifest rows (server-filtered via ?status=)
    ├── log_entries.html
    ├── dashboard_app_grid.html  # App health cards with health bars
    ├── dashboard_errors.html    # Session-scoped recent errors feed
    ├── app_health_strip.html    # 4 health KPI cards
    ├── app_handlers.html        # Handler row list (uses handler_row macro)
    ├── app_jobs.html            # Job row list (uses job_row macro)
    ├── app_logs.html            # App-scoped log entries
    ├── app_handler_stats.html   # Stats-only polling partial (data-* attrs for JS updater)
    ├── handler_invocations.html # Expanded invocation history (lazy-loaded on click)
    ├── job_executions.html      # Expanded execution history (lazy-loaded on click)
    └── app_detail_jobs.html     # App detail job list
```

## Pages vs Partials

- **Pages** extend `base.html` and define `{% block content %}`. They are full HTML documents.
- **Partials** are HTML fragments returned by `/ui/partials/*` endpoints. They never extend base.html and never contain `<html>` or `<head>` tags. Partials are swapped in via HTMX.

## Available Macros (`macros/ui.html`)

Import macros at the top of a template:
```jinja
{% from "macros/ui.html" import status_badge, health_card, handler_row, job_row, action_buttons, log_table %}
```

### `status_badge(status, size="", block_reason="")`
Renders a dot + label badge for app/instance status (running/failed/stopped/disabled/blocked).
- `size="small"` renders a compact badge variant
- `block_reason` adds a title attribute for blocked status

### `health_card(label, value, detail, status_class="")`
Renders a KPI card for the health strip (init status, error rate, avg duration, last activity).

### `handler_row(listener, app_key, summary="")`
Renders an expandable handler row with Alpine.js `@click` + `htmx.ajax()` lazy-load pattern.
- Stable `id="handler-{{ listener.listener_id }}"` for idiomorph matching
- `data-testid="handler-row-{{ listener.listener_id }}"`
- `summary` — plain-language description from `format_handler_summary()`

### `job_row(job, app_key)`
Renders an expandable job row with the same Alpine.js expand pattern as handler_row.

### `action_buttons(app_key, status, after_action="location.reload()", show_labels=true)`
Renders start/stop/reload buttons with HTMX POST and inline Lucide SVG icons.
- `after_action` — JS expression to run after the HTMX request completes
- `show_labels=false` — icon-only buttons (for compact table rows)

### `log_table(show_app_column, app_key="", max_height="600px", app_keys=None)`
Full Alpine.js log viewer with filters, sortable columns, and WebSocket streaming.
- `show_app_column` — whether to show the App column
- `app_key` — lock to a specific app's logs
- `app_keys` — list of app keys for the app filter dropdown (main logs page)

### `job_status_badge(status)`
Renders a status tag for job execution results (success/error/cancelled).

## CSS Architecture

Two CSS files, both using the `--ht-*` design token system from `design/direction.md`:

- **`tokens.css`** — All `--ht-*` custom properties. Dark mode in `:root, [data-theme="dark"]`, light mode in `[data-theme="light"]`.
- **`style.css`** — All component styles. Every value references a `--ht-*` token. No raw hex values.

All custom CSS classes use the `ht-` prefix: `ht-layout`, `ht-sidebar`, `ht-card`, `ht-status-badge`, `ht-item-row`, `ht-health-card`, etc.

## Jinja2 Template Globals

Registered in `web/ui/__init__.py`, available in all templates without explicit passing:

- `classify_error_rate(rate)` — returns `"good"` / `"warn"` / `"bad"` CSS class
- `classify_health_bar(success_rate)` — returns `"excellent"` / `"good"` / `"warning"` / `"critical"` CSS class

## JavaScript Patterns

### Alpine.js Components
- `logTable(config)` — log viewer (`static/js/log-table.js`). Has `init()` and `destroy()` lifecycle methods.
- Alpine stores: `$store.ws` — WebSocket state (`static/js/ws-handler.js`).

### HTMX
- Partials are loaded via `hx-get` with `hx-swap="innerHTML"`.
- Action buttons use `hx-post` with `hx-on::after-request` for post-action behavior.
- Handler/job row expand uses Alpine.js `@click` + `htmx.ajax()` (NOT `hx-trigger="intersect"`).

### Live Updates (`static/js/live-updates.js`)
- `data-live-on-app="/url"` — refreshed on `app_status_changed` WebSocket messages via idiomorph morph
- Used on: health strip, dashboard app grid, dashboard errors. NOT on handler/job lists (those use polling).
- All swaps use idiomorph `morph:innerHTML` — identical content produces zero DOM mutation
- Re-reads the `data-live-on-app` attribute at fire time (not enqueue time) to support dynamic URLs
- Uses a `Map` for pending refreshes with 500ms debounce
- IntersectionObserver-based visibility tracking — only refreshes visible elements

### Handler Stats Polling (`live-updates.js`)
- `#app-handler-stats` polls every 5s via `hx-trigger="every 5s"`
- On `htmx:afterSwap`, JS reads `data-*` attributes from the polled partial and updates handler row counts, status dots, and durations in-place (text content + class changes only — no DOM replacement)
- This preserves Alpine.js expand/collapse state on handler rows

## Banned Patterns

Enforced by `tools/check_template_patterns.py`:
1. **No inline `<script>` tags in partials/components/macros** — use `{% block scripts %}` in pages or Alpine.js components.
2. **No inline event handlers** (`onclick=`, `onchange=`, `oninput=`, etc.) — use Alpine.js directives (`@click`, `@change`, `@input`).
3. **No Font Awesome** — use inline Lucide SVG icons.
4. **No raw hex values in CSS** — use `--ht-*` tokens from `tokens.css`.

## Shared Dependency Aliases

Import from `hassette.web.dependencies` instead of defining locally:
```python
from hassette.web.dependencies import RuntimeDep, TelemetryDep, HassetteDep, ApiDep
```

- `RuntimeDep` — live system state (app status, logs, events, WebSocket)
- `TelemetryDep` — historical telemetry from the database (listeners, jobs, errors, summaries)

## How to Add a New Page

1. Create `templates/pages/my_page.html` extending `base.html`.
2. Import needed macros: `{% from "macros/ui.html" import ... %}`.
3. Add a route in `web/ui/router.py` returning `TemplateResponse`.
4. Use `RuntimeDep` (and `TelemetryDep` as needed) from `web/dependencies.py`.
5. Add nav link in `templates/components/nav.html`.

## How to Add a New Partial

1. Create `templates/partials/my_partial.html` (no `{% extends %}`).
2. Add a route in `web/ui/partials.py` returning `TemplateResponse`.
3. Reference from pages via `hx-get="/ui/partials/my-partial"`.
