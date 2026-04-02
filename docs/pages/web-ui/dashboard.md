# Dashboard

The dashboard is the landing page of the web UI. It provides a quick overview of system health, per-app telemetry, and recent errors.

![Dashboard](../../_static/web_ui_dashboard.png)

## KPI Strip

A row of health cards across the top summarizes the system at a glance:

| Card | Description |
|------|-------------|
| **Apps** | Total registered apps and how many are running. |
| **Error Rate** | Combined error rate across all handler invocations and job executions. Color-coded: green (healthy), yellow (elevated), red (critical). |
| **Handlers** | Total registered event handlers and their invocation count. |
| **Jobs** | Total scheduled jobs and their execution count. |
| **Uptime** | How long Hassette has been running (hours and minutes). |

## App Health Grid

Below the KPI strip, the **App Health** section displays a card for each registered app. Each card shows:

- **Display name** and **status badge** (running, stopped, failed, disabled).
- **Handler count** and **job count** — how many event listeners and scheduled jobs the app owns.
- **Invocations and executions** — total handler calls and job runs (shown when telemetry data exists).
- **Error rate** — percentage of invocations/executions that resulted in an error.
- **Health bar** — visual indicator of overall app health.
- **Last activity** — relative timestamp of the most recent invocation or execution.
- **Instance count** — shown as a badge when the app has multiple instances.

Click any app card to navigate to its [detail page](apps.md#app-detail-view).

A **Manage Apps** link at the bottom navigates to the full [Apps](apps.md) page.

## Recent Errors

The **Recent Errors** section lists the most recent handler and job errors. Each entry displays:

- **Error type** — the Python exception class (e.g. `ValueError`, `TimeoutError`).
- **Kind badge** — `handler` or `job`, indicating the source of the error.
- **App key** — links to the app detail page.
- **Method or job name** — the specific handler method or job that failed.
- **Relative timestamp** — when the error occurred.
- **Error message** — the exception message text.

When no errors exist, a "No recent errors. All systems healthy." message is displayed.

## Session Scope

Error and telemetry data can be scoped using the **session toggle** in the status bar. Choose between:

- **This Session** — only data from the current Hassette session.
- **All Time** — data across all sessions in the retention window.

See [Sessions](sessions.md) for more on how sessions work.

## Auto-Refresh

Dashboard data refreshes every 30 seconds and updates in real time when WebSocket messages arrive (e.g. app status transitions). Rapid updates are debounced to avoid excessive API calls.
