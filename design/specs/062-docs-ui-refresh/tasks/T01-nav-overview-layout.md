---
task_id: "T01"
title: "Update mkdocs nav, rewrite Overview, add Layout & Navigation"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#4", "AC#1"]
---

## Summary
Create the two foundational Web UI docs pages and restructure the mkdocs nav. The Overview page (`index.md`) is rewritten to describe the current UI. The Layout & Navigation page (`layout.md`) is new and documents all cross-cutting chrome: sidebar, status bar, command palette, mobile nav, and alert banners. The mkdocs.yml nav is updated to the 12-page structure. Old files (`dashboard.md`, `sessions.md`) are deleted.

These two pages establish the vocabulary — sidebar, status bar, command palette, time-preset selector, "auto" badge — that all subsequent pages reference.

## Prompt
### mkdocs.yml nav update

Edit `mkdocs.yml` (Web UI nav section, currently lines 78-83). Replace with:

```yaml
- Web UI:
    - Overview: pages/web-ui/index.md
    - Layout & Navigation: pages/web-ui/layout.md
    - Apps: pages/web-ui/apps.md
    - App Detail:
        - Overview: pages/web-ui/app-detail/index.md
        - Overview Tab: pages/web-ui/app-detail/overview.md
        - Handlers Tab: pages/web-ui/app-detail/handlers.md
        - Code Tab: pages/web-ui/app-detail/code.md
        - Logs Tab: pages/web-ui/app-detail/logs.md
        - Config Tab: pages/web-ui/app-detail/config.md
    - Handlers: pages/web-ui/handlers.md
    - Logs: pages/web-ui/logs.md
    - Config: pages/web-ui/config.md
```

### Delete obsolete files

Delete these files:
- `docs/pages/web-ui/dashboard.md`
- `docs/pages/web-ui/sessions.md`

### Rewrite Overview page

Rewrite `docs/pages/web-ui/index.md` (currently 59 lines). Follow mode-ordered structure:

1. **Explanation paragraph** (2-3 sentences) — what the web UI provides and why it exists
2. **Hero screenshot** — `![Apps page](../../_static/web_ui_apps.png)`
3. **How-to block** — enabling the UI, accessing at `http://<host>:8126/ui/`, security warning admonition (no authentication)
4. **First-run note** — admonition: "A fresh install shows empty tables and zero counts until automations run and handlers fire."
5. **Config reference** — in a `??? "Configuration Quick Reference"` collapsible admonition. Use the **new nested config key format**: `[hassette.web_api] run`, `run_ui`, `host`, `port`, etc. (NOT the legacy flat keys like `run_web_api`). See `src/hassette/config/models.py` `WebApiConfig` class (line 247) for the current field names.
6. **Related pages** — link to Layout & Navigation and Apps

Preserve the existing snippet include for `disable-ui.toml` BUT update the snippet file at `docs/pages/web-ui/snippets/disable-ui.toml` to use the new config format:
```toml
[hassette.web_api]
run_ui = false
```

### Create Layout & Navigation page

Create new file `docs/pages/web-ui/layout.md`. Document all cross-cutting UI chrome. Read the frontend components to describe each element accurately:

**Sidebar** (read `frontend/src/components/layout/sidebar.tsx`):
- Hassette wordmark + version number
- "jump to..." command palette trigger (Ctrl+K / Cmd+K)
- Nav items: apps, handlers, logs, config
- APPS section: count badge, "Filter apps..." search, collapsible status groups (RUNNING with count), individual app entries with status dots
- "auto" badge on auto-detected apps (not explicitly configured in hassette.toml)
- Multi-instance apps show expand chevron with instance sub-items
- Use `![Sidebar](../../_static/web_ui_detail_sidebar.png)` screenshot

**Status bar** (read `frontend/src/components/layout/status-bar.tsx`):
- Time-preset selector: "Since restart", "1h", "24h", "7d" — explain "Since restart" shows data from the most recent hassette startup (NOT "current session"), others use wall-clock windows
- Uptime display ("up Xm") next to presets
- WebSocket connection indicator (green dot = connected)
- Theme toggle (light/dark mode)
- Use `![Status bar](../../_static/web_ui_detail_status_bar.png)` screenshot

**Command palette** (read `frontend/src/components/layout/command-palette.tsx`):
- Shortcut: Ctrl+K (Cmd+K on macOS)
- Sections: PAGES, APPS (with status dots), INSTANCES (for multi-instance apps), HANDLERS, ACTIONS (reload all apps, stop all failing, open docs)
- Keyboard navigation
- Use `![Command palette](../../_static/web_ui_detail_command_palette.png)` screenshot

**Mobile navigation**: Hamburger menu replaces sidebar on narrow viewports. Brief mention.

**Alert banners**: Brief mention of telemetry degraded banner and failed app alert.

End with "Related pages" section linking to Apps.

## Focus
- The existing `index.md` has a config reference table and snippet include. Preserve the snippet pattern but update content.
- mkdocs supports `pymdownx.details` for collapsible admonitions (`??? "Title"` syntax).
- The snippet base path is `docs` in mkdocs.yml, so snippet paths are relative to the docs root.
- The snippet file `docs/pages/web-ui/snippets/disable-ui.toml` currently uses the legacy `run_web_ui` key — must be updated to `[hassette.web_api] run_ui = false`.
- Sidebar nav items are defined in `frontend/src/components/layout/sidebar.tsx` lines 20-25.
- Both pages should use `##` headings for major sections and `###` for sub-features.

## Verify
- [ ] FR#1: mkdocs.yml Web UI nav matches the 12-page structure from the design doc
- [ ] FR#2: Overview describes the UI overview; Layout & Navigation describes cross-cutting chrome — each page serves one purpose
- [ ] FR#4: Screenshots referenced in Overview (`web_ui_apps.png`) and Layout (`web_ui_detail_sidebar.png`, `web_ui_detail_status_bar.png`, `web_ui_detail_command_palette.png`) exist in `docs/_static/`
- [ ] AC#1: All 12 pages listed in mkdocs.yml nav
