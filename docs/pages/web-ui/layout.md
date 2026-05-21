# Layout & Navigation

Every page in the hassette web UI shares the same chrome: a sidebar for navigation, a status bar at the top, and a command palette for keyboard-driven navigation. Understanding these elements once means you can move efficiently through any page.

## Sidebar

The sidebar is the primary navigation surface. It stays visible on all pages and updates in real time as app statuses change.

![Sidebar](../../_static/web_ui_detail_sidebar.png)

### Wordmark and version

The hassette wordmark at the top of the sidebar is a link to the Apps page. The running hassette version (`v0.x.y`) appears below it.

### Command palette trigger

Below the wordmark, a "jump to…" button opens the command palette. The keyboard shortcut is shown alongside it — **Ctrl+K** on Windows/Linux, **⌘K** on macOS.

### Navigation items

Four top-level items link to the main pages:

| Item | Page |
|------|------|
| apps | [Apps](apps.md) — all automations |
| handlers | [Handlers](handlers.md) — cross-app handler table |
| logs | [Logs](logs.md) — global log viewer |
| config | [Config](config.md) — system configuration |

The active page is highlighted.

### APPS section

Below the top-level nav, the APPS section lists all loaded automations. A count badge shows the total number of apps.

**Filter apps** — A search input at the top of the section filters apps by display name or app key as you type. When filtering is active, the count badge shows `filtered/total` (e.g., `2/7`).

**Status groups** — Apps are grouped by lifecycle status: FAILING (handlers currently erroring), BLOCKED (waiting for a dependency), SLOW (execution timing out or cooling down), RUNNING, STOPPED, and DISABLED. Each group is collapsible and shows a count. When all apps are healthy, the RUNNING group is expanded by default; other groups expand when they contain apps.

**App entries** — Each app shows a colored status dot and its display name. Clicking an entry navigates to that app's detail page.

**"auto" chip** — Apps that hassette detected automatically from the app directory (not explicitly configured in `hassette.toml`) show a small `auto` chip next to their name.

**Multi-instance apps** — Apps with more than one instance show a collapse/expand chevron next to the app entry. Clicking it reveals the individual instance sub-items, each with its own status dot and instance name.

## Status bar

The status bar runs across the top of every page. It provides time-scoping controls, system uptime, WebSocket connection status, and the theme toggle.

![Status bar](../../_static/web_ui_detail_status_bar.png)

### Time-preset selector

Four buttons control the time window used for all telemetry counts and tables across the UI:

| Preset | What it shows |
|--------|---------------|
| Since restart | All data since the most recent hassette startup |
| 1h | Data from the past 1 hour |
| 24h | Data from the past 24 hours |
| 7d | Data from the past 7 days |

**Since restart** is not a "current session" view — it shows data from the last hassette startup to now, regardless of how long the process has been running. The other presets use wall-clock windows relative to the current time.

The selected preset is highlighted. Hassette persists your last-used preset across page reloads.

### Uptime display

Next to the preset buttons, the uptime counter shows how long hassette has been running since the last restart (e.g., "up 4h 32m").

### WebSocket connection indicator

A small dot on the right side of the status bar shows the WebSocket connection status. A steady green dot means the UI is receiving live updates. If the connection drops, the dot changes color and a text label appears ("Reconnecting..." or "Disconnected") until the connection is restored.

### Status indicators

The status bar's right section can show additional inline indicators when the system is degraded:

- **"N dropped"** — Appears when telemetry events are dropped due to buffer overflow, write failures, no active session, or during shutdown. The count shows total dropped events since the last restart.
- **"N handler errors"** — Appears when user-supplied error handlers raise exceptions or time out. Indicates your custom error-handling code is itself failing.

These are distinct from the amber "Telemetry degraded" [alert banner](#alert-banners), which covers database backpressure at the page level. The inline indicators provide at-a-glance counts without leaving the current page.

### Theme toggle

A sun/moon button toggles between light and dark mode. Your preference is saved across page reloads.

## Command palette

The command palette is a keyboard-first navigation tool that lets you jump to any page, app, handler, or action without using the mouse.

![Command palette](../../_static/web_ui_detail_command_palette.png)

**Open**: Press **Ctrl+K** (Windows/Linux) or **⌘K** (macOS), or click the "jump to…" button in the sidebar.

**Close**: Press **Escape** or click the backdrop.

### Sections

The palette organizes results into sections that only appear when they have matching items:

| Section | Contents |
|---------|----------|
| pages | The four top-level pages (apps, handlers, logs, config) |
| apps | All loaded apps, each with a status dot and app key |
| instances | Individual instances of multi-instance apps |
| handlers | All registered handlers across all apps |
| actions | Bulk operations: Reload all apps, Stop all failing, Open docs |

Typing in the search box filters all sections simultaneously.

### Keyboard navigation

| Key | Action |
|-----|--------|
| ↑ / ↓ | Move between results |
| Enter | Activate the selected item |
| Escape | Close the palette |

## Mobile navigation

On narrow viewports, the sidebar is replaced by a hamburger menu in the top-left corner. Tapping it opens a slide-in drawer with the same navigation items and app list. The status bar remains visible at the top.

## Alert banners

Two alert banners can appear at the top of the page, above the main content:

**Failed apps** — When one or more apps are in a failed state, a red alert banner lists the app names and their most recent error message. Clicking an app name navigates to its detail page.

**Telemetry degraded** — When the telemetry database is under backpressure (queue overflow or write failures), an amber warning banner appears. Some historical data may be missing while the banner is visible.

These banners are conditional — they do not appear when all apps are healthy and telemetry is writing normally.

## Related pages

- [Web UI Overview](index.md) — enabling, accessing, and configuring the web UI
- [Apps](apps.md) — monitor and manage your automations from the main app table
