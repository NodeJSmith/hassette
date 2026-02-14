# Hassette Web UI — Developer Guide

## Template Directory Layout

```
templates/
├── base.html              # Root layout: Bulma, HTMX, Alpine.js, nav
├── macros/
│   └── ui.html            # Shared Jinja2 macros (status_badge, action_buttons, log_table, job_status_badge)
├── components/
│   ├── nav.html            # Sidebar navigation
│   └── status_bar.html     # Top status bar (health badge)
├── pages/                  # Full-page templates (extend base.html)
│   ├── dashboard.html
│   ├── apps.html
│   ├── app_detail.html
│   ├── app_instance_detail.html
│   ├── logs.html
│   ├── scheduler.html
│   ├── bus.html
│   └── entities.html
└── partials/               # HTML fragments for HTMX swaps (no <html>, no <head>)
    ├── health_badge.html
    ├── event_feed.html
    ├── app_list.html
    ├── app_row.html
    ├── manifest_list.html
    ├── manifest_row.html
    ├── instance_row.html
    ├── log_entries.html
    ├── entity_list.html
    ├── scheduler_jobs.html
    ├── scheduler_history.html
    ├── bus_listeners.html
    ├── bus_metrics.html
    ├── apps_summary.html
    ├── dashboard_scheduler.html
    ├── dashboard_logs.html
    ├── app_detail_listeners.html
    └── app_detail_jobs.html
```

## Pages vs Partials

- **Pages** extend `base.html` and define `{% block content %}`. They are full HTML documents.
- **Partials** are HTML fragments returned by `/ui/partials/*` endpoints. They never extend base.html and never contain `<html>` or `<head>` tags. Partials are swapped in via HTMX.

## Available Macros (`macros/ui.html`)

Import macros at the top of a template:
```jinja
{% from "macros/ui.html" import status_badge, action_buttons, log_table, job_status_badge %}
```

### `status_badge(status, size="", block_reason="")`
Renders a Bulma tag for app/instance status (running/failed/stopped/disabled/blocked).
- `size="small"` renders with `is-small` class
- `block_reason` adds a title attribute for blocked status

### `action_buttons(app_key, status, after_action="location.reload()", show_labels=true)`
Renders start/stop/reload buttons with HTMX POST.
- `after_action` — JS expression to run after the HTMX request completes
- `show_labels=false` — icon-only buttons (for compact table rows)

### `log_table(show_app_column, app_key="", max_height="600px", app_keys=None)`
Full Alpine.js log viewer with filters, sortable columns, and WebSocket streaming.
- `show_app_column` — whether to show the App column
- `app_key` — lock to a specific app's logs
- `app_keys` — list of app keys for the app filter dropdown (main logs page)

### `job_status_badge(status)`
Renders a status tag for job execution results (success/error/cancelled).

## CSS Naming Convention

All custom CSS classes use the `ht-` prefix:
- `ht-layout`, `ht-main`, `ht-sidebar`
- `ht-status-stopped`, `ht-status-disabled`, `ht-status-blocked`
- `ht-log-debug`, `ht-log-info`, `ht-log-warning`, `ht-log-error`, `ht-log-critical`
- `ht-log-container`, `ht-live-pulse`, `ht-group-header`, `ht-instance-row`

## JavaScript Patterns

### Alpine.js Components
- `logTable(config)` — log viewer (`static/js/log-table.js`). Has `init()` and `destroy()` lifecycle methods.
- `entityBrowser()` — defined inline in `pages/entities.html` `{% block scripts %}`.
- Alpine stores: `$store.ws` — WebSocket state (`static/js/ws-handler.js`).

### HTMX
- Partials are loaded via `hx-get` with `hx-swap="innerHTML"`.
- Action buttons use `hx-post` with `hx-on::after-request` for post-action behavior.

### Live Updates (`static/js/live-updates.js`)
- `data-live-refresh="/url"` — refreshed on `ht:refresh` events
- `data-live-on-app="/url"` — refreshed on `app_status_changed` WebSocket messages
- `data-live-on-state="/url"` — refreshed on `state_changed` WebSocket messages
- Uses a `Map` for pending refreshes with 500ms debounce (no DOM mutation).

## Banned Patterns

Enforced by `tools/check_template_patterns.py`:
1. **No inline `<script>` tags in partials/components/macros** — use `{% block scripts %}` in pages or Alpine.js components.
2. **No inline event handlers** (`onclick=`, `onchange=`, `oninput=`, etc.) — use Alpine.js directives (`@click`, `@change`, `@input`).

## Shared Dependency Aliases

Import from `hassette.web.dependencies` instead of defining locally:
```python
from hassette.web.dependencies import DataSyncDep, HassetteDep, ApiDep
```

## How to Add a New Page

1. Create `templates/pages/my_page.html` extending `base.html`.
2. Import needed macros: `{% from "macros/ui.html" import ... %}`.
3. Add a route in `web/ui/router.py` returning `TemplateResponse`.
4. Use `DataSyncDep` from `web/dependencies.py`.
5. Add nav link in `templates/components/nav.html`.

## How to Add a New Partial

1. Create `templates/partials/my_partial.html` (no `{% extends %}`).
2. Add a route in `web/ui/partials.py` returning `TemplateResponse`.
3. Reference from pages via `hx-get="/ui/partials/my-partial"`.
