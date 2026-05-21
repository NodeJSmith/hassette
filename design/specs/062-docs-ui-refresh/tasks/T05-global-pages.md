---
task_id: "T05"
title: "Add Handlers, rewrite Logs, and add Config global pages"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#4", "FR#5", "AC#3"]
---

## Summary
Create the three global pages: Handlers (new), Logs (rewrite), and Config (new). These are the non-app-specific monitoring pages accessible from the sidebar nav. The Handlers page provides the fleet-level cross-app view. The Logs page is the global log viewer with column picker, detail drawer, and execution ID filtering. The Config page shows the system configuration.

## Prompt
### 1. Rewrite `docs/pages/web-ui/logs.md` (currently 48 lines)

The Logs page is the most feature-rich global page. Document:

- **Opening paragraph** — global filterable, searchable log viewer with real-time streaming
- **Hero screenshot** — `![Logs page](../../_static/web_ui_logs.png)`
- **Column picker** — icon button that opens a checkbox popover to toggle column visibility. Required columns (Level) are disabled. Some columns hidden at narrow viewports. "Reset to defaults" button. Use `![Column picker](../../_static/web_ui_detail_column_picker.png)` screenshot.
- **Log table columns** — LEVEL (with filter), TIMESTAMP (sortable, default sort descending), APP (with filter), INSTANCE, EXECUTION, FUNCTION (with filter), MODULE, MESSAGE. Document with a column table.
- **Search** — filters by message content
- **Log detail drawer** — click any row to open a side panel with full details: level badge, timestamp, metadata grid (app with link, instance, execution ID with copy button, function, module, line, logger), message section with copy button, exception/traceback section (if present) with copy button. Keyboard navigation (arrows for prev/next, Escape to close). Use `![Log detail drawer](../../_static/web_ui_detail_log_drawer.png)` screenshot.
- **Live streaming** — new entries appear in real-time via WebSocket
- **Auto-pause on sort** — when the user sorts by a column, live streaming pauses to prevent the sort from being disrupted. A "Resume" indicator appears.
- **Execution ID filtering** — `?execution_id=<id>` URL parameter filters to logs from a specific handler/job execution. Used when navigating from the Handlers tab's execution history.
- **Related pages** — link to App Detail Logs Tab (per-app filtering), App Detail Handlers Tab (execution ID linking)

Read `frontend/src/pages/logs.tsx`, `frontend/src/components/shared/log-table/` for exact features.

### 2. Create `docs/pages/web-ui/handlers.md` (new)

The cross-app handler/job table. Navigate here when managing multiple apps and needing to scan all handlers for a specific entity or type across apps.

- **Opening paragraph** — fleet-level view of all registered handlers and jobs across all apps. "Navigate here when you need to find all handlers listening to a specific entity, or scan error rates across your entire automation fleet."
- **Hero screenshot** — `![Handlers page](../../_static/web_ui_handlers.png)`
- **Table columns** — TYPE (event/job chip), APP (sortable + filterable), NAME, TRIGGER, RUNS, FAILED, TIMED OUT, ERROR RATE, AVG duration, NEXT RUN. Document with a column table. Note that failing rows are highlighted in red.
- **Search** — filters by handler name
- **Footer** — shows "N handlers · M jobs" count
- **Mobile layout** — brief note that the table switches to card layout on narrow viewports
- **Related pages** — link to App Detail Handlers Tab (for per-app drill-down with full detail panel)

Read `frontend/src/pages/handlers.tsx` for exact columns and behavior.

### 3. Create `docs/pages/web-ui/config.md` (new)

Read-only view of the running hassette configuration.

- **Opening paragraph** — shows the active framework configuration, read-only
- **Hero screenshot** — `![Config page](../../_static/web_ui_config.png)`
- **Grouped tables** — 7 groups: general, connection, buffers, timeouts, scheduler, file_watcher, paths. Each group is a card with key-value rows. Document the groups (list, not a table per group — the screenshot shows the structure clearly).
- **Value formatting** — booleans shown as `true`/`false`, numbers as plain values, arrays as comma-separated, null/empty as "—"
- **Related pages** — link to Configuration docs in core-concepts for how to change settings

Read `frontend/src/pages/config.tsx` for exact groups and rendering.

## Focus
- The existing `logs.md` is 48 lines and partially accurate — the filtering concept exists but the column picker, detail drawer, and execution ID filtering are missing.
- The old `web_ui_logs.png` screenshot should be overwritten by the new one we captured. Verify the filename matches.
- The Handlers page `web_ui_handlers.png` screenshot shows `fail_once` / `sensor_health_check` highlighted in red — good for illustrating the error rate column.
- All three pages reference screenshots in `../../_static/` (standard depth for top-level web-ui pages).
- The `web_ui_detail_log_drawer.png` cropped screenshot shows the side panel clearly — use it inline when explaining the drawer feature.

## Verify
- [ ] FR#2: Each page describes exactly one global page — Handlers, Logs, Config are distinct
- [ ] FR#3: Every documented interaction (column picker, log detail drawer, execution ID filter, auto-pause, handler table sort/filter) exists in the frontend
- [ ] FR#4: Every screenshot referenced (`web_ui_handlers.png`, `web_ui_logs.png`, `web_ui_config.png`, detail crops) exists in `docs/_static/`
- [ ] FR#5: No references to old screenshots (`web_ui_dashboard.png`, `web_ui_sessions.png`) — these files have been deleted
- [ ] AC#3: All screenshots show the current UI (post-v0.30.0)
