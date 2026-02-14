# Dashboard

The dashboard is the landing page of the web UI. It provides a quick overview of system health, running apps, scheduled jobs, event bus activity, recent events, and recent logs.

![Dashboard](../../_static/web_ui_dashboard.png)

## System Health

The top-left panel shows the current system status:

- **Status badge** — `OK` (green) when everything is healthy, or `degraded`/`starting` during transitions.
- **WS Connected** — indicates the WebSocket connection to Home Assistant is active.
- **Uptime** — how long Hassette has been running.
- **Entities** — total number of Home Assistant entities tracked.
- **Apps** — number of loaded apps.

## Apps Summary

The top-right panel summarizes app states:

- **Total** — all registered apps.
- **Running** (green) — apps that are active and healthy.
- **Failed** (red) — apps that encountered an error.

Click **Manage Apps** to navigate to the [Apps](apps.md) page.

## Scheduled Jobs

The middle-left panel shows a summary of scheduled jobs:

- **Active** (green) — jobs that are currently scheduled and not cancelled.
- **Repeating** — jobs configured to run repeatedly.
- **Total** — total number of registered jobs.

Click **View All** to navigate to the [Scheduler](scheduler.md) page.

## Event Bus

Below the Scheduled Jobs panel, the Event Bus panel displays aggregate event bus metrics:

- **Listeners** — total number of registered event listeners across all apps.
- **Invocations** — total handler calls since startup.
- **Successful** (green) — handlers that completed without error.
- **Failed** — handlers that raised an exception.

## Recent Events

The middle-right panel shows the last 10 events received from Home Assistant. Each entry displays the event type (e.g. `state_changed`) and the entity ID.

## Recent Logs

The bottom panel spans the full width and shows the last 30 log entries. Each entry displays:

- **Level** — colored badge (DEBUG, INFO, WARNING, ERROR, CRITICAL).
- **Time** — when the entry was recorded, formatted as local time.
- **App** — originating app (links to app detail), or `—` for system-level messages.
- **Message** — truncated log message text.

Click **View All** to navigate to the [Logs](logs.md) page.

## Auto-Refresh

Dashboard data refreshes every 30 seconds and updates in real time when WebSocket messages arrive (e.g. state changes or app status transitions).
