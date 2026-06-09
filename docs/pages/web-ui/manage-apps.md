# Manage Apps

The apps dashboard shows every registered automation at a glance: health status, recent errors, and lifecycle controls, all without leaving the browser.

The apps page is the landing page of the web UI. Navigating to `/` redirects to `/apps`.

## Check App Health

![Apps page table](../../_static/web_ui_apps.png)

The stats strip at the top shows aggregate counts: **TOTAL**, **RUNNING**, **FAILED**, **STOPPED**, **DISABLED**, **HANDLERS**, and **RUNS/HR**. A non-zero **FAILED** count turns that cell red. Zero means all automations are alive.

Below the strip, the app table shows one row per app with the following columns:

| Column | What it shows |
|--------|--------------|
| **APP** | Status dot, app key, and class name. An **auto** chip appears for apps discovered by directory scan rather than an explicit `hassette.toml` entry. |
| **STATUS** | Lifecycle state badge: `RUNNING`, `STOPPED`, `FAILED`, `DISABLED`, or `BLOCKED`. |
| **LAST ERROR** | Most recent error message, truncated. Click to expand the full message. Shows `—` when the app is healthy. |
| **RUNS** | An activity sparkline showing invocation frequency over the selected time window, plus the total run count. |
| **LAST FIRED** | Relative timestamp of the most recent handler or job execution, for example "3 min ago". Shows `—` if the app has never fired. |
| **ACTIONS** | Context-sensitive buttons based on current status. See [Start, Stop, and Reload](#start-stop-and-reload) below. |

Clicking a **LAST ERROR** cell expands the full error message and traceback inline:

![Error spotlight](../../_static/web_ui_detail_error_spotlight.png)

### Find a specific app

The search box above the table filters rows by app key and class name as you type. The status filter popover on the **STATUS** column header narrows the table to one lifecycle state. Per-status counts appear in the popover. Searching and status filtering work together.

### Drill into an app

Click any app row to open the App Detail view. The detail view shows health indicators, a handler list, recent activity, and error details across five tabs.

![App detail overview](../../_static/web_ui_app_detail_overview.png)

### Multi-instance apps

Apps with multiple instances show a parent row with a chevron and an instance count badge (e.g., "2 instances"). Click the chevron to expand into individual instance rows. Each instance row shows its own status dot, badge, last error, and action buttons. Click an instance name to open that instance's detail view.

## Start, Stop, and Reload

Action buttons appear in the **ACTIONS** column and in the App Detail header. Which buttons appear depends on the app's current status:

| Button | Available when | What it does |
|--------|---------------|-------------|
| **Start** | `STOPPED`, `FAILED`, or `DISABLED` | Initializes the app and begins processing events. |
| **Stop** | `RUNNING` | Shuts the app down gracefully and cancels its scheduled jobs. The app stops receiving events until started again. |
| **Reload** | `RUNNING` | Stops then starts the app, picking up code and config changes without restarting the Hassette process. |

**Reload** picks up changes to an app's Python file or its config in `hassette.toml`. Reloading one app does not affect other running apps. A full Hassette process restart is only needed for global settings, new integrations, or Hassette updates.

These actions call the REST API (`POST /apps/{key}/start`, `/stop`, `/reload`). The CLI does not expose start/stop/reload subcommands. See [CLI Commands](../cli/commands.md) for what the CLI offers.

## Understand App States

The **STATUS** badge on each row reflects the app's current lifecycle state.

| State | Meaning |
|-------|---------|
| `STARTING` | The app is running its `on_initialize` hook. |
| `RUNNING` | The app is processing events normally. |
| `STOPPED` | The app was stopped via the UI or REST API. It will not process events until started again. |
| `FAILED` | The app encountered an unhandled error. Check the **LAST ERROR** column or the App Detail error banner for the traceback. |
| `CRASHED` | The app crashed and cannot recover. Check the error details and restart manually. |
| `DISABLED` | The app has `enabled = false` in `hassette.toml`. **Start** enables it for this session. Setting `enabled = true` in config makes the change permanent. |
| `BLOCKED` | Another app has the [`@only_app`](../core-concepts/apps/lifecycle.md) decorator (restricts Hassette to running only that app, useful for focused debugging), excluding this app from running. The block resolves automatically when the blocking app is removed or reloaded. |

For the full lifecycle state machine and transition rules, see [Apps lifecycle](../core-concepts/apps/lifecycle.md).
