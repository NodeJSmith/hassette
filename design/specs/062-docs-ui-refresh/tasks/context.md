# Context: Web UI Documentation Rewrite

## Problem & Motivation
The Web UI documentation describes an interface that no longer exists after the v0.30.0-v0.32.0 redesign. Two of five pages (Dashboard, Sessions) cover removed features, three are significantly outdated, and new pages (Handlers, Config, plus cross-cutting Layout & Navigation and App Detail sub-pages) have no documentation. All old screenshots have been replaced. Users must ignore the docs and reverse-engineer the interface, leaving features like the command palette, handler detail view, and code viewer undiscovered.

## Visual Artifacts
All screenshots are captured and ready in `docs/_static/`. Reference them directly in docs pages using `![alt](../../_static/filename.png)`.

**Full-page screenshots:**
- `web_ui_apps.png` — Apps page with sidebar, stats strip, table, sparklines, error, "auto" badge
- `web_ui_app_detail_overview.png` — Overview tab with error spotlight, handler health grid, activity, logs
- `web_ui_app_detail_handlers.png` — Handlers tab with failing handler selected, error banner, stats, executions
- `web_ui_app_detail_code.png` — Code tab with syntax-highlighted ClimateController source
- `web_ui_app_detail_config.png` — Config tab with typed table + raw JSON
- `web_ui_handlers.png` — Global handlers table with fail_once highlighted in red
- `web_ui_logs.png` — Global logs table
- `web_ui_config.png` — System config with all 7 groups

**Cropped detail screenshots:**
- `web_ui_detail_error_spotlight.png` — "failing handlers" section with handler name + error type
- `web_ui_detail_handler_error.png` — Red error banner with TypeError + "show traceback"
- `web_ui_detail_instance_switcher.png` — Breadcrumb + instance switcher tabs (paulus / home_boy)
- `web_ui_detail_log_drawer.png` — Side panel with full log entry metadata
- `web_ui_detail_column_picker.png` — Column visibility checkbox popover
- `web_ui_detail_command_palette.png` — Modal with pages, apps, instances, handlers sections
- `web_ui_detail_status_bar.png` — Time presets, uptime, WS indicator, theme toggle
- `web_ui_detail_sidebar.png` — Full sidebar with nav, status groups, "auto" badge

## Key Decisions
1. **12-page structure** replacing the current 5. Six top-level pages + App Detail split into index + 5 tab sub-pages. Diagnostics intentionally excluded (hidden from sidebar and command palette).
2. **Layout & Navigation written first** to establish vocabulary (sidebar, status bar, command palette, time-preset selector) that all other pages reference.
3. **App Detail split into sub-pages** — outline-first gate confirmed ~22 H3 headings and ~7 column tables, exceeding both thresholds. Index page covers shared elements; one sub-page per tab.
4. **Sessions concept retired** — "sessions.md" deleted without replacement. "Since restart" preset documented using "since the last restart" language, not "current session."
5. **Cross-page linking** — each Web UI page ends with "Related pages" or "Next steps" linking to natural next pages in monitoring and troubleshooting workflows.
6. **"auto" badge documented** — auto-detected apps show "auto" badge in sidebar and app detail header. Explicitly configured apps do not.
7. **Screenshots captured first** — all 16 screenshots (8 full-page + 8 cropped) are already in `docs/_static/`. Tasks reference real images directly.

## Constraints & Anti-Patterns
- **Do not modify any frontend code.** Document what exists, not what should exist.
- **Do not invent UI features.** The Diagnostics page exists but is intentionally excluded from docs.
- **Avoid "current session" terminology** — use "since the last restart" instead. Sessions are DB-internal vocabulary being retired from user-facing docs.
- **No "Dashboard page", "Sessions page", "session scope toggle", "bottom navigation", or "icon sidebar"** references may appear in any doc page.
- **Error spotlight is conditional** — only renders when handlers are failing. Don't describe it as always-visible.
- **Overview page mode ordering** — explanation paragraph first, hero screenshot, how-to (enabling/accessing/security), config reference in collapsed admonition. Don't mix modes.
- **Use nested config keys** — the v0.32.0 migration moved flat keys to nested groups. Use `[hassette.web_api] run_ui = false` not `run_web_ui = false`. See `src/hassette/config/legacy.py` for the mapping.

## Design Doc References
- `## Architecture` — page structure table, mkdocs nav, screenshot plan, cross-reference update list, execution order
- `## Convention Examples` — target writing style for new pages (illustrative, not from existing files)
- `## Edge Cases` — multi-instance, empty states, mobile layout, time-preset behavior
- `## Cross-reference updates` — specific files and line numbers for dashboard/sessions references to update
- `## Cross-page linking requirement` — minimum links between pages for AC#4

## Convention Examples
These examples show the **target** writing style for the new pages.

### Doc page structure with screenshot and feature list

```markdown
# Logs

The Logs page provides a filterable, searchable view of all log entries
across your hassette apps.

![Logs page](../../_static/web_ui_logs.png)

## Features

### Filtering

Filter logs by level (DEBUG through CRITICAL) and by app using the
dropdown selectors. ...
```

### Admonition usage for tips and warnings

```markdown
!!! tip "Quick Navigation"
    Click any app card to navigate directly to the App Detail View.

!!! warning "No Authentication"
    The web UI does not currently include authentication.
    Only expose the hassette port on trusted networks.
```

### Table for documenting columns/fields

```markdown
| Column | Description |
|--------|-------------|
| App | Name and key of the automation |
| Status | Current lifecycle state with color indicator |
| Actions | Stop, Reload, or Start buttons |
```

### Cross-page linking pattern

```markdown
See the [Apps page](apps.md) for details on managing your automations,
or the [Logs page](logs.md) for filtering and searching log entries.
```
