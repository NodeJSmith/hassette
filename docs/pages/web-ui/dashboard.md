# Dashboard

The dashboard is the landing page of the web UI. It provides a quick overview of system health, per-app telemetry, and recent errors.

![Dashboard](../../_static/web_ui_dashboard.png)

## KPI Strip

A row of health cards across the top summarizes the system at a glance:

| Card | Description |
|------|-------------|
| **Error Rate** | Combined error rate across all handler invocations and job executions, including both app and framework errors. Color-coded: green (healthy), yellow (elevated), red (critical). |
| **Apps** | Total registered apps and how many are running. |
| **Handlers** | Total registered event handlers and their invocation count. Counts reflect [persisted registrations](../core-concepts/database-telemetry.md#registration-persistence) and survive restarts. |
| **Jobs** | Total scheduled jobs and their execution count. Counts reflect persisted registrations and survive restarts. |
| **Uptime** | How long Hassette has been running (hours and minutes). |

## App Health Grid

Below the KPI strip, the **App Health** section displays a card for each registered app. Each card shows:

- **Display name** — the app's human-readable name. A status badge appears next to the name when the app is not running (stopped, failed, or disabled).
- **Handler count** and **job count** — how many event listeners and scheduled jobs the app owns.
- **Invocations and executions** — total handler calls and job runs (shown when telemetry data exists).
- **Error rate** — percentage of invocations/executions that resulted in an error (shown when errors exist).
- **Last activity** — relative timestamp of the most recent invocation or execution.
- **Instance count** — shown as a badge when the app has multiple instances.

Click any app card to navigate to its [detail page](apps.md#app-detail-view).

## Recent Errors

The **Recent Errors** section is a unified feed of the most recent handler and job errors from all sources — your apps and the framework. Each entry displays:

- **Error type** — the Python exception class (e.g. `ValueError`, `TimeoutError`).
- **Kind badge** — `handler` or `job`, indicating the source of the error.
- **Source** — for app errors, links to the app detail page. For framework errors, a **Framework** badge with the component name (e.g. Service Watcher, App Handler) is shown instead of a link.
- **Method or job name** — the specific handler method or job that failed.
- **Relative timestamp** — when the error occurred.
- **Error message** — the exception message text.
- **Traceback** — framework errors always include a full Python traceback, expandable inline. App errors include a traceback when one was captured.

When no errors exist, a "No recent errors. All systems healthy." message is displayed.

## System Health

Below the error feed, the **System Health** badge summarizes framework-level health — issues within Hassette itself rather than in your automations. The badge shows the framework error count (scoped by the session toggle); green means none.

## Session Scope

Error and telemetry data can be scoped using the **session toggle** in the status bar. Choose between:

- **This Session** — only data from the current Hassette session.
- **All Time** — data across all sessions in the retention window.

See [Sessions](sessions.md) for more on how sessions work.

## Auto-Refresh

Dashboard data refreshes when WebSocket messages arrive (e.g. app status transitions). Rapid updates are debounced to avoid excessive API calls. Data also refreshes automatically after a WebSocket reconnection.
