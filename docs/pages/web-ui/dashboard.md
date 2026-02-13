# Dashboard

The dashboard is the landing page of the web UI. It provides a quick overview of system health, running apps, event bus activity, and recent events.

![Dashboard](../../_static/web_ui_dashboard.png)

## System Health

The top-left widget shows the current system status:

- **Status badge** — `OK` (green) when everything is healthy, or `degraded`/`starting` during transitions.
- **WS Connected** — indicates the WebSocket connection to Home Assistant is active.
- **Uptime** — how long Hassette has been running.
- **Entities** — total number of Home Assistant entities tracked.
- **Apps** — number of loaded apps.

## Apps

The top-right widget summarizes app states:

- **Total** — all registered apps.
- **Running** (green) — apps that are active and healthy.
- **Failed** (red) — apps that encountered an error.

Click **Manage Apps** to navigate to the [Apps](apps.md) page.

## Event Bus

The bottom-left widget displays aggregate event bus metrics:

- **Listeners** — total number of registered event listeners across all apps.
- **Invocations** — total handler calls since startup.
- **Successful** (green) — handlers that completed without error.
- **Failed** — handlers that raised an exception.

## Recent Events

The bottom-right widget shows the last 10 events received from Home Assistant. Each entry displays the event type (e.g. `state_changed`) and the entity ID.

## Auto-Refresh

Dashboard data refreshes every 30 seconds and updates in real time when WebSocket messages arrive (e.g. state changes or app status transitions).
