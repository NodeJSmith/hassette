---
task_id: "T03"
title: "Add App Detail index, Overview tab, and Handlers tab pages"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#4", "FR#7", "FR#8", "AC#4"]
---

## Summary
Create the App Detail index page and the two most substantial tab sub-pages: Overview and Handlers. The index page documents shared elements (breadcrumb, header, instance switcher, multi-instance parent overview, tab strip). The Overview tab documents the monitoring surface (error spotlight, handler health grid, recent activity, embedded logs). The Handlers tab documents the troubleshooting surface (master-detail layout with listener/job detail panels).

Together these three pages carry the core of both the monitoring workflow (Alex) and troubleshooting workflow (Sam).

## Prompt
Create three new files in `docs/pages/web-ui/app-detail/`:

### 1. `index.md` — App Detail shared elements

Create the `app-detail/` directory first. This index page documents elements shared across all tabs:

- **Breadcrumb** — `apps / <app_key>` for single-instance, `apps / <app_key> / <instance_name>` for multi-instance
- **Instance switcher** — tab-like buttons with status dots, shown only on per-instance views of multi-instance apps. Use `![Instance switcher](../../../_static/web_ui_detail_instance_switcher.png)` screenshot
- **Header** — status dot + app key + Reload/Stop action buttons + metadata line (filename · ClassName · "auto" if auto-detected, or instance index)
- **Tab strip** — overview, handlers (with count badge), code, logs, config. Briefly describe what each tab shows with links to sub-pages
- **Multi-instance parent overview** — when visiting a multi-instance app without selecting an instance, shows a grid of instance cards (each with instance name, status, and click to navigate). Explain the flow: parent overview → click instance → instance switcher appears → tab content is scoped to that instance
- **Related pages** — link to Apps (go back to the list) and each tab sub-page

### 2. `overview.md` — Overview Tab

Documents the default tab when viewing an app's detail:

- **Error spotlight** (conditional) — only appears when handlers are currently failing. Shows handler name, error type (e.g., TypeError), truncated error message, and a "view" link to jump to the handler detail. Use `![Error spotlight](../../../_static/web_ui_detail_error_spotlight.png)`. Note explicitly that this section is hidden when all handlers are healthy.
- **Handler health grid** — responsive card grid showing all handlers and jobs. Each card: status indicator (green=healthy, red=failing, gray=no data), handler/job name, type chip (state change, interval, after, cron, daily, etc.), call/run count, avg duration, last active time.
- **Recent activity** — table with HANDLER, DURATION, TIME columns showing the most recent handler/job executions across all handlers for this app.
- **Embedded logs** — per-app log table at the bottom showing recent log entries scoped to this app. Has its own search field.
- Use `![Overview tab](../../../_static/web_ui_app_detail_overview.png)` as the hero screenshot
- **Related pages** — link to Handlers Tab (for drill-down into specific handlers)

### 3. `handlers.md` — Handlers Tab

Documents the most feature-rich tab — the master-detail handler/job explorer:

- **Stats strip** — HANDLERS count, INVOCATIONS count, SUCCESS RATE %, FAILED count, TIMED OUT count
- **Master-detail layout** — left panel shows handler/job list, right panel shows detail for the selected item. Empty state: "Select a handler or job to see details."

**Handler list (left panel):**
- Cards for each handler/job with: status indicator, type icon, type chip, handler name, trigger description (entity pattern, interval, cron expression, etc.), call/run count. Failing handlers show red square + "failing" badge + failed count in red.

**Listener detail (right panel — when an event handler is selected):**
- Kind badge + handler name + "failing" badge (if applicable)
- Registration source — the actual Python code that registered this handler (e.g., `self.bus.on_state_change(...)`)
- Modifier chips — debounce, throttle, once, priority, immediate, duration (only shown when configured)
- Source location — file path + line number + "view in code →" link (navigates to Code tab at that line)
- Error banner (conditional) — red panel with "Last Error — <ErrorType>", error message, "show traceback" link. Use `![Handler error](../../../_static/web_ui_detail_handler_error.png)`
- Stats grid — RUNS, SUCCESSFUL, LAST, FAILED, TIMED OUT, MIN, AVG, MAX duration
- Executions table — STATUS (green dot or red error type), TIMESTAMP, DURATION, EXECUTION ID for the most recent invocations

**Job detail (right panel — when a scheduled job is selected):**
- Same layout as listener detail but with: schedule chips (group, jitter), trigger detail (interval, cron, daily at, after delay), next run time

- Use `![Handlers tab](../../../_static/web_ui_app_detail_handlers.png)` as the hero screenshot
- **Related pages** — link to Overview Tab (go back), Code Tab (view source), Logs Tab (check logs for this app)

Read `frontend/src/components/app-detail/handlers-tab.tsx`, `listener-detail.tsx`, `job-detail.tsx`, and `handler-detail-layout.tsx` for exact structure.

## Focus
- The `app-detail/` directory does not exist yet — create it.
- The screenshot `web_ui_app_detail_handlers.png` shows the `sensor_health_check` failing handler selected with the error banner visible — this is the ideal reference for the error state documentation.
- The instance switcher screenshot (`web_ui_detail_instance_switcher.png`) shows PresenceTracker with "paulus" and "home_boy" tabs — good for the multi-instance documentation.
- Image paths from app-detail sub-pages use `../../../_static/` (one extra level up due to the sub-directory).
- The handlers tab is the most complex page — it has two distinct detail panel variants (listener vs job). Keep the documentation organized with clear `###` headings for each.

## Verify
- [ ] FR#2: Each page describes one concern — index covers shared elements, overview covers the overview tab, handlers covers the handlers tab
- [ ] FR#3: Every documented interaction (instance switcher, error spotlight "view" link, handler selection, "view in code" link, "show traceback") exists in the frontend
- [ ] FR#7: Monitoring workflow: reader understands how to check handler health at a glance via the overview tab
- [ ] FR#8: Troubleshooting workflow: reader can follow error spotlight → handler detail → error banner → traceback → "view in code" → logs
- [ ] FR#4: Screenshots referenced (`web_ui_app_detail_overview.png`, `web_ui_app_detail_handlers.png`, `web_ui_detail_error_spotlight.png`, `web_ui_detail_handler_error.png`, `web_ui_detail_instance_switcher.png`) exist in `docs/_static/`
- [ ] AC#4: Related pages sections link the Apps → App Detail → Handlers → Code/Logs sequence without gaps
