---
task_id: "T04"
title: "Add App Detail Code, Logs, and Config tab pages"
status: "planned"
depends_on: ["T01", "T03"]
implements: ["FR#2", "FR#3"]
---

## Summary
Create the three remaining App Detail tab sub-pages: Code, Logs, and Config. These are smaller pages documenting the source viewer, per-app log table, and app configuration display. Each page is focused and self-contained.

## Prompt
Create three new files in `docs/pages/web-ui/app-detail/`:

### 1. `code.md` — Code Tab

Documents the read-only source code viewer:

- **Source header** — filename, line count, "read-only" badge, "copy path" button
- **Syntax-highlighted source** — Python source with Shiki syntax highlighting (theme-aware — light/dark), line numbers
- **Handler annotations** — lines where handlers are registered are highlighted; hovering shows handler names
- **Deep link support** — `?line=N` URL parameter scrolls to and highlights a specific line. The "view in code →" link from the Handlers tab navigates here with the line focused.
- Use `![Code tab](../../../_static/web_ui_app_detail_code.png)` as the hero screenshot
- **Related pages** — link to Handlers Tab (for handler details)

Read `frontend/src/components/app-detail/code-tab.tsx` for exact features.

### 2. `logs.md` — Logs Tab

Documents the per-app scoped log viewer:

- **Same features as the global Logs page** but filtered to a single app — explain this relationship briefly ("This tab shows the same log viewer as the [global Logs page](../logs.md), filtered to this app.")
- **Columns** — LEVEL, TIMESTAMP, EXECUTION, FUNCTION, MODULE, MESSAGE (same as global)
- **Search** — "Search logs..." filters by message content
- **Live streaming** — new log entries appear in real-time via WebSocket
- Note: this is the same log table component used on the global Logs page and in the Overview tab's embedded logs section
- **Related pages** — link to global Logs page (for cross-app view), Overview Tab (which has an embedded logs preview)

Read `frontend/src/components/app-detail/app-logs-panel.tsx` and `frontend/src/components/shared/log-table/` for the shared component.

### 3. `config.md` — Config Tab

Documents the app configuration viewer:

- **Metadata header** — FILE (filename), CLASS (class name), ENABLED (yes/no)
- **Configuration table** — "Instance N" heading, columns: KEY, TYPE, VALUE. Types are derived from the AppConfig class schema (string, number, boolean). Values show "—" for defaults/None.
- **Raw config panel** — JSON representation of the config as loaded from hassette.toml. Shows the TOML source path.
- **Multi-instance display** — each instance shown separately with its own config table
- Use `![Config tab](../../../_static/web_ui_app_detail_config.png)` as the hero screenshot
- **Related pages** — link to App Detail index (for app overview)

Read `frontend/src/components/app-detail/config-tab.tsx` for exact structure.

## Focus
- Image paths from app-detail sub-pages use `../../../_static/` (one extra level up).
- The Code tab's handler annotations feature may not be visible in the screenshot if the ClimateController doesn't have annotated lines in the viewport — describe the feature based on the frontend code, not just the screenshot.
- The Logs tab is intentionally thin — it reuses the shared log table component. Don't duplicate the global Logs page documentation; link to it instead.
- The Config tab shows "Instance 0" for single-instance apps. The screenshot shows ClimateController which is single-instance.

## Verify
- [ ] FR#2: Each page describes exactly one tab — Code, Logs, Config are distinct and focused
- [ ] FR#3: Every documented feature (syntax highlighting, handler annotations, deep linking, config table, raw JSON) exists in the frontend code
