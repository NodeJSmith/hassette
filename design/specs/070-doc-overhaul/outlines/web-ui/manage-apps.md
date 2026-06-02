# Web UI — Manage Apps

**Status:** Stub (3 lines), needs full JTBD design from scratch
**Voice mode:** Procedural — "you" allowed, task-focused
**Page type:** Procedural (task-oriented)
**Reader's job:** Check whether their apps are healthy, and start/stop/reload individual apps from the browser.

## What was cut

The old outline was organized by UI element (stats strip, table, actions,
detail view, multi-instance, mobile). A reader managing apps doesn't think
in UI components — they think "is my app running?" and "how do I restart it?"

Reorganized around the two tasks readers actually perform: checking health
and taking action. The detail view is folded into "checking health" since
that's when you drill in. Multi-instance and mobile are notes within the
relevant sections, not standalone headings.

## Outline

### H2: Check App Health
What the apps dashboard shows at a glance: status badges (RUNNING, STOPPED,
ERROR), handler count, invocation count. How to read the stats strip.

How to find a specific app: search, status filter, sorting.

Drilling in: click an app to see its detail view — overview tab with health
indicators and recent activity.

Note: multi-instance apps show one row per instance with the instance name.

### H2: Start, Stop, and Reload
Where the action buttons are (apps table and app detail page). What each does:

- **Start** — initializes the app and begins processing events
- **Stop** — shuts down gracefully, cancels scheduled jobs
- **Reload** — stops then starts (picks up code and config changes)

When to use reload vs restart the whole process.

Note: these are the same actions as `hassette app start/stop/reload <key>` on
the CLI.

### H2: Understand App States
Brief table of app lifecycle states (INITIALIZING, RUNNING, STOPPED, ERROR)
and what each means. Link to Apps/Lifecycle for the full state machine.

## Snippet Inventory

No code snippets — UI documentation.

## Cross-Links

- **Links to:** Web UI overview, Debug Handler (if app shows errors), Apps/Lifecycle (state machine), CLI commands (app management)
- **Linked from:** Web UI overview
