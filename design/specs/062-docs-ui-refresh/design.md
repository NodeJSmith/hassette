# Design: Web UI Documentation Rewrite

**Date:** 2026-05-20
**Status:** archived
**Scope-mode:** hold
**Research:** /tmp/claude-mine-define-research-fdlh21/brief.md

## Problem

The Web UI documentation describes an interface that no longer exists. Two of the five documented pages (Dashboard and Sessions) cover features that were removed in the v0.30.0 redesign. The remaining three pages are significantly outdated — they describe an icon-based bottom navigation, a session scope toggle, and a dashboard landing page, none of which exist anymore. Three entirely new pages (Handlers, Diagnostics, Config) have no documentation at all. All four screenshots show the old UI.

A new user who installs hassette and opens the Web UI sees an apps-centric layout with a sidebar, command palette, and time-preset selector — then opens the docs and reads about a dashboard with KPI strips and a session scope toggle. Every page they visit deepens the confusion: the "Dashboard" docs describe a page that doesn't exist, the "Sessions" docs describe a removed feature, and the screenshots show an interface they've never seen. Users must ignore the docs and explore the UI themselves, which means features like the command palette, diagnostics page, and handler detail view go undiscovered entirely. For a framework that emphasizes developer experience, shipping docs that actively mislead is a credibility problem.

## Goals

1. Every Web UI documentation page accurately describes the current interface
2. All screenshots show the current UI with representative data
3. A new user can follow the docs to understand both routine monitoring ("is everything healthy?") and troubleshooting ("what went wrong and where?")
4. New features (command palette, handler detail, code viewer, diagnostics) are discoverable through the docs
5. All references to the old UI in non-Web-UI docs pages are updated

## User Scenarios

### Alex: New hassette user

- **Goal:** Learn the Web UI after deploying hassette for the first time
- **Context:** Has automations running, opens the UI at localhost:8126/ui/

#### First visit orientation

1. **Opens the docs Web UI overview**
   - Sees: What the UI provides, how to enable/configure it, a screenshot matching what they see in the browser
   - Then: Navigates to Layout & Navigation to understand the sidebar and status bar

2. **Learns the navigation model**
   - Sees: Sidebar structure, status indicators, command palette shortcut
   - Decides: Whether to explore pages sequentially or jump to a specific page
   - Then: Opens the Apps page docs

3. **Understands the Apps page**
   - Sees: Stats strip, app table with status filters, how to search and sort
   - Decides: Clicks an app to see detail
   - Then: Reads App Detail docs to understand tabs

4. **Explores app detail tabs**
   - Sees: Overview tab with handler health, handlers tab with master-detail, code tab with source, logs tab, config tab
   - Then: Understands the full monitoring surface for a single app

### Sam: Existing user troubleshooting a failure

- **Goal:** Find why an automation stopped working
- **Context:** Noticed a light automation didn't trigger, opens the UI to investigate

#### Investigate a failing handler

1. **Checks the Apps page**
   - Sees: A failed app in the stats strip, red status in the table
   - Then: Clicks the app to see detail

2. **Opens the app detail overview tab**
   - Sees: Error spotlight showing the recent failure, handler health grid with red indicators
   - Decides: Clicks the failing handler to see detail
   - Then: Navigates to handlers tab

3. **Reads handler detail**
   - Sees: Invocation history with the failed execution, error message, stack trace
   - Decides: Clicks "view in code" to see where the handler is registered
   - Then: Opens the code tab at the relevant line

4. **Checks logs for context**
   - Sees: Per-app logs tab filtered to the app, or global logs page with execution ID filter
   - Then: Has enough context to fix the automation

## Functional Requirements

- **FR#1** The Web UI docs nav structure matches the current frontend route hierarchy
- **FR#2** Each page in the Web UI docs section describes exactly one UI page or cross-cutting concern (layout/navigation)
- **FR#3** Every documented interaction (filter, sort, search, tab switch, detail navigation) exists in the current frontend
- **FR#4** Every screenshot shows the current UI and is referenced by at least one docs page
- **FR#5** Old screenshots that show removed features are deleted
- **FR#6** All references to "dashboard" or "sessions page" in non-Web-UI docs are updated to reference the correct current page
- **FR#7** The monitoring workflow (check app health → drill into detail) is traceable through the docs page sequence
- **FR#8** The troubleshooting workflow (spot failure → find handler → read error → check logs) is traceable through the docs page sequence

## Edge Cases

- **Multi-instance apps**: App detail has special behavior for multi-instance apps (parent page with shared tabs, instance switcher). Must be documented separately from single-instance flow.
- **Empty states**: New installations with no telemetry data will see empty tables and zero counts. The Overview page should include a first-run expectation note: "A fresh install shows empty tables and zero counts until automations run and handlers fire."
- **Mobile layout differences**: Several pages switch from table to card layout on mobile. The docs should mention this without requiring separate mobile screenshots.
- **Time-preset selector behavior**: "Since restart" shows data from the most recent hassette startup to now; the other presets (1h, 24h, 7d) use wall-clock windows relative to the current time. Docs should use "since the last restart" language throughout — avoid "current session" (that is DB-internal terminology, not UI vocabulary).

## Acceptance Criteria

- **AC#1** The mkdocs.yml Web UI nav contains entries for all 12 pages (overview, layout, apps, app-detail index + 5 tab sub-pages, handlers, logs, config) — maps to FR#1, FR#2
- **AC#2** No docs page references "Dashboard page", "Sessions page", "session scope toggle", "bottom navigation", or "icon sidebar" — maps to FR#3, FR#6
- **AC#3** All screenshots in docs/_static/web_ui_*.png show the current UI (post-v0.30.0 redesign) — maps to FR#4, FR#5
- **AC#4** A reader can follow the Apps → App Detail → Handlers/Logs sequence to trace both the monitoring and troubleshooting scenarios without gaps — maps to FR#7, FR#8
- **AC#5** Cross-reference updates cover all files identified in the research brief (~10 files outside web-ui/) — maps to FR#6
- **AC#6** `mkdocs serve` builds without warnings and all internal links resolve

## Key Constraints

- **Do not modify any frontend code.** This is a documentation-only change. If the UI has a discoverability problem (e.g., Diagnostics not in sidebar), document it accurately — don't "fix" it in the docs by pretending it's in the sidebar.
- **Do not invent UI features.** Document only what exists in the current frontend code. If a feature seems missing (e.g., no session history page), note it in the docs if relevant but don't describe a feature that doesn't exist.
- **Screenshots require a running instance with demo data.** Write all text content first with placeholder image references, then capture screenshots as a batch. This avoids blocking text work on infrastructure setup.

## Dependencies and Assumptions

- **Running hassette instance**: Screenshots require a hassette instance connected to Home Assistant with 4+ apps in various states (running, failed, stopped, disabled) and handler activity. The existing Docker deployment workflow can be used.
- **mkdocs tooling**: Already configured in the project with all needed extensions (admonitions, tabbed content, code annotations, glightbox).
- **No external dependencies**: This is a pure documentation change with no code or infrastructure requirements beyond what's already in the project.

**Assumption**: The UI is stable and won't change significantly between when docs are written and when they ship. The v0.32.0 release is done and no further UI redesign is planned.

## Architecture

### Page structure (8 pages)

The new Web UI docs section replaces the current 5 pages with 12 pages: 5 top-level pages (overview, apps, handlers, logs, config), plus a cross-cutting Layout & Navigation page, plus 6 App Detail sub-pages (one index + one per tab). The outline-first gate was executed — App Detail exceeds both thresholds (~22 H3 headings, ~7 column tables) and is split into sub-pages. The Diagnostics page (`/diagnostics`) is intentionally excluded — it is hidden from sidebar and command palette, and not ready for user-facing documentation.

| Page | File | Replaces | Content |
|------|------|----------|---------|
| Overview | `index.md` | Rewrite of existing | Explanation, hero screenshot, enabling/accessing/security (how-to), config reference (collapsed admonition) |
| Layout & Navigation | `layout.md` | New | Sidebar (wordmark, version, command palette trigger, nav items, APPS section with status groups + filter + app list with "auto" badges), status bar (time-preset selector with uptime display, WS indicator, theme toggle), command palette (Ctrl+K — sections: pages, apps, instances, handlers, actions), mobile hamburger nav, alert banners |
| Apps | `apps.md` | Rewrite of existing | Stats strip (total/running/failed/stopped/disabled/handlers/runs-per-hr), table with sortable+filterable columns (app, status, last error, runs, last fired, actions), search, "auto" badge for auto-detected apps, URL params |
| App Detail | `app-detail/index.md` | New | Shared elements: breadcrumb (includes instance name for multi-instance), instance switcher (tab buttons with status dots, shown on per-instance views), header (status dot, app key, reload/stop actions, metadata: filename · class · instance N), tab strip with count badges, multi-instance parent overview (instance card grid). Sidebar shows multi-instance apps with expand chevron |
| App Detail — Overview | `app-detail/overview.md` | New | Error spotlight (conditional — only renders when handlers are failing), handler health card grid, recent activity table, embedded logs |
| App Detail — Handlers | `app-detail/handlers.md` | New | Stats strip + master-detail (listener detail: stats, modifier chips, source location with "view in code", error banner, invocation history; job detail: stats, schedule chips, trigger detail, execution history) |
| App Detail — Code | `app-detail/code.md` | New | Syntax-highlighted source with line numbers, "copy path" button, handler annotations, deep link support |
| App Detail — Logs | `app-detail/logs.md` | New | Per-app scoped log table (same features as global logs but filtered to one app) |
| App Detail — Config | `app-detail/config.md` | New | Metadata (file, class, enabled) + typed config table (key/type/value) + raw JSON panel. Multi-instance: per-instance config display |
| Handlers | `handlers.md` | New | Cross-app handler/job table. Navigate here when managing multiple apps and needing to scan all handlers for a specific entity or handler type across apps — the fleet-level view that per-app tabs don't provide |
| Logs | `logs.md` | Rewrite of existing | Column picker, detail drawer, execution ID filtering, live streaming |
| Config | `config.md` | New | Grouped config tables, value formatting |

Files to delete: `dashboard.md`, `sessions.md`.

### mkdocs.yml nav update

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

### Screenshot plan

Screenshots have been captured and are ready in `docs/_static/`. Writers reference these real images directly — no placeholders needed. All captured at **1400x900 viewport** (shows full sidebar, readable tables, no content truncation) from a running demo instance. Use `uv run python scripts/hassette_demo.py` to start the demo, wait ~20s for activity data and the failing job to fire, then capture via Playwright at the `DEMO_FRONTEND_URL`.

**Full-page screenshots** — show entire page with sidebar for context:

| Screenshot | Filename | Shows |
|------------|----------|-------|
| Apps page (hero) | `web_ui_apps.png` | Full layout with sidebar + apps table (replaces old) |
| App detail — overview | `web_ui_app_detail_overview.png` | Handler health grid, error spotlight, recent activity |
| App detail — handlers | `web_ui_app_detail_handlers.png` | Master-detail with handler selected showing stats + invocation history |
| App detail — code | `web_ui_app_detail_code.png` | Syntax-highlighted source with line numbers |
| App detail — config | `web_ui_app_detail_config.png` | Config table + raw JSON |
| Handlers page | `web_ui_handlers.png` | Cross-app handler table |
| Logs page | `web_ui_logs.png` | Log table with filters (replaces old) |
| Config page | `web_ui_config.png` | Grouped config tables |

**Cropped detail screenshots** — focused on specific UI elements being discussed:

| Screenshot | Filename | Shows |
|------------|----------|-------|
| Error spotlight | `web_ui_detail_error_spotlight.png` | Cropped to error spotlight section on overview tab (failing handler name + error type + "view" link) |
| Handler error banner | `web_ui_detail_handler_error.png` | Cropped to handler detail panel showing error banner with traceback |
| Instance switcher | `web_ui_detail_instance_switcher.png` | Cropped to breadcrumb + instance switcher tabs on a multi-instance app |
| Log detail drawer | `web_ui_detail_log_drawer.png` | Cropped to the side-panel drawer showing full log entry details |
| Column picker | `web_ui_detail_column_picker.png` | Cropped to the column picker popover on the logs page |
| Command palette | `web_ui_detail_command_palette.png` | The modal overlay with search results (naturally cropped by the modal) |
| Status bar | `web_ui_detail_status_bar.png` | Cropped to time-preset selector, uptime, WS indicator, theme toggle |
| Sidebar | `web_ui_detail_sidebar.png` | Cropped to sidebar showing status groups, multi-instance chevrons, "auto" badge |

Delete: `web_ui_dashboard.png`, `web_ui_sessions.png`.

### Cross-reference updates

~10 files outside `docs/pages/web-ui/` reference "dashboard" or the old UI and need updating. Key changes:

- `getting-started/index.md`: "see the dashboard" → "see the apps page"
- `getting-started/docker/index.md`: Update feature list at line ~157 (remove "session history", add "handler detail", "system configuration"). Leave line ~142 ("sessions marked as unknown") — that describes real database behavior during Docker shutdown, not the retired UI concept.
- `core-concepts/database-telemetry.md`: Requires two passes. (1) Session cleanup: remove or reframe the direct `sessions.md` links at lines 11 and 137 and session-concept references at line 110 (sessions are being retired as a user-facing concept). (2) Dashboard/stale UI term pass: update "Dashboard KPIs" at line 3, "Dashboard KPI counts" → "Apps page stats strip", "Recent Errors feed" → "Error Spotlight", "App Health grid" → "Handler health grid" at line 17 AND the `??? note` block below it, "Dashboard shows..." at line 110, "Dashboard displays..." at line 117. Do not start cross-reference updates on this file until both passes are planned
- `core-concepts/configuration/global.md`: "browser dashboard" → "web UI"
- `advanced/log-level-tuning.md`: "dashboard errors" → "web UI"
- `troubleshooting.md`: "Dashboard shows zeroed-out metrics" → update location

### Cross-page linking requirement

Each page in the Web UI section ends with a brief "Related pages" or "Next steps" section linking to the natural next page in both the monitoring and troubleshooting workflows. At minimum: Apps links to App Detail; App Detail links to Handlers and Logs; Handlers links back to App Detail for per-app drill-down. This satisfies AC#5 independently of the live UI's own navigation.

### Execution order

1. ~~**Screenshots**~~ — **DONE**. 16 screenshots (8 full-page + 8 cropped detail) captured in `docs/_static/web_ui_*.png`. Old screenshots deleted.
2. **Layout & Navigation** and **Overview** — establishes vocabulary all other pages reference
3. **Apps** and **App Detail** (index + 5 tab sub-pages) — the core pages most users interact with
4. **Handlers**, **Logs** — monitoring/troubleshooting pages
5. **Config** — utility page
6. **Cross-reference updates** — after new page structure is settled

## Convention Examples

These examples show the **target** writing style for the new pages. The current file content will be replaced — these examples are not present in the files yet.

### Doc page structure with screenshot and feature list

**Target style (illustrative):**

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

**Target style (illustrative):**

```markdown
!!! tip "Quick Navigation"
    Click any app card to navigate directly to the App Detail View.

!!! warning "No Authentication"
    The web UI does not currently include authentication.
    Only expose the hassette port on trusted networks.
```

### Config snippet include

**Target style (illustrative):**

```markdown
To disable the web UI entirely:

```toml title="disable-ui.toml"
--8<-- "snippets/disable-ui.toml"
```​
```

### Table for documenting columns/fields

**Target style (illustrative):**

```markdown
| Column | Description |
|--------|-------------|
| App | Name and key of the automation |
| Status | Current lifecycle state with color indicator |
| Actions | Stop, Reload, or Start buttons |
```

### Cross-page linking pattern

**Target style (illustrative):**

```markdown
See the [Apps page](apps.md) for details on managing your automations,
or the [Logs page](logs.md) for filtering and searching log entries.
```

## Alternatives Considered

### Alternative 1: Incremental patching (rejected)

Update only the factual errors in existing pages — fix "Dashboard" references, swap screenshots, and add stub pages for new features. This is faster but leaves the page structure misaligned with the actual UI (e.g., a "Dashboard" page that's been rewritten to describe the Apps page). Results in confusing navigation and doesn't address the structural mismatch.

### Alternative 2: Merge App Detail into Apps page (rejected)

Keep 7 pages instead of 8 by documenting app detail within the Apps page. Rejected because the App Detail content is substantial (5 tabs, each with distinct features) and would make the Apps page exceed 500 lines. A dedicated page provides better navigation for users looking for specific tab documentation.

### Alternative 3: One page per App Detail tab (adopted)

Split App Detail into sub-pages (index + one per tab). The outline-first gate confirmed this: ~22 H3 headings and ~7 column tables exceed both thresholds. The deeper mkdocs nav nesting is an acceptable tradeoff for focused, navigable pages. The index page covers shared elements (breadcrumb, header, instance switcher, multi-instance parent view) and the tab strip overview.

## Test Strategy

- **mkdocs build**: Run `mkdocs build --strict` to verify all internal links resolve, no missing images, and no build warnings
- **Manual review**: Read each page in the served docs site (`mkdocs serve`) and verify screenshots match descriptions
- **Cross-reference check**: Grep the full `docs/` directory for "dashboard" (case-insensitive) and "sessions page" to verify all old references are updated
- **Screenshot verification**: Compare each screenshot against the running UI to confirm accuracy
- **Link integrity**: Verify all cross-page links within the Web UI section and from external pages resolve correctly

## Documentation Updates

This IS the documentation update — no additional documentation changes needed beyond what's described in this design.

## Impact

**Files modified:** 3 existing Web UI doc pages rewritten (index.md, apps.md, logs.md), mkdocs.yml nav updated, ~10 cross-reference files updated
**Files created:** 9 new doc pages (layout.md, app-detail/index.md, app-detail/overview.md, app-detail/handlers.md, app-detail/code.md, app-detail/logs.md, app-detail/config.md, handlers.md, config.md), 16 new screenshots (8 full-page + 8 cropped detail)
**Files deleted:** 2 doc pages (dashboard.md, sessions.md), 2 old screenshots (web_ui_dashboard.png, web_ui_sessions.png)
**Blast radius:** Documentation only — no code, test, or infrastructure changes

## Open Questions

- **App Detail page length**: Resolved — outline-first gate executed. The 5 tabs produce ~22 H3 headings and ~7 column tables, exceeding both thresholds. Committed to sub-pages: `app-detail/index.md` (shared elements), plus `overview.md`, `handlers.md`, `code.md`, `logs.md`, `config.md` per tab. mkdocs nav and page structure updated accordingly.
- **Demo data for screenshots**: Resolved — `uv run python scripts/hassette_demo.py` starts HA container + hassette + Vite dev server using the 5 example apps (climate_controller, cover_scheduler, motion_lights, presence_tracker, security_monitor) and the demo HA database fixture. Prints `DEMO_FRONTEND_URL` when ready. Use this for all screenshot capture.
- **Sessions concept**: Resolved — sessions are being retired as a user-facing concept. The `sessions.md` page is deleted without replacement. The `database-telemetry.md` cross-references to sessions must be updated to remove or reframe session language (covered in the cross-reference plan). The "Since restart" preset is documented using "since the last restart" language, not "current session."
